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
    verification = read_private(directory/'meta-verification.json') if authorized else {}
    if verification.get('token_hash') != digest(stored.get('access_token','')):
        verification = {}
    accounts = verification.get('accounts',[])
    return {'configured':True,'authorized':authorized,'accounts_verified':bool(accounts),'accounts':accounts,
            'permissions':verification.get('permissions',[]),'checked_at':verification.get('checked_at'),
            'verification_notes':verification.get('notes',[]),'callback_url':callback,
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


def error_summary(error):
    """Só códigos numéricos e categorias locais; nunca texto bruto do provedor."""
    details=[]
    if isinstance(error.code,int):
        details.append(f'HTTP {error.code}')
    try:
        payload=json.loads(error.read(65536))
        value=payload.get('error',{}) if isinstance(payload,dict) else {}
        if not isinstance(value,dict):
            value={}
    except (ValueError,OSError):
        value={}
    finally:
        error.close()
    for key,label in [('code','código'),('error_subcode','subcódigo')]:
        if type(value.get(key)) is int:
            details.append(f'{label} {value[key]}')
    text=str(value.get('message','')).casefold()
    reason=''
    if value.get('code')==190:
        reason='A autorização pode ter expirado ou sido revogada.'
    elif 'image' in text and any(word in text for word in ['download','fetch','url','uri','format','jpeg']):
        reason='A Meta apontou um problema com a imagem ou com o endereço público dela.'
    elif any(word in text for word in ['permission','capability','not allowed','development mode']):
        reason='A Meta apontou uma restrição de permissões, tarefas ou configuração do aplicativo.'
    elif 'unsupported' in text or 'does not exist' in text:
        reason='A Meta não aceitou o objeto ou a operação solicitada; confira o acesso à conta.'
    return ' ('+'; '.join(details)+'). '+reason


def graph_read(settings, path, token, params=None):
    """Somente GET em destino fixo. Nunca registrar URL, cabeçalhos ou erros brutos."""
    if not re.fullmatch(r'[A-Za-z0-9_/]+',path):
        raise ValueError('Consulta da Meta inválida.')
    query = urllib.parse.urlencode(params or {})
    request = urllib.request.Request(f'https://graph.facebook.com/{settings["version"]}/{path}?{query}',
        headers={'Authorization':f'Bearer {token}','Accept':'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request,timeout=20) as response:
            result=json.loads(response.read(262144))
        if not isinstance(result,dict) or 'error' in result:
            raise ValueError('A Meta recusou a consulta. Confira as permissões e os ativos liberados no aplicativo.')
        return result
    except urllib.error.HTTPError as error:
        # O texto do provedor pode conter dados privados; não é retornado nem logado.
        detail=error_summary(error)
        raise ValueError('A Meta recusou a consulta'+detail) from None
    except (urllib.error.URLError,OSError,TimeoutError,json.JSONDecodeError):
        raise ValueError('Não foi possível consultar a Meta. Confira o acesso a graph.facebook.com no servidor e tente novamente.') from None


def verify_accounts(directory):
    settings=config(directory)
    stored=read_private(directory/'meta-connection.json')
    token=stored.get('access_token')
    if not token or stored.get('app_id')!=settings['app_id']:
        raise ValueError('Conecte à Meta antes de verificar as contas.')
    (directory/'meta-verification.json').unlink(missing_ok=True)
    # A introspecção informa validade, escopos e ativos efetivamente concedidos.
    # input_token é exigido pela API de introspecção; nunca imprimir esta URL.
    debug=graph_read(settings,'debug_token',settings['app_id']+'|'+settings['app_secret'],{'input_token':token}).get('data',{})
    if not isinstance(debug,dict) or debug.get('is_valid') is not True or str(debug.get('app_id'))!=settings['app_id']:
        raise ValueError('A autorização não está válida para este aplicativo. Conecte novamente à Meta.')
    now=int(time.time())
    for field in ['expires_at','data_access_expires_at']:
        expiration=debug.get(field)
        if isinstance(expiration,(int,float)) and expiration>0 and expiration<=now:
            raise ValueError('A autorização expirou. Conecte novamente à Meta.')
    scopes=debug.get('scopes',[])
    scopes=sorted({s for s in scopes if isinstance(s,str) and re.fullmatch(r'[a-z_]+',s)}) if isinstance(scopes,list) else []
    proof=hmac.new(settings['app_secret'].encode(),token.encode(),hashlib.sha256).hexdigest()
    accounts,notes,targets=[],[],set()
    granular=debug.get('granular_scopes',[])
    if isinstance(granular,list):
        for grant in granular:
            if isinstance(grant,dict) and grant.get('scope')=='instagram_basic':
                values=grant.get('target_ids',[])
                for target in (values if isinstance(values,list) else [])[:20]:
                    if isinstance(target,str) and target.isdecimal():
                        targets.add(target)
    # Esta rota exige páginas concedidas; o modelo Unified Login pode conceder
    # somente Instagram, o que não implica autorização de uma página Facebook.
    if 'pages_show_list' in scopes:
        try:
            pages=graph_read(settings,'me/accounts',token,{'fields':'id,name,instagram_business_account{id,username}','limit':50,'appsecret_proof':proof})
            values=pages.get('data',[])
            if not isinstance(values,list):
                raise ValueError('A Meta retornou uma lista de páginas inválida. Tente novamente.')
            for page in values[:50]:
                if not isinstance(page,dict) or not str(page.get('id','')).isdecimal():
                    continue
                accounts.append({'channel':'Facebook','id':str(page['id']),'name':str(page.get('name','Página do Facebook'))[:200],
                    'publishing_scope_granted':'pages_manage_posts' in scopes})
                instagram=page.get('instagram_business_account')
                if isinstance(instagram,dict) and str(instagram.get('id','')).isdecimal():
                    targets.add(str(instagram['id']))
            if isinstance(pages.get('paging'),dict) and pages['paging'].get('next'):
                notes.append('A consulta foi limitada às primeiras 50 páginas. A lista pode estar incompleta.')
        except ValueError as error:
            notes.append(str(error))
    else:
        notes.append('pages_show_list não foi concedida. Nenhuma página Facebook foi confirmada.')
    for target in sorted(targets)[:20]:
        try:
            account=graph_read(settings,target,token,{'fields':'id,username','appsecret_proof':proof})
            if not account.get('username') or str(account.get('id'))!=target:
                notes.append('Uma conta Instagram não pôde ser identificada nesta consulta.')
                continue
            accounts.append({'channel':'Instagram','id':target,'name':str(account['username'])[:200],
                'publishing_scope_granted':'instagram_content_publish' in scopes})
        except ValueError as error:
            notes.append(str(error))
    if not accounts:
        notes.append('O token é válido, mas nenhuma conta foi identificada. Confira os ativos e permissões na configuração do login da Meta.')
    result={'token_hash':digest(token),'accounts':accounts,'permissions':scopes,'checked_at':now,'notes':list(dict.fromkeys(notes))}
    try:
        write_private(directory/'meta-verification.json',result)
    except OSError:
        raise ValueError('Não foi possível salvar a verificação no servidor. Confira as permissões do disco.') from None
    return result


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
    (directory/'meta-verification.json').unlink(missing_ok=True)
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
