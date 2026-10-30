"""Aciona a fila e, quando ativa, a política de criação previamente autorizada."""
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import time
from urllib.parse import urlsplit

import meta
import scheduling
import feed_autonomy

PATH = '/internal/scheduler/tick'
KEY_FILE = 'scheduler-key.txt'
HASH_FILE = 'scheduler-key.sha256'
MIN_INTERVAL = 30
LEASE_SECONDS = 600


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS scheduler_http_runtime (
        id INTEGER PRIMARY KEY CHECK(id=1), last_started INTEGER NOT NULL,
        lease TEXT NOT NULL, lease_until INTEGER NOT NULL)''')


def run(connect, directory):
    now = int(time.time())
    lease = secrets.token_hex(16)
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM scheduler_http_runtime WHERE id=1').fetchone()
        if row and row['lease_until'] > now:
            return {'status': 'busy'}
        if row and now - row['last_started'] < MIN_INTERVAL:
            return {'status': 'throttled'}
        conn.execute('INSERT OR REPLACE INTO scheduler_http_runtime VALUES(1,?,?,?)',
                     (now, lease, now + LEASE_SECONDS))
    try:
        result = scheduling.tick(connect, directory, mode='http')
        # Publicação tem prioridade. A criação só usa chamadas ociosas e política ativa.
        if result.get('status') == 'idle':
            try:
                feed_autonomy.tick(connect, directory)
            except (ValueError, OSError, sqlite3.Error):
                # O estado privado da rotina registra a falha sem expor conteúdo.
                # Falha na criação não desliga o cron de publicações autorizadas.
                with connect() as conn:
                    conn.execute("UPDATE feed_auto_runtime SET state='error' WHERE id=1 AND lease_until<=?", (int(time.time()),))
        return result
    finally:
        with connect() as conn:
            conn.execute("UPDATE scheduler_http_runtime SET lease='',lease_until=0 WHERE id=1 AND lease=?", (lease,))


def handle(handler, method, connect, directory):
    # Não aceitar credenciais em URL nem chamadas de páginas de navegador.
    if urlsplit(handler.path).query:
        return handler.send_json({'error': 'Use a URL sem parâmetros.'}, 400)
    if handler.headers.get('Origin') is not None:
        return handler.send_json({'error': 'Origem não permitida.'}, 403)
    try:
        digest = (directory / HASH_FILE).read_text().strip()
    except OSError:
        digest = ''
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        return handler.send_json({'error': 'Acionamento externo não configurado.'}, 503)
    authorization = handler.headers.get('Authorization', '')
    match = re.fullmatch(r'Bearer ([A-Za-z0-9_-]{32,256})', authorization, re.IGNORECASE)
    if not match or not hmac.compare_digest(hashlib.sha256(match[1].encode()).hexdigest(), digest):
        return handler.send_json({'error': 'Credencial inválida.'}, 401)
    if method != 'POST':
        return handler.send_json({'error': 'Use POST sem corpo.'}, 405)
    if handler.headers.get('Content-Length', '0') not in ('', '0') or handler.headers.get('Transfer-Encoding'):
        return handler.send_json({'error': 'Envie a requisição sem corpo.'}, 400)
    try:
        # Exigir a mesma configuração HTTPS e Meta usada pelo executor em console.
        origin = urlsplit(meta.callback_url())
        if handler.headers.get('Host', '') != origin.netloc:
            return handler.send_json({'error': 'Endereço não permitido.'}, 403)
        meta.config(directory)
        result = run(connect, directory)
    except (OSError, ValueError, sqlite3.Error):
        return handler.send_json({'error': 'Executor indisponível. Confira a configuração e o estado da fila no sistema.'}, 503)
    # Não devolver legendas, contas, tokens, erros da Meta ou dados comerciais.
    return handler.send_json(result)


def _write_private(path, content):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.scheduler-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content + '\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def configure(directory, rotate=False):
    directory.mkdir(parents=True, exist_ok=True)
    if not rotate and any((directory / name).exists() for name in (KEY_FILE, HASH_FILE)):
        raise ValueError('A chave já existe. Use configure --rotate somente para substituí-la e atualizar o agendador externo.')
    key = secrets.token_urlsafe(32)
    _write_private(directory / KEY_FILE, key)
    _write_private(directory / HASH_FILE, hashlib.sha256(key.encode()).hexdigest())


def main():
    import argparse
    import app
    parser = argparse.ArgumentParser(description='Chave exclusiva para acionar a fila por HTTP')
    parser.add_argument('command', choices=['configure'])
    parser.add_argument('--rotate', action='store_true')
    args = parser.parse_args()
    try:
        configure(app.DB.parent, args.rotate)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
    print('Chave criada em:', app.DB.parent / KEY_FILE)
    print('Use seu conteúdo apenas no formulário seguro do agendador. Não envie a chave ao chat.')
    print('Nenhum agendamento foi criado ou publicado. Configure o acionamento externo e teste antes de encerrar o console.')


if __name__ == '__main__':
    main()
