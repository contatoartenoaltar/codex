"""Acesso individual com senha scrypt e sessões persistidas por hash."""
import hashlib
import hmac
import secrets
import time
from http.cookies import SimpleCookie, CookieError

SESSION_SECONDS = 12 * 60 * 60


def initialize(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS owner (id INTEGER PRIMARY KEY CHECK(id=1), salt TEXT NOT NULL, password_hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS login_attempts (at INTEGER NOT NULL);
    ''')


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def set_password(conn, password):
    if len(password) < 12 or len(password) > 256:
        raise ValueError('Use uma senha entre 12 e 256 caracteres.')
    salt = secrets.token_hex(16)
    digest = password_hash(password, salt)
    conn.execute('INSERT OR REPLACE INTO owner VALUES(1,?,?)', (salt, digest))
    conn.execute('DELETE FROM sessions')
    conn.execute('DELETE FROM login_attempts')


def configured(conn):
    return conn.execute('SELECT 1 FROM owner WHERE id=1').fetchone() is not None


def login(conn, password):
    now = int(time.time())
    # BEGIN IMMEDIATE serializa a contagem entre processos do servidor.
    conn.execute('BEGIN IMMEDIATE')
    conn.execute('DELETE FROM login_attempts WHERE at<?', (now - 600,))
    if conn.execute('SELECT COUNT(*) FROM login_attempts').fetchone()[0] >= 10:
        return None, 'Muitas tentativas. Aguarde 10 minutos.', 429
    owner = conn.execute('SELECT salt,password_hash FROM owner WHERE id=1').fetchone()
    if not owner:
        return None, 'O acesso ainda precisa ser configurado pelo responsável no servidor.', 503
    if not isinstance(password, str) or len(password) > 256:
        password = ''
    if not hmac.compare_digest(password_hash(password, owner[0]), owner[1]):
        conn.execute('INSERT INTO login_attempts VALUES(?)', (now,))
        return None, 'Senha incorreta.', 401
    conn.execute('DELETE FROM login_attempts')
    conn.execute('DELETE FROM sessions WHERE expires<=?', (now,))
    token = secrets.token_urlsafe(32)
    conn.execute('INSERT INTO sessions VALUES(?,?)', (hashlib.sha256(token.encode()).hexdigest(), now + SESSION_SECONDS))
    return token, None, 200


def token_hash(header):
    try:
        cookie = SimpleCookie()
        cookie.load(header or '')
        value = cookie.get('arte_session')
        return hashlib.sha256(value.value.encode()).hexdigest() if value else ''
    except CookieError:
        return ''


def authenticated(conn, header):
    return conn.execute('SELECT 1 FROM sessions WHERE token_hash=? AND expires>?', (token_hash(header), int(time.time()))).fetchone() is not None
