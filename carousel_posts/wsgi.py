"""Aplicação WSGI mínima do acionamento privado de carrosséis."""
from __future__ import annotations

import json
import os

from .http import PATH, handle


def application(environ, start_response):
    if environ.get("PATH_INFO") != PATH:
        from promotional_stories.wsgi import application as existing
        return existing(environ, start_response)
    directory = os.environ.get("ARTENOALTAR_CAROUSELS_DIR", "")
    meta_directory = os.environ.get("ARTENOALTAR_CAROUSELS_META_DIR", "")
    if not directory or not meta_directory:
        status, payload = 503, {"error": "Carrosséis não configurados."}
    else:
        status, payload = handle(environ, directory, meta_directory)
    raw = json.dumps(payload, ensure_ascii=False).encode()
    start_response(f"{status} {'OK' if status == 200 else 'Error'}", [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(raw))),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
    ])
    return [raw]
