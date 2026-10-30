"""Gera ZIP privado SOMENTE após verificar o endpoint HTTPS implantado.

Uso: python package_social_plugin.py https://artenoaltar.pythonanywhere.com/mcp
Ou acrescente --configured-key para reutilizar o arquivo privado mcp-key.txt.
Credencial nunca exibida ou gravada no pacote; comandos administrativos, não ferramentas MCP.
"""
import getpass
import json
import argparse
import urllib.request
import urllib.parse
import zipfile
from pathlib import Path

import social_mcp


def package(url, token, destination):
    root = Path(__file__).parent / 'plugin'
    manifest = json.loads((root / 'plugin.json').read_text())
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'artenoaltar.pythonanywhere.com'
            or parsed.path != '/mcp' or parsed.query or parsed.fragment or parsed.username
            or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('Use apenas o endpoint HTTPS implantado no domínio da Arte no Altar.')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            raise ValueError('Redirecionamento recusado para proteger a credencial.')
    opener = urllib.request.build_opener(NoRedirect())
    def request(method, params=None):
        body = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
            'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': social_mcp.VERSION})
        with opener.open(req, timeout=30) as response:
            value = json.loads(response.read(1024 * 1024))
        if 'error' in value:
            raise ValueError('Endpoint retornou erro MCP.')
        return value['result']
    info = request('initialize', {'protocolVersion': social_mcp.VERSION,
                   'capabilities': {}, 'clientInfo': {'name': 'arte-no-altar-validator', 'version': manifest['version']}})
    if info.get('protocolVersion') != social_mcp.VERSION:
        raise ValueError('Versão do protocolo não validada.')
    found = request('tools/list').get('tools', [])
    if {x['name'] for x in found} != {x[0] for x in social_mcp.TOOLS}:
        raise ValueError('Ferramentas inesperadas; não gerar o pacote.')
    for actual in found:
        expected = next(x[2] for x in social_mcp.TOOLS if x[0] == actual['name'])
        if actual['inputSchema'] != expected:
            raise ValueError('Schema remoto diferente do código revisado.')
    check = request('tools/call', {'name': 'social_list_accounts', 'arguments': {}})
    if check.get('isError'):
        raise ValueError('Não foi possível consultar contas.')
    config = {'$schema': 'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json',
              'mcpServers': {'arte-no-altar': {'type': 'streamable-http', 'url': url,
                'extensions': {'com.openai': {'auth': {'type': 'api_key', 'headerScheme': 'bearer'}}}}}}
    assert len(manifest['extensions']['com.openai']['interface']['shortDescription']) <= 30
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*')):
            if path.is_file() and not path.is_symlink():
                archive.write(path, path.relative_to(root))
        archive.writestr('mcp.json', json.dumps(config, ensure_ascii=False, indent=2))
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('--configured-key', action='store_true',
                        help='Usar mcp-key.txt no diretório privado do banco, sem exibir a chave')
    args = parser.parse_args()
    try:
        import app
        version = json.loads((Path(__file__).parent / 'plugin' / 'plugin.json').read_text())['version']
        token = ((app.DB.parent / 'mcp-key.txt').read_text().strip() if args.configured_key
                 else getpass.getpass('Chave exclusiva da integração: '))
        app.DB.parent.mkdir(parents=True, exist_ok=True)
        output = package(args.url, token, app.DB.parent / f'arte-no-altar-{version}.zip')
    except Exception:
        raise SystemExit('Pacote não gerado: verificação HTTPS/MCP falhou. Confira implantação, credencial e schemas sem enviar segredos ao chat.') from None
    print(f'Pacote gerado: {output}. Confira as ferramentas no aplicativo e valide o novo agendamento antes de uso operacional.')
