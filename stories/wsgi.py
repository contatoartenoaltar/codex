"""Entrada opcional: uma rota nova; as demais usam exatamente o WSGI atual.

Este arquivo não altera a configuração da hospedagem por conta própria.
"""
from http import HTTPStatus
import json
import os
from pathlib import Path

from . import http


def client_factory(account_id):
    from .meta_client import MetaClient
    directory = os.environ.get('ARTENOALTAR_STORIES_META_DIR', '')
    if not directory or not Path(directory).is_absolute():
        raise ValueError('O diretório da autorização existente precisa ser configurado.')
    return MetaClient.from_directory(directory, account_id)


def application(environ, start_response):
    if environ.get('PATH_INFO') != http.PATH:
        from wsgi import application as existing
        return existing(environ, start_response)
    directory = os.environ.get('ARTENOALTAR_STORIES_DIR', '')
    if not directory or not Path(directory).is_absolute():
        status, result = 503, {'error': 'Stories não configurados.'}
    else:
        status, result = http.handle(environ, Path(directory), client_factory)
    content = json.dumps(result, ensure_ascii=False).encode('utf-8')
    start_response(f'{status} {HTTPStatus(status).phrase}', [
        ('Content-Type', 'application/json; charset=utf-8'), ('Content-Length', str(len(content))),
        ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
        ('X-Frame-Options', 'DENY'), ('Referrer-Policy', 'no-referrer'),
        ('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")])
    return [content]
