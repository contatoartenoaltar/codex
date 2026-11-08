"""Private trigger for the isolated Reels queue.

This module owns its key, throttle and lease.  It does not share state with the
feed, Story or carousel executors.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .queue import Store, policy_status


PATH = "/internal/reels/tick"
KEY_FILE = "reels-trigger.key"
CONFIG_FILE = "reels-http.json"
MIN_INTERVAL = 30
LEASE_SECONDS = 600
ZONE = ZoneInfo("America/Sao_Paulo")


def tick(store, client, *, now=None):
    """Late-bound adapter keeps HTTP independent from queue implementation details."""
    from .queue import tick as process
    return process(store, client, now=now)


def origin_host(origin: str) -> str:
    if not isinstance(origin, str) or any(ord(char) <= 32 for char in origin):
        raise ValueError("Informe a origem HTTPS dos Reels.")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or
            parsed.fragment or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Use a origem HTTPS sem caminho, parâmetros ou credenciais.")
    return parsed.netloc.lower()


def configure(directory: Path, origin: str) -> None:
    """Create a private trigger without enabling the publishing policy."""
    origin_host(origin)
    store = Store(directory)
    store.initialize()
    paths = store.directory / KEY_FILE, store.directory / CONFIG_FILE
    if any(path.exists() or path.is_symlink() for path in paths):
        raise FileExistsError("O acionamento dos Reels já está configurado; nada foi substituído.")
    key = secrets.token_urlsafe(48)
    payloads = (
        (paths[0], key.encode()),
        (paths[1], json.dumps({"origin": origin,
                              "key_hash": hashlib.sha256(key.encode()).hexdigest()}).encode()),
    )
    created: list[Path] = []
    try:
        for path, content in payloads:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def _replace_private(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".reels-key-")
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)


def rotate(directory: Path) -> None:
    """Replace only the private trigger credential, preserving queue policy and origin."""
    directory = Path(directory)
    config = read_config(directory)
    key = secrets.token_urlsafe(48)
    _replace_private(directory / KEY_FILE, key.encode())
    _replace_private(directory / CONFIG_FILE, json.dumps({
        "origin": config["origin"],
        "key_hash": hashlib.sha256(key.encode()).hexdigest(),
    }).encode())


def read_config(directory: Path) -> dict:
    directory = Path(directory)
    path = directory / CONFIG_FILE
    if (directory.is_symlink() or path.is_symlink() or path.stat().st_mode & 0o077 or
            path.stat().st_size > 8192):
        raise ValueError("A configuração dos Reels precisa ser privada e local.")
    config = json.loads(path.read_text())
    origin_host(config["origin"])
    if not re.fullmatch(r"[a-f0-9]{64}", config["key_hash"]):
        raise ValueError("Chave de acionamento inválida.")
    return config


def _stamp(now=None) -> int:
    value = datetime.now(ZONE) if now is None else now
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Informe uma data com fuso horário.")
    return int(value.astimezone(ZONE).timestamp())


def run(store: Store, factory, preparer=None, *, now=None):
    current = _stamp(now)
    lease = secrets.token_hex(16)
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        policy = connection.execute("SELECT enabled,mode,account_id FROM policy WHERE id=1").fetchone()
        if policy is None or not policy["enabled"]:
            return {"status": "disabled"}
        if policy["mode"] != "live" or factory is None:
            return {"status": "unconfigured"}
        connection.execute("""CREATE TABLE IF NOT EXISTS reels_http_runtime(
            id INTEGER PRIMARY KEY CHECK(id=1), last_started INTEGER NOT NULL,
            lease TEXT NOT NULL, lease_until INTEGER NOT NULL)""")
        runtime = connection.execute("SELECT * FROM reels_http_runtime WHERE id=1").fetchone()
        if runtime and runtime["lease_until"] > current:
            return {"status": "busy"}
        if runtime and current - runtime["last_started"] < MIN_INTERVAL:
            return {"status": "throttled"}
        connection.execute("INSERT OR REPLACE INTO reels_http_runtime VALUES(1,?,?,?)",
                           (current, lease, current + LEASE_SECONDS))
    try:
        client = factory(policy["account_id"])
        result = tick(store, client, now=now)
        if result.get("status") == "idle" and preparer is not None:
            result = preparer(store, now=now)
        return result
    finally:
        with store.connect() as connection:
            connection.execute("""UPDATE reels_http_runtime SET lease='',lease_until=0
                WHERE id=1 AND lease=?""", (lease,))


def handle(environ, directory: Path, factory=None, preparer=None, *, now=None):
    if environ.get("QUERY_STRING"):
        return 400, {"error": "Use a URL sem parâmetros."}
    if "HTTP_ORIGIN" in environ:
        return 403, {"error": "Origem não permitida."}
    try:
        config = read_config(directory)
    except (OSError, ValueError, KeyError, TypeError):
        return 503, {"error": "Acionamento de Reels não configurado."}
    authorization = environ.get("HTTP_AUTHORIZATION", "")
    match = (re.fullmatch(r"Bearer ([A-Za-z0-9_-]{32,256})", authorization, re.IGNORECASE)
             if isinstance(authorization, str) else None)
    if (not match or not hmac.compare_digest(hashlib.sha256(match[1].encode()).hexdigest(),
                                              config["key_hash"])):
        return 401, {"error": "Credencial inválida."}
    if environ.get("REQUEST_METHOD") != "POST":
        return 405, {"error": "Use POST sem corpo."}
    if (environ.get("CONTENT_LENGTH", "") not in ("", "0") or
            environ.get("HTTP_TRANSFER_ENCODING") or environ.get("TRANSFER_ENCODING")):
        return 400, {"error": "Envie a requisição sem corpo."}
    if str(environ.get("HTTP_HOST", "")).lower() != origin_host(config["origin"]):
        return 403, {"error": "Endereço não permitido."}
    try:
        result = run(Store(directory), factory, preparer, now=now)
        return 200, {"status": result["status"]}
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
        return 503, {"error": "O executor de Reels não concluiu o acionamento; confira seu estado."}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Configure or inspect the isolated private Reels trigger.")
    commands = parser.add_subparsers(dest="command", required=True)
    configure_command = commands.add_parser(
        "configure", help="Create a private trigger without enabling publishing.")
    configure_command.add_argument("--directory", required=True, type=Path)
    configure_command.add_argument("--origin", required=True)
    status_command = commands.add_parser(
        "status", help="Validate trigger configuration without exposing its key.")
    status_command.add_argument("--directory", required=True, type=Path)
    rotate_command = commands.add_parser(
        "rotate", help="Replace an exposed trigger key without changing publishing policy.")
    rotate_command.add_argument("--directory", required=True, type=Path)
    arguments = parser.parse_args(argv)
    if arguments.command == "configure":
        configure(arguments.directory, arguments.origin)
        print("Private Reels trigger configured. Publishing remains disabled.")
        return
    if arguments.command == "rotate":
        rotate(arguments.directory)
        print("Private Reels trigger key rotated. Copy the new key into the existing job.")
        return
    config = read_config(arguments.directory)
    policy = policy_status(Store(arguments.directory))
    print(json.dumps({
        "configured": True,
        "origin": config["origin"],
        "publishing_enabled": policy["enabled"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
