"""Catálogo privado de originais do Drive. Somente GET; não cria artes nem publica."""
import argparse
from collections import Counter, deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request

API = 'https://www.googleapis.com/drive/v3/files'
TOKEN_URI = 'https://oauth2.googleapis.com/token'
SCOPE = 'https://www.googleapis.com/auth/drive.readonly'
FOLDER_MIME = 'application/vnd.google-apps.folder'
SHORTCUT_MIME = 'application/vnd.google-apps.shortcut'
CONFIG_FILE = 'drive-source.json'
CREDENTIALS_FILE = 'drive-service-account.json'
CATALOG_FILE = 'drive-catalog.json'
MAX_JSON = 2 * 1024 * 1024
MAX_FILES = 20000
MAX_FOLDERS = 2000
MAX_PAGES = 200


class DriveError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise DriveError('Redirecionamento recusado para proteger a conexão com o Drive.')


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,160}', value):
        raise DriveError('Informe um identificador válido de pasta do Drive.')
    return value


def folder_id(value):
    if not isinstance(value, str):
        raise DriveError('Informe o link ou identificador da pasta.')
    value = value.strip()
    if value.startswith('https://'):
        parsed = urllib.parse.urlsplit(value)
        if parsed.netloc != 'drive.google.com' or parsed.fragment:
            raise DriveError('Use um link HTTPS de pasta em drive.google.com.')
        match = re.fullmatch(r'/drive/(?:u/\d+/)?folders/([A-Za-z0-9_-]+)/?', parsed.path)
        if not match:
            raise DriveError('Use o link da pasta de originais, não de um arquivo.')
        value = match[1]
    return identifier(value)


def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.drive-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path, limit=65536):
    try:
        if path.is_symlink() or path.stat().st_size > limit:
            raise DriveError('Arquivo de configuração privado inválido.')
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise DriveError('Arquivo de configuração privado inválido.')
        return value
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise DriveError('Configuração do Drive ausente ou inválida. Confira os arquivos privados na hospedagem.') from None


def account_info(directory):
    info = read_json(directory / CREDENTIALS_FILE)
    email = info.get('client_email', '')
    if (info.get('type') != 'service_account' or info.get('token_uri') != TOKEN_URI
            or info.get('universe_domain', 'googleapis.com') != 'googleapis.com'
            or not isinstance(email, str)
            or not re.fullmatch(r'[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\.gserviceaccount\.com', email)
            or not isinstance(info.get('private_key'), str)):
        raise DriveError('Use o JSON original de uma conta de serviço Google, com endpoint oficial de autenticação.')
    return info


class TokenTransport:
    """Transporte esperado por google-auth, restrito ao endpoint OAuth oficial."""
    def __init__(self, opener=None):
        self.opener = opener or urllib.request.build_opener(NoRedirect())

    def __call__(self, url, method='GET', body=None, headers=None, timeout=25, **kwargs):
        if url != TOKEN_URI or method != 'POST':
            raise DriveError('Destino de autenticação Google não permitido.')
        request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
        try:
            response = self.opener.open(request, timeout=min(timeout or 25, 25))
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            data = response.read(65537)
            if len(data) > 65536:
                raise DriveError('Resposta de autenticação Google inválida.')
            return type('TokenResponse', (), {'status': response.getcode(), 'data': data,
                                             'headers': dict(response.headers)})()


def credentials(directory):
    info = account_info(directory)
    try:
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_info(info, scopes=[SCOPE])
    except ImportError:
        raise DriveError('Instale as dependências com o mesmo Python usado pelo sistema.') from None
    except Exception:
        raise DriveError('O JSON da conta de serviço não pôde ser validado. Não envie a chave ao chat.') from None


class DriveClient:
    def __init__(self, credential, opener=None):
        self.credential = credential
        self.opener = opener or urllib.request.build_opener(NoRedirect())
        self.transport = TokenTransport()

    def get(self, path='', params=None):
        if path:
            identifier(path)
        url = API + ('/' + path if path else '')
        if params:
            url += '?' + urllib.parse.urlencode(params)
        headers = {'Accept': 'application/json'}
        try:
            self.credential.before_request(self.transport, 'GET', url, headers)
            request = urllib.request.Request(url, headers=headers, method='GET')
            with self.opener.open(request, timeout=25) as response:
                raw = response.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                raise DriveError('A resposta do Drive excedeu o limite. Catálogo anterior preservado.')
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get('error'):
                raise DriveError('O Drive não confirmou a consulta.')
            return data
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 404):
                raise DriveError('Acesso ao Drive não confirmado. Confira API ativa, conta de serviço e compartilhamento da pasta como Leitor.') from None
            raise DriveError('Falha temporária ao consultar o Drive. Tente novamente mais tarde.') from None
        except DriveError:
            raise
        except Exception:
            raise DriveError('Não foi possível consultar o Drive. Confira a autenticação e o acesso de rede da hospedagem.') from None

    def catalog(self, root_id):
        root_id = identifier(root_id)
        root = self.get(root_id, {'fields': 'id,name,mimeType', 'supportsAllDrives': 'true'})
        if root.get('id') != root_id or root.get('mimeType') != FOLDER_MIME:
            raise DriveError('A origem não foi confirmada como pasta do Drive.')
        pending = deque([(root_id, [])])
        visited = set()
        files, folders = {}, {}
        pages = 0
        skipped_shortcuts = 0
        while pending:
            current, path = pending.popleft()
            if current in visited:
                continue
            visited.add(current)
            if len(visited) > MAX_FOLDERS:
                raise DriveError('Limite de subpastas excedido. Catálogo anterior preservado.')
            token = None
            seen_tokens = set()
            while True:
                pages += 1
                if pages > MAX_PAGES:
                    raise DriveError('Limite de páginas do Drive excedido. Catálogo anterior preservado.')
                params = {'q': f"'{current}' in parents and trashed = false", 'pageSize': 1000,
                          'fields': 'nextPageToken,incompleteSearch,files(id,name,mimeType,size,modifiedTime,md5Checksum)',
                          'supportsAllDrives': 'true', 'includeItemsFromAllDrives': 'true'}
                if token:
                    params['pageToken'] = token
                response = self.get(params=params)
                entries = response.get('files')
                if response.get('incompleteSearch') or not isinstance(entries, list):
                    raise DriveError('O Drive retornou uma consulta incompleta. Catálogo anterior preservado.')
                for item in entries:
                    if not isinstance(item, dict):
                        raise DriveError('Metadados do Drive inválidos.')
                    ident = identifier(item.get('id'))
                    name, mime = item.get('name'), item.get('mimeType')
                    if not isinstance(name, str) or not isinstance(mime, str):
                        raise DriveError('Metadados do Drive inválidos.')
                    if mime == SHORTCUT_MIME:
                        skipped_shortcuts += 1
                        continue
                    if mime == FOLDER_MIME:
                        folders[ident] = {'id': ident, 'name': name, 'path': path + [name]}
                        pending.append((ident, path + [name]))
                    else:
                        files[ident] = {key: item[key] for key in ('id', 'name', 'mimeType', 'size', 'modifiedTime', 'md5Checksum') if key in item}
                        files[ident]['path'] = path + [name]
                    if len(files) + len(folders) > MAX_FILES:
                        raise DriveError('Limite de arquivos excedido. Catálogo anterior preservado.')
                token = response.get('nextPageToken')
                if not token:
                    break
                if not isinstance(token, str) or token in seen_tokens:
                    raise DriveError('Paginação inválida. Catálogo anterior preservado.')
                seen_tokens.add(token)
        counts = Counter(item['mimeType'] for item in files.values())
        return {'provider': 'google_drive', 'folder_id': root_id, 'folder_name': root.get('name', ''),
                'checked_at': datetime.now(timezone.utc).isoformat(), 'complete': True,
                'total_files': len(files), 'total_images': sum(n for mime, n in counts.items() if mime.startswith('image/')),
                'formats': dict(sorted(counts.items())), 'skipped_shortcuts': skipped_shortcuts,
                'subfolders': sorted(folders.values(), key=lambda item: item['path']),
                'files': sorted(files.values(), key=lambda item: item['path'])}


def configure(directory, source):
    ident = folder_id(source)
    info = account_info(directory)
    (directory / CREDENTIALS_FILE).chmod(0o600)
    write_private(directory / CONFIG_FILE, {'provider': 'google_drive', 'folder_id': ident,
                                           'role': 'originals', 'access_verified': False})
    return info['client_email']


def inspect(directory, client=None):
    config = read_json(directory / CONFIG_FILE)
    ident = identifier(config.get('folder_id'))
    client = client or DriveClient(credentials(directory))
    catalog = client.catalog(ident)
    write_private(directory / CATALOG_FILE, catalog)
    write_private(directory / CONFIG_FILE, config | {'access_verified': True,
                                                   'checked_at': catalog['checked_at']})
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    configure_parser = sub.add_parser('configure')
    configure_parser.add_argument('--folder', required=True, help='Link ou ID da pasta de originais')
    sub.add_parser('inspect')
    args = parser.parse_args()
    import app
    try:
        if args.command == 'configure':
            email = configure(app.DB.parent, args.folder)
            print('Compartilhe somente a pasta de originais com esta conta, como Leitor:')
            print(email)
            print('Origem configurada. O acesso ainda não foi testado.')
        else:
            result = inspect(app.DB.parent)
            summary = {key: result[key] for key in ('folder_name', 'total_files', 'total_images', 'formats', 'skipped_shortcuts')}
            summary['subfolders'] = [item['path'] for item in result['subfolders']]
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            print('Catálogo privado salvo. Consulta somente de leitura; nenhuma arte ou publicação foi criada.')
    except (DriveError, OSError):
        import sys
        error = sys.exception()
        raise SystemExit(str(error) if isinstance(error, DriveError) else 'Não foi possível guardar a configuração privada na hospedagem.') from None


if __name__ == '__main__':
    main()
