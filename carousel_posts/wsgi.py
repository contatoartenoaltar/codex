"""Aplicação WSGI mínima do acionamento privado de carrosséis."""
from __future__ import annotations

import json
import os

from .http import PATH, handle


def application(environ, start_response):
    if environ.get("PATH_INFO") != PATH:
        status, payload = 404, {"error": "Rota não encontrada."}
    else:
        status, payload = handle(
            environ,
            os.environ["ARTENOALTAR_CAROUSELS_DIR"],
            os.environ["ARTENOALTAR_CAROUSELS_META_DIR"],
        )
    raw = json.dumps(payload, ensure_ascii=False).encode()
    start_response(f"{status} {'OK' if status == 200 else 'Error'}", [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(raw))),
        ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
    ])
    return [raw]
