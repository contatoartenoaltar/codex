"""Login oficial da Meta. Segredos restritos ao disco privado do servidor."""
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CALLBACK = '/auth/meta/callback'
VERSION = 'v24.0'


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS meta_oauth_states (
        state_hash TEXT PRIMARY KEY, browser_hash TEXT NOT NULL,
        session_hash TEXT NOT NULL, expires INTEGER NOT NULL)''')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def write_private(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.meta-')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_private(path):
    try:
        if path.stat().st_mode & 0o077:
            raise ValueError('Arquivo da Meta precisa de permissão privada (600).')
        result = json.loads(path.read_text())
        if not isinstance(result, dict):
            raise ValueError('Configuração da Meta inválida.')
        return result
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        raise ValueError('Não foi possível ler a configuração privada da Meta.') from None


def config(directory):
    result = read_private(directory / 'meta-config.json')
    for field, variable in [('app_id','ARTENOALTAR_META_APP_ID'),('app_secret','ARTENOALTAR_META_APP_SECRET'),('config_id','ARTENOALTAR_META_CONFIG_ID')]:
        if os.environ.get(variable):
            result[field] = os.environ[variable]
    result.setdefault('version', VERSION)
    if not all(isinstance(result.get(k), str) and result[k] for k in ['app_id','app_secret','config_id']):
        raise ValueError('Configure as credenciais da Meta no terminal seguro do servidor.')
    if not re.fullmatch(r'\d+',result['app_id']) or not re.fullmatch(r'\d+',result['config_id']) or not re.fullmatch(r'v\d+\.0',result['version']):
        raise ValueError('Confira os identificadores e a versão da API da Meta.')
    return result


def callback_url():
    origin = os.environ.get('ARTENOALTAR_ORIGIN','')
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('Configure o endereço HTTPS do sistema antes de conectar a Meta.')
    return origin + CALLBACK


def status(directory):
    try:
        settings = config(directory)
        callback = callback_url()
    except ValueError as error:
        return {'configured':False,'authorized':False,'accounts_verified':False,'message':str(error),'callback_url':None}
    stored = read_private(directory / 'meta-connection.json')
    expires = stored.get('expires_at')
    expired = isinstance(expires,(int,float)) and expires <= time.time()
    authorized = bool(stored.get('access_token')) and not expired and stored.get('app_id') == settings['app_id']
    return {'configured':True,'authorized':authorized,'accounts_verified':False,'callback_url':callback,
            'message':('Autorização recebida. Contas e permissões de publicação ainda precisam ser verificadas.' if authorized else 'Autorização expirada. Conecte novamente.' if expired else 'Pronto para solicitar autorização à Meta.')}


def start(conn, directory, session_hash):
    settings = config(directory)
    redirect = callback_url()
    state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = int(time.time())
    conn.execute('DELETE FROM meta_oauth_states WHERE expires<=? OR session_hash=?',(now,session_hash))
    conn.execute('INSERT INTO meta_oauth_states VALUES(?,?,?,?)',(digest(state),digest(browser),session_hash,now+600))
    query = urllib.parse.urlencode({'client_id':settings['app_id'],'config_id':settings['config_id'],
        'redirect_uri':redirect,'response_type':'code','override_default_response_type':'true','state':state})
    return f'https://www.facebook.com/{settings["version"]}/dialog/oauth?{query}', browser


def consume(conn, query, browser):
    if len(query.get('state',[])) != 1 or len(query.get('code',[])) > 1:
        return False
    state = query.get('state',[''])[0]
    if not state or len(state)>256 or not browser or len(browser)>256:
        return False
    conn.execute('BEGIN IMMEDIATE')
    row = conn.execute('SELECT browser_hash,session_hash,expires FROM meta_oauth_states WHERE state_hash=?',(digest(state),)).fetchone()
    if not row or not hmac.compare_digest(row[0],digest(browser)):
        return False
    conn.execute('DELETE FROM meta_oauth_states WHERE state_hash=?',(digest(state),))
    valid_session = conn.execute('SELECT 1 FROM sessions WHERE token_hash=? AND expires>?',(row[1],int(time.time()))).fetchone()
    return row[2]>time.time() and bool(valid_session)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def exchange(directory, code):
    if not code or len(code)>8192:
        raise ValueError('A Meta não retornou um código de autorização válido.')
    settings = config(directory)
    request = urllib.request.Request(f'https://graph.facebook.com/{settings["version"]}/oauth/access_token',
        data=urllib.parse.urlencode({'client_id':settings['app_id'],'client_secret':settings['app_secret'],
            'redirect_uri':callback_url(),'code':code}).encode(),
        headers={'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'})
    # Não seguir redirecionamentos com o segredo do aplicativo. Preserva proxy/TLS padrão.
    try:
        with urllib.request.build_opener(NoRedirect).open(request,timeout=25) as response:
            result = json.loads(response.read(65536))
        token = result.get('access_token')
        expires = result.get('expires_in')
        if not isinstance(token,str) or not token or result.get('error'):
            raise ValueError('A Meta não retornou uma autorização válida.')
        if expires is not None and (isinstance(expires,bool) or not isinstance(expires,(int,float)) or not math.isfinite(expires) or expires<=0):
            raise ValueError('A Meta retornou uma validade inválida. Conecte novamente.')
    except (urllib.error.URLError,TimeoutError,OSError,json.JSONDecodeError,AttributeError):
        raise ValueError('Não foi possível confirmar a autorização com a Meta. Confira a configuração do aplicativo e o acesso de rede do servidor e tente novamente.') from None
    try:
        write_private(directory/'meta-connection.json',{'access_token':token,'authorized_at':int(time.time()),
            'expires_at':int(time.time()+expires) if expires else None,'app_id':settings['app_id']})
    except OSError:
        raise ValueError('Não foi possível guardar a autorização no disco privado do servidor. Confira as permissões e tente novamente.') from None


def disconnect(conn, directory):
    (directory/'meta-connection.json').unlink(missing_ok=True)
    conn.execute('DELETE FROM meta_oauth_states')


if __name__ == '__main__':
    import getpass
    import app
    import sys
    if sys.argv[1:] != ['configure']:
        raise SystemExit('Uso: python3.12 meta.py configure')
    app_id = input('ID do aplicativo [2100056530644878]: ').strip() or '2100056530644878'
    config_id = input('ID da configuração [1296615742590788]: ').strip() or '1296615742590788'
    if not app_id.isdecimal() or not config_id.isdecimal():
        raise SystemExit('Identificadores inválidos.')
    secret = getpass.getpass('Chave secreta do aplicativo (não aparece ao digitar): ').strip()
    if not secret:
        raise SystemExit('Chave não informada. Nenhuma alteração foi salva.')
    write_private(app.DB.parent/'meta-config.json',{'app_id':app_id,'config_id':config_id,'app_secret':secret,'version':VERSION})
    # Ao mudar as credenciais, uma autorização anterior deixa de ser válida para este app.
    (app.DB.parent/'meta-connection.json').unlink(missing_ok=True)
    print('Configuração privada salva no servidor. Recarregue o aplicativo Web.')
