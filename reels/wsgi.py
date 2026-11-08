"""WSGI wrapper for one isolated Reels trigger route."""
from __future__ import annotations

from http import HTTPStatus
import json
import os
from pathlib import Path

from . import http
from . import media
from .queue import Store, resolve_media_grant


def client_factory(account_id):
    from .meta_client import MetaClient
    directory = os.environ.get("ARTENOALTAR_REELS_META_DIR", "")
    origin = os.environ.get("ARTENOALTAR_ORIGIN", "")
    if not directory or not Path(directory).is_absolute() or not origin:
        raise ValueError("O diretório da autorização existente precisa ser configurado.")
    return MetaClient.from_directory(Path(directory), account_id, origin)


def prepare_reel(store, *, now=None):
    from .automation import run
    directory = os.environ.get("ARTENOALTAR_REELS_DRIVE_DIR", "")
    if not directory or not Path(directory).is_absolute():
        raise ValueError("A origem de vídeos do Drive precisa ser configurada.")
    schedule_directory = os.environ.get("ARTENOALTAR_REELS_META_DIR", "")
    if not schedule_directory or not Path(schedule_directory).is_absolute():
        schedule_directory = None
    return run(store, Path(directory), schedule_directory=schedule_directory, now=now)


def application(environ, start_response):
    if str(environ.get("PATH_INFO", "")).startswith(media.PATH_PREFIX):
        value = os.environ.get("ARTENOALTAR_REELS_DIR", "")
        directory = Path(value)
        if not value or not directory.is_absolute() or directory.is_symlink():
            return media.serve(environ, start_response, Path("/reels-unconfigured"),
                               lambda token: None)
        store = Store(directory)
        return media.serve(environ, start_response, directory,
                           lambda token: resolve_media_grant(store, token))
    if environ.get("PATH_INFO") != http.PATH:
        from carousel_posts.wsgi import application as existing
        return existing(environ, start_response)
    directory = os.environ.get("ARTENOALTAR_REELS_DIR", "")
    if not directory or not Path(directory).is_absolute():
        status, result = 503, {"error": "Reels não configurados."}
    else:
        status, result = http.handle(environ, Path(directory), client_factory, prepare_reel)
    content = json.dumps(result, ensure_ascii=False).encode("utf-8")
    start_response(f"{status} {HTTPStatus(status).phrase}", [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(content))),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
        ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
    ])
    return [content]
