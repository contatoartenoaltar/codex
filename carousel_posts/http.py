"""Endpoint privado usado pelo cron-job.org para os carrosséis."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
from urllib.parse import urlsplit

from .meta_client import CarouselMetaClient
from .queue import Store, ensure_horizon, tick

PATH = "/internal/carousels/tick"
KEY_FILE = "carousel-trigger.key"
CONFIG_FILE = "carousel-http.json"


def origin_host(origin: str) -> str:
    if not isinstance(origin, str) or any(ord(char) <= 32 for char in origin):
        raise ValueError("Informe a origem HTTPS.")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or
            parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("Use a origem HTTPS sem caminho ou parâmetros.")
    return parsed.netloc.lower()


def configure(directory, origin) -> None:
    origin_host(origin)
    store = Store(directory)
    store.initialize()
    key_path, config_path = store.directory / KEY_FILE, store.directory / CONFIG_FILE
    if any(path.exists() or path.is_symlink() for path in (key_path, config_path)):
        raise FileExistsError("O acionamento de carrosséis já está configurado.")
    key = secrets.token_urlsafe(48)
    config = {"origin": origin, "key_hash": hashlib.sha256(key.encode()).hexdigest()}
    for path, content in ((key_path, key.encode()), (config_path, json.dumps(config).encode())):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)


def read_config(directory) -> dict:
    directory = Path(directory)
    path = directory / CONFIG_FILE
    if (directory.is_symlink() or path.is_symlink() or path.stat().st_mode & 0o077 or
            path.stat().st_size > 8192):
        raise ValueError("A configuração de carrosséis precisa ser privada.")
    config = json.loads(path.read_text())
    origin_host(config["origin"])
    if not re.fullmatch(r"[a-f0-9]{64}", config["key_hash"]):
        raise ValueError("Chave inválida.")
    return config


def handle(environ, directory, meta_directory, *, now=None):
    if environ.get("QUERY_STRING") or "HTTP_ORIGIN" in environ:
        return 400, {"error": "Use a URL privada sem parâmetros ou origem."}
    try:
        config = read_config(directory)
    except (OSError, ValueError, KeyError, TypeError):
        return 503, {"error": "Acionamento de carrosséis não configurado."}
    auth = environ.get("HTTP_AUTHORIZATION", "")
    match = re.fullmatch(r"Bearer ([A-Za-z0-9_-]{32,256})", auth, re.IGNORECASE) if isinstance(auth, str) else None
    if not match or not hmac.compare_digest(hashlib.sha256(match[1].encode()).hexdigest(), config["key_hash"]):
        return 401, {"error": "Credencial inválida."}
    if environ.get("REQUEST_METHOD") != "POST":
        return 405, {"error": "Use POST sem corpo."}
    if (environ.get("CONTENT_LENGTH", "") not in ("", "0") or environ.get("HTTP_TRANSFER_ENCODING") or
            str(environ.get("HTTP_HOST", "")).lower() != origin_host(config["origin"])):
        return 400, {"error": "Requisição inválida."}
    try:
        store = Store(directory)
        result = tick(store, lambda account_id: CarouselMetaClient.from_directory(meta_directory, account_id), now=now)
        if result["status"] == "idle":
            ensure_horizon(store, now=now)
        return 200, {"status": result["status"]}
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
        return 503, {"error": "O executor de carrosséis não concluiu o acionamento."}

