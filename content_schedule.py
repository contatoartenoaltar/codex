"""Agenda visual somente leitura para conteúdos automáticos já enfileirados."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import time

from stories.queue import APPLICATION_ID as VERSE_APPLICATION_ID
from promotional_stories.queue import APPLICATION_ID as PROMOTIONAL_APPLICATION_ID
from carousel_posts.queue import APPLICATION_ID as CAROUSEL_APPLICATION_ID
from carousel_posts.composer import item as carousel_item


ACTIVE_STATES = ("queued", "staged", "processing", "sending")
SOURCES = {
    "verse": {
        "environment": "ARTENOALTAR_STORIES_DIR",
        "database": "story-queue.sqlite3",
        "application_id": VERSE_APPLICATION_ID,
        "source": "Versículo diário",
    },
    "promotional": {
        "environment": "ARTENOALTAR_PROMOTIONAL_STORIES_DIR",
        "database": "promotional-story-queue.sqlite3",
        "application_id": PROMOTIONAL_APPLICATION_ID,
        "source": "Story promocional",
    },
    "carousel": {
        "environment": "ARTENOALTAR_CAROUSELS_DIR",
        "database": "carousel-queue.sqlite3",
        "application_id": CAROUSEL_APPLICATION_ID,
        "source": "Carrossel automático",
    },
}
NAME = re.compile(r"[a-f0-9]{32}\.jpg")
CAROUSEL_NAME = re.compile(r"([a-f0-9]{32})-0([1-3])\.jpg")


def _directory(kind):
    config = SOURCES.get(kind)
    if config is None:
        raise ValueError("Origem de conteúdo inválida.")
    value = os.environ.get(config["environment"], "")
    directory = Path(value)
    database = directory / config["database"]
    media = directory / "media"
    if (not value or not directory.is_absolute() or directory.is_symlink() or
            database.is_symlink() or media.is_symlink() or not database.is_file()):
        raise ValueError("Agenda automática indisponível.")
    return config, directory, database, media


def _connect(kind):
    config, directory, database, media = _directory(kind)
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    if connection.execute("PRAGMA application_id").fetchone()[0] != config["application_id"]:
        connection.close()
        raise ValueError("Agenda automática inválida.")
    return config, directory, media, connection


def _title(kind, row, media):
    if kind == "verse":
        try:
            verse = json.loads(row["verse_json"])
            reference = verse.get("reference")
            if isinstance(reference, str) and 0 < len(reference) <= 80:
                return f"Versículo · {reference}"
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        return "Versículo do dia"
    manifest = media / Path(row["filename"]).with_suffix(".json")
    try:
        if manifest.is_symlink() or manifest.stat().st_size > 65536:
            raise ValueError
        title = json.loads(manifest.read_text(encoding="utf-8")).get("title")
        if isinstance(title, str) and 0 < len(title) <= 160:
            return title
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        pass
    model = row["model_name"]
    return model if isinstance(model, str) and 0 < len(model) <= 160 else "Story promocional"


def agenda(*, now=None):
    """Retorna apenas itens ativos e imagens que pertencem às filas verificadas."""
    cutoff = int(time.time() if now is None else now) - 1800
    items = []
    for kind in SOURCES:
        try:
            config, directory, media, connection = _connect(kind)
            try:
                if kind == "carousel":
                    rows = connection.execute(
                        "SELECT c.id,c.faq_id,c.due_at,c.state,s.filename "
                        "FROM carousels c JOIN slides s ON s.carousel_id=c.id AND s.position=1 "
                        "WHERE c.state IN ('queued','staging','processing','publishing') "
                        "AND c.due_at>=? ORDER BY c.due_at LIMIT 60", (cutoff,)).fetchall()
                    for row in rows:
                        try:
                            product = carousel_item(row["faq_id"])["question"]
                        except (ValueError, KeyError, TypeError):
                            product = "Carrossel de perguntas e respostas"
                        slides = connection.execute(
                            "SELECT position,filename FROM slides WHERE carousel_id=? ORDER BY position",
                            (row["id"],)).fetchall()
                        if [slide["position"] for slide in slides] != [1, 2, 3]:
                            continue
                        images = [directory / slide["filename"] for slide in slides]
                        if any(image.parent != media / row["id"] or image.is_symlink() or
                               not image.is_file() or image.stat().st_size > 8 * 1024 * 1024
                               for image in images):
                            continue
                        urls = [f"/api/content-media/carousel/{row['id']}-0{position}.jpg"
                                for position in (1, 2, 3)]
                        items.append({
                            "id": f"carousel-{row['id']}", "kind": "carousel",
                            "product": product, "channel": "Instagram Carrossel",
                            "source": config["source"],
                            "image_url": urls[0], "image_urls": urls,
                            "due_at": row["due_at"], "state": row["state"],
                        })
                    continue
                columns = ("id,due_at,verse_json,filename,state" if kind == "verse" else
                           "id,due_at,model_name,filename,state")
                placeholders = ",".join("?" for _ in ACTIVE_STATES)
                rows = connection.execute(
                    f"SELECT {columns} FROM slots WHERE state IN ({placeholders}) "
                    "AND due_at>=? ORDER BY due_at LIMIT 60", (*ACTIVE_STATES, cutoff)).fetchall()
                for row in rows:
                    name = row["filename"]
                    image = media / name
                    if (not isinstance(name, str) or not NAME.fullmatch(name) or image.is_symlink() or
                            not image.is_file() or image.stat().st_size > 8 * 1024 * 1024):
                        continue
                    items.append({
                        "id": f"{kind}-{row['id']}", "kind": kind,
                        "product": _title(kind, row, media), "channel": "Instagram Story",
                        "source": config["source"], "image_url": f"/api/content-media/{kind}/{name}",
                        "due_at": row["due_at"], "state": row["state"],
                    })
            finally:
                connection.close()
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
            continue
    return sorted(items, key=lambda item: (item["due_at"], item["id"]))[:50]


def image(kind, name):
    """Lê uma miniatura somente quando seu nome ainda pertence à fila informada."""
    if kind == "carousel":
        match = CAROUSEL_NAME.fullmatch(name) if isinstance(name, str) else None
        if not match:
            raise ValueError("Miniatura inválida.")
        carousel_id, position = match.group(1), int(match.group(2))
        _, directory, _, connection = _connect(kind)
        try:
            row = connection.execute(
                "SELECT filename FROM slides WHERE carousel_id=? AND position=?",
                (carousel_id, position)).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ValueError("Miniatura não encontrada.")
        path = directory / row["filename"]
        expected_parent = directory / "media" / carousel_id
        if (path.parent != expected_parent or path.is_symlink() or not path.is_file() or
                path.stat().st_size > 8 * 1024 * 1024):
            raise ValueError("Miniatura não encontrada.")
        payload = path.read_bytes()
        if not (payload.startswith(b"\xff\xd8") and payload.endswith(b"\xff\xd9")):
            raise ValueError("Miniatura inválida.")
        return payload
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("Miniatura inválida.")
    _, _, media, connection = _connect(kind)
    try:
        if connection.execute("SELECT 1 FROM slots WHERE filename=?", (name,)).fetchone() is None:
            raise ValueError("Miniatura não encontrada.")
    finally:
        connection.close()
    path = media / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Miniatura não encontrada.")
    payload = path.read_bytes()
    if not (payload.startswith(b"\xff\xd8") and payload.endswith(b"\xff\xd9")):
        raise ValueError("Miniatura inválida.")
    return payload


def cancel(item_id, expected_due_at, *, confirmed=False):
    """Cancela atomicamente um Story que ainda não começou a ser processado."""
    if confirmed is not True or type(expected_due_at) is not int or not isinstance(item_id, str):
        raise ValueError("Confirme o agendamento exibido antes de cancelar.")
    kind, separator, slot_id = item_id.partition("-")
    if not separator or kind not in SOURCES or not re.fullmatch(r"[a-f0-9]{32}", slot_id):
        raise ValueError("Agendamento automático inválido.")
    config, _, database, _ = _directory(kind)
    connection = sqlite3.connect(database, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        if connection.execute("PRAGMA application_id").fetchone()[0] != config["application_id"]:
            raise ValueError("Agenda automática inválida.")
        connection.execute("BEGIN IMMEDIATE")
        table = "carousels" if kind == "carousel" else "slots"
        row = connection.execute(
            f"SELECT due_at,state FROM {table} WHERE id=?", (slot_id,)).fetchone()
        if row is None or row["due_at"] != expected_due_at:
            raise ValueError("O agendamento mudou. Atualize a página antes de cancelar.")
        if row["state"] != "queued":
            raise ValueError("O envio já começou e não pode mais ser cancelado por esta tela.")
        changed = connection.execute(
            f"UPDATE {table} SET state='cancelled',error='Cancelado pelo Estúdio de conteúdo.' "
            "WHERE id=? AND due_at=? AND state='queued'", (slot_id, expected_due_at))
        if changed.rowcount != 1:
            raise ValueError("O envio começou antes do cancelamento. Atualize a página.")
        if kind != "carousel":
            connection.execute(
                "INSERT INTO policy_events(action,account_id,created_at) "
                "SELECT ?,account_id,? FROM policy WHERE id=1",
                ("cancel_slot:" + slot_id, int(time.time())))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {"id": item_id, "cancelled": True}
