"""Transporte de Stories. Nada é enviado ao importar ou construir o cliente.

A credencial é recebida explicitamente, ou lida da autorização já existente
somente quando o acionamento de Stories está configurado e habilitado.
"""
import hashlib
import hmac
import io
import json
import math
from pathlib import Path
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image

from .queue import ACCOUNT


MAX_RESPONSE = 262144
MAX_IMAGE = 5 * 1024 * 1024
SCOPES = {'instagram_basic', 'instagram_content_publish', 'pages_show_list',
          'pages_read_engagement', 'pages_manage_posts'}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]{0,39}', value):
        raise ValueError('Identificador da Meta inválido.')
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirecionamento da Meta recusado.')


def credentials(directory):
    """Leitura somente, sem renovar token ou atualizar verificação do feed."""
    import meta
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError('A autorização precisa estar em um diretório local.')
    for name in ('meta-config.json', 'meta-connection.json'):
        if (directory / name).is_symlink():
            raise ValueError('A autorização precisa estar em arquivos privados locais.')
    settings = meta.config(directory)
    connection = meta.read_private(directory / 'meta-connection.json')
    expiry = connection.get('expires_at')
    if (connection.get('app_id') != settings['app_id'] or
            not isinstance(connection.get('access_token'), str) or not connection['access_token'] or
            isinstance(expiry, bool) or
            (expiry is not None and (not isinstance(expiry, (int, float)) or not math.isfinite(expiry) or expiry <= time.time()))):
        raise ValueError('A autorização existente da Meta não está disponível ou está expirada.')
    return settings, connection['access_token']


class MetaClient:
    simulation = False
    requires_staging = True

    def __init__(self, settings, token, account_id, *, opener=None):
        self.account_id = identifier(account_id)
        if (not isinstance(settings.get('version'), str) or
                not re.fullmatch(r'v[1-9][0-9]*\.0', settings['version']) or
                not isinstance(settings.get('app_secret'), str) or not settings['app_secret'] or
                not isinstance(token, str) or not token):
            raise ValueError('Configuração da Meta inválida.')
        self.settings = dict(settings)
        self.token = token
        self.opener = opener if opener is not None else urllib.request.build_opener(NoRedirect)
        self.page = None

    @classmethod
    def from_directory(cls, directory, account_id):
        settings, token = credentials(directory)
        return cls(settings, token, account_id)

    def _request(self, method, path, data=None, *, token=None, image=None):
        if (method not in ('GET', 'POST') or
                not re.fullmatch(r'(?:me/(?:accounts|permissions)|[1-9][0-9]{0,39}(?:/(?:photos|media|media_publish))?)', path)):
            raise ValueError('Operação da Meta não permitida.')
        token = self.token if token is None else token
        proof = hmac.new(self.settings['app_secret'].encode(), token.encode(), hashlib.sha256).hexdigest()
        fields = dict(data or {}) | {'appsecret_proof': proof}
        url = f'https://graph.facebook.com/{self.settings["version"]}/{path}'
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
        body = None
        if method == 'GET':
            url += '?' + urllib.parse.urlencode(fields)
        elif image is None:
            body = urllib.parse.urlencode(fields).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        else:
            if not path.endswith('/photos') or len(image) > MAX_IMAGE:
                raise ValueError('Imagem de apoio inválida.')
            boundary = 'Story' + secrets.token_hex(16)
            parts = []
            for key, value in fields.items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="source"; filename="story.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode())
            parts.extend((image, f'\r\n--{boundary}--\r\n'.encode()))
            body = b''.join(parts)
            headers['Content-Type'] = 'multipart/form-data; boundary=' + boundary
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=5) as response:
                raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError('Resposta da Meta excedeu o limite.')
            result = json.loads(raw)
            if not isinstance(result, dict) or 'error' in result:
                raise ValueError('Resposta da Meta não confirmou a operação.')
            return result
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            # Não devolver corpo, URL, cabeçalhos ou mensagem bruta do provedor.
            raise ValueError('A Meta não confirmou a operação de Story; confira antes de repetir.') from None

    def verify_account(self, account_id):
        if account_id != self.account_id:
            raise ValueError('A conta do Story mudou.')
        self.page = None
        permissions = self._request('GET', 'me/permissions').get('data', [])
        if not isinstance(permissions, list):
            raise ValueError('Não foi possível conferir as permissões da conta.')
        granted = {p.get('permission') for p in permissions if isinstance(p, dict) and p.get('status') == 'granted'}
        if not SCOPES.issubset(granted):
            raise ValueError('A autorização não inclui as permissões necessárias para Stories.')
        account = self._request('GET', self.account_id, {'fields': 'id,username,account_type'})
        if (str(account.get('id')) != self.account_id or account.get('username') != ACCOUNT or
                account.get('account_type') != 'BUSINESS'):
            raise ValueError('O destino precisa ser a conta empresarial @arte.no.altar.')
        pages = self._request('GET', 'me/accounts',
                              {'fields': 'id,instagram_business_account{id},access_token', 'limit': 50}).get('data', [])
        if not isinstance(pages, list):
            raise ValueError('Não foi possível conferir as páginas concedidas.')
        matches = [p for p in pages if isinstance(p, dict) and
                   isinstance(p.get('instagram_business_account'), dict) and
                   str(p['instagram_business_account'].get('id')) == self.account_id]
        if len(matches) != 1:
            raise ValueError('A página vinculada ao Instagram não foi identificada sem ambiguidade.')
        page = matches[0]
        identifier(str(page.get('id')))
        if not isinstance(page.get('access_token'), str) or not page['access_token']:
            raise ValueError('A autorização da página vinculada não está disponível.')
        self.page = page
        return {'id': self.account_id, 'username': ACCOUNT, 'account_type': 'BUSINESS', 'stories_allowed': True}

    def stage_image(self, image):
        if self.page is None:
            raise ValueError('Confira a conta antes de enviar a imagem.')
        image = Path(image)
        if image.is_symlink() or image.stat().st_size > MAX_IMAGE:
            raise ValueError('Imagem do Story inválida.')
        raw = image.read_bytes()
        with Image.open(io.BytesIO(raw)) as photo:
            if photo.format != 'JPEG' or photo.size != (1080, 1920):
                raise ValueError('O Story precisa ser um JPEG 1080 × 1920.')
            photo.verify()
        result = self._request('POST', str(self.page['id']) + '/photos', {'published': 'false'},
                               token=self.page['access_token'], image=raw)
        return {'id': identifier(str(result.get('id')))}

    def create_container(self, image, *, media_type, staged_photo):
        if media_type != 'STORIES' or self.page is None:
            raise ValueError('Use somente o formato Story na conta conferida.')
        photo = self._request('GET', identifier(staged_photo), {'fields': 'images'}, token=self.page['access_token'])
        candidates = []
        for item in photo.get('images', []):
            if not isinstance(item, dict) or not isinstance(item.get('source'), str):
                continue
            parsed = urllib.parse.urlsplit(item['source'])
            host = (parsed.hostname or '').lower()
            width, height = item.get('width'), item.get('height')
            if (parsed.scheme == 'https' and not parsed.username and not parsed.password and not parsed.fragment and
                    parsed.port in (None, 443) and host.endswith(('.fbcdn.net', '.fbsbx.com', '.facebook.com')) and
                    type(width) is int and type(height) is int and 320 <= width <= 1440 and height > 0 and
                    abs(width / height - 9 / 16) < .01):
                candidates.append(item)
        if not candidates:
            raise ValueError('A Meta não retornou uma imagem vertical compatível com o Story.')
        source = max(candidates, key=lambda x: x['width'])['source']
        result = self._request('POST', self.account_id + '/media', {'media_type': 'STORIES', 'image_url': source})
        return {'id': identifier(str(result.get('id')))}

    def container_status(self, container):
        result = self._request('GET', identifier(container), {'fields': 'status_code'})
        return result.get('status_code')

    def publish(self, container):
        result = self._request('POST', self.account_id + '/media_publish', {'creation_id': identifier(container)})
        return {'id': identifier(str(result.get('id')))}
