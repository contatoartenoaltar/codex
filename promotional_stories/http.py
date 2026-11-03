"""Acionamento privado exclusivo dos Stories promocionais."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from urllib.parse import urlsplit

from .queue import Store, tick, run_daily_step, local_now, stamp, LEASE


PATH = "/internal/promotional-stories/tick"
KEY_FILE = "promotional-stories-trigger.key"
CONFIG_FILE = "promotional-stories-http.json"
MIN_INTERVAL = 30


def origin_host(origin):
    if not isinstance(origin, str) or any(ord(c) <= 32 for c in origin):
        raise ValueError("Informe a origem HTTPS.")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or
            parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Use a origem HTTPS sem caminho, parâmetros ou credenciais.")
    return parsed.netloc.lower()


def configure(directory, origin):
    origin_host(origin)
    store = Store(directory)
    store.initialize()
    paths = store.directory / KEY_FILE, store.directory / CONFIG_FILE
    if any(path.exists() or path.is_symlink() for path in paths):
        raise FileExistsError("O acionamento promocional já está configurado.")
    key = secrets.token_urlsafe(48)
    config = {"origin": origin, "key_hash": hashlib.sha256(key.encode()).hexdigest()}
    created = []
    try:
        for path, content in ((paths[0], key.encode()), (paths[1], json.dumps(config).encode())):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def read_config(directory):
    directory = Path(directory)
    path = directory / CONFIG_FILE
    if directory.is_symlink() or path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_size > 8192:
        raise ValueError("A configuração promocional precisa ser privada e local.")
    config = json.loads(path.read_text())
    origin_host(config["origin"])
    if not re.fullmatch(r"[a-f0-9]{64}", config["key_hash"]):
        raise ValueError("Chave inválida.")
    return config


def run(store, factory, *, now=None):
    now = local_now(now)
    lease = secrets.token_hex(16)
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        policy = conn.execute("SELECT * FROM policy WHERE id=1").fetchone()
        if not policy["enabled"]:
            return {"status": "disabled"}
        if factory is None:
            return {"status": "unconfigured"}
        row = conn.execute("SELECT * FROM http_runtime WHERE id=1").fetchone()
        if row and row["lease_until"] > stamp(now):
            return {"status": "busy"}
        if row and stamp(now) - row["last_started"] < MIN_INTERVAL:
            return {"status": "throttled"}
        conn.execute("INSERT OR REPLACE INTO http_runtime VALUES(1,?,?,?)", (stamp(now), lease, stamp(now)+LEASE))
    try:
        result = tick(store, factory(policy["account_id"]), now=now)
        if result["status"] == "idle":
            daily = run_daily_step(store, now=now)
            if daily["status"] not in ("disabled", "idle"):
                return daily
        return result
    finally:
        with store.connect() as conn:
            conn.execute("UPDATE http_runtime SET lease='',lease_until=0 WHERE id=1 AND lease=?", (lease,))


def handle(environ, directory, factory=None, *, now=None):
    if environ.get("QUERY_STRING"):
        return 400, {"error": "Use a URL sem parâmetros."}
    if "HTTP_ORIGIN" in environ:
        return 403, {"error": "Origem não permitida."}
    try:
        config = read_config(directory)
    except (OSError, ValueError, KeyError, TypeError):
        return 503, {"error": "Acionamento promocional não configurado."}
    auth = environ.get("HTTP_AUTHORIZATION", "")
    match = re.fullmatch(r"Bearer ([A-Za-z0-9_-]{32,256})", auth, re.IGNORECASE) if isinstance(auth, str) else None
    if not match or not hmac.compare_digest(hashlib.sha256(match[1].encode()).hexdigest(), config["key_hash"]):
        return 401, {"error": "Credencial inválida."}
    if environ.get("REQUEST_METHOD") != "POST":
        return 405, {"error": "Use POST sem corpo."}
    if (environ.get("CONTENT_LENGTH", "") not in ("", "0") or
            environ.get("HTTP_TRANSFER_ENCODING") or environ.get("TRANSFER_ENCODING")):
        return 400, {"error": "Envie a requisição sem corpo."}
    if str(environ.get("HTTP_HOST", "")).lower() != origin_host(config["origin"]):
        return 403, {"error": "Endereço não permitido."}
    try:
        result = run(Store(directory), factory, now=now)
        return 200, {"status": result["status"]}
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
        return 503, {"error": "O executor promocional não concluiu o acionamento; confira seu estado."}


def main():
    parser = argparse.ArgumentParser(
        description="Criar acionamento privado promocional, sem ativar envios.")
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--origin", required=True)
    args = parser.parse_args()
    configure(args.directory, args.origin)
    print("Acionamento promocional configurado. A chave ficou no arquivo privado; envios não foram ativados.")


if __name__ == "__main__":
    main()
