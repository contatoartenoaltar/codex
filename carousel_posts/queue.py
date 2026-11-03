"""Fila isolada para criação e publicação automática dos carrosséis."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
from zoneinfo import ZoneInfo

from . import composer

ZONE = ZoneInfo("America/Sao_Paulo")
APPLICATION_ID = 0x41414352
PUBLICATION_TIME = time(12, 0)
WEEKDAYS = (0, 2, 4)  # segunda, quarta e sexta
HORIZON = 3
MAX_LATENESS = 1800

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS policy(id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL, mode TEXT NOT NULL, account_id TEXT NOT NULL, rules_hash TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS carousels(
        id TEXT PRIMARY KEY, faq_id TEXT NOT NULL, cycle INTEGER NOT NULL,
        due_at INTEGER NOT NULL UNIQUE, state TEXT NOT NULL, caption TEXT NOT NULL,
        manifest TEXT NOT NULL, parent_container TEXT NOT NULL DEFAULT '',
        remote_id TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL, UNIQUE(cycle,faq_id))""",
    """CREATE TABLE IF NOT EXISTS slides(
        carousel_id TEXT NOT NULL REFERENCES carousels(id), position INTEGER NOT NULL,
        filename TEXT NOT NULL, image_hash TEXT NOT NULL,
        staged_photo TEXT NOT NULL DEFAULT '', child_container TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(carousel_id,position))""",
    """CREATE TABLE IF NOT EXISTS attempts(
        id TEXT PRIMARY KEY, carousel_id TEXT NOT NULL REFERENCES carousels(id),
        phase TEXT NOT NULL, created_at INTEGER NOT NULL, outcome TEXT NOT NULL DEFAULT 'pending')""",
)


def local_now(now=None) -> datetime:
    value = datetime.now(ZONE) if now is None else now
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Informe uma data com fuso horário.")
    return value.astimezone(ZONE)


def _stamp(value: datetime) -> int:
    return int(value.timestamp())


def _next_dates(now: datetime, count: int = HORIZON) -> list[datetime]:
    result = []
    day = now.date()
    while len(result) < count:
        due = datetime.combine(day, PUBLICATION_TIME, ZONE)
        if day.weekday() in WEEKDAYS and due > now + timedelta(minutes=10):
            result.append(due)
        day += timedelta(days=1)
    return result


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "carousel-queue.sqlite3"
        self.media = self.directory / "media"
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValueError("Não use links simbólicos no armazenamento de carrosséis.")

    def initialize(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.media.mkdir(mode=0o700, exist_ok=True)
        if not self.path.exists():
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("BEGIN IMMEDIATE")
            identity = connection.execute("PRAGMA application_id").fetchone()[0]
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if identity not in (0, APPLICATION_ID) or (identity == 0 and tables):
                raise ValueError("Recusado: banco existente não pertence aos carrosséis.")
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            for statement in SCHEMA:
                connection.execute(statement)
            connection.execute("INSERT OR IGNORE INTO policy VALUES(1,0,'live','',?)", (composer.rules_hash(),))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def connect(self):
        if not self.path.is_file() or self.path.is_symlink():
            raise ValueError("Inicialize o armazenamento de carrosséis.")
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise ValueError("Este banco não pertence aos carrosséis.")
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def agenda(self) -> list[dict]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM carousels ORDER BY due_at")]


def _caption(record: dict) -> str:
    return (f'{record["question"]}\n\n{record["answer"]}\n\n'
            "Conheça nossos modelos e fale com a Arte no Altar.\n"
            "artenoaltar.com.br | WhatsApp 35 9 8442-8442\n\n"
            "#ArteNoAltar #GraficaCrista #Igreja")


def _next_topic(connection) -> tuple[int, dict]:
    items = composer.catalog()
    row = connection.execute("SELECT COUNT(*) FROM carousels").fetchone()
    offset = row[0]
    return offset // len(items) + 1, items[offset % len(items)]


def _create(store: Store, connection, due: datetime, now: datetime) -> str:
    cycle, record = _next_topic(connection)
    ident = secrets.token_hex(16)
    target = store.media / ident
    if target.exists() or target.is_symlink():
        raise ValueError("Destino de mídia de carrossel já existe.")
    manifest = composer.save(record["id"], target)
    try:
        connection.execute(
            "INSERT INTO carousels(id,faq_id,cycle,due_at,state,caption,manifest,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (ident, record["id"], cycle, _stamp(due), "queued", _caption(record),
             json.dumps(manifest, ensure_ascii=False, sort_keys=True), _stamp(now)))
        for slide in manifest["slides"]:
            path = target / slide["filename"]
            connection.execute(
                "INSERT INTO slides(carousel_id,position,filename,image_hash) VALUES(?,?,?,?)",
                (ident, slide["position"], str(path.relative_to(store.directory)), slide["sha256"]))
    except BaseException:
        for path in target.glob("*"):
            path.unlink()
        target.rmdir()
        raise
    return ident


def enable_automatic(store: Store, account_id: str, *, confirmed: bool = False) -> None:
    if not confirmed:
        raise ValueError("Confirme a ativação automática dos carrosséis.")
    if not isinstance(account_id, str) or not account_id.isdigit():
        raise ValueError("Conta Meta inválida.")
    with store.connect() as connection:
        connection.execute("UPDATE policy SET enabled=1,account_id=?,rules_hash=? WHERE id=1",
                           (account_id, composer.rules_hash()))


def disable(store: Store) -> None:
    with store.connect() as connection:
        connection.execute("UPDATE policy SET enabled=0 WHERE id=1")


def ensure_horizon(store: Store, *, now=None) -> dict:
    """Mantém as próximas três datas de carrossel prontas, sem aprovação por item."""
    now = local_now(now)
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        policy = connection.execute("SELECT * FROM policy WHERE id=1").fetchone()
        if not policy["enabled"]:
            return {"status": "disabled"}
        if policy["rules_hash"] != composer.rules_hash():
            connection.execute("UPDATE policy SET enabled=0 WHERE id=1")
            return {"status": "review"}
        existing = {row[0] for row in connection.execute(
            "SELECT due_at FROM carousels WHERE state IN ('queued','staging','publishing') AND due_at>?",
            (_stamp(now),))}
        created = []
        for due in _next_dates(now, HORIZON):
            if _stamp(due) not in existing:
                created.append(_create(store, connection, due, now))
        return {"status": "queued" if created else "idle", "created": created}


def cancel(store: Store, carousel_id: str) -> dict:
    with store.connect() as connection:
        row = connection.execute("SELECT state FROM carousels WHERE id=?", (carousel_id,)).fetchone()
        if row is None:
            raise ValueError("Carrossel não encontrado.")
        if row["state"] not in ("queued", "failed"):
            raise ValueError("Este carrossel não pode mais ser cancelado.")
        connection.execute("UPDATE carousels SET state='cancelled' WHERE id=?", (carousel_id,))
    return {"id": carousel_id, "state": "cancelled"}


def verify_files(store: Store, carousel_id: str) -> list[Path]:
    with store.connect() as connection:
        rows = connection.execute(
            "SELECT position,filename,image_hash FROM slides WHERE carousel_id=? ORDER BY position",
            (carousel_id,)).fetchall()
    if [row["position"] for row in rows] != [1, 2, 3]:
        raise ValueError("O carrossel precisa conter exatamente três slides ordenados.")
    result = []
    for row in rows:
        path = store.directory / row["filename"]
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["image_hash"]:
            raise ValueError("Arquivo de carrossel ausente ou alterado.")
        result.append(path)
    return result


def _review(store: Store, ident: str, message: str) -> None:
    with store.connect() as connection:
        connection.execute("UPDATE carousels SET state='review',error=? WHERE id=?", (message, ident))


def tick(store: Store, factory, *, now=None) -> dict:
    """Executa no máximo uma transição remota confirmada por chamada do cron."""
    now = local_now(now)
    with store.connect() as connection:
        policy = connection.execute("SELECT * FROM policy WHERE id=1").fetchone()
        if not policy["enabled"]:
            return {"status": "disabled"}
        row = connection.execute(
            "SELECT * FROM carousels WHERE state IN ('queued','staging','processing','publishing') "
            "AND due_at<=? ORDER BY due_at LIMIT 1", (_stamp(now),)).fetchone()
    if row is None:
        result = ensure_horizon(store, now=now)
        return {"status": "idle"} if result["status"] in ("idle", "queued") else result
    carousel = dict(row)
    ident = carousel["id"]
    if _stamp(now) - carousel["due_at"] > MAX_LATENESS and carousel["state"] == "queued":
        _review(store, ident, "Horário excedido; confira a agenda antes de publicar.")
        return {"status": "review", "id": ident}
    try:
        client = factory(policy["account_id"])
        client.verify_account(policy["account_id"])
        files = verify_files(store, ident)
        with store.connect() as connection:
            slides = [dict(slide) for slide in connection.execute(
                "SELECT * FROM slides WHERE carousel_id=? ORDER BY position", (ident,))]

        unstaged = next((slide for slide in slides if not slide["staged_photo"]), None)
        if unstaged:
            staged = client.stage_image(store.directory / unstaged["filename"])
            with store.connect() as connection:
                connection.execute("UPDATE slides SET staged_photo=? WHERE carousel_id=? AND position=?",
                                   (staged["id"], ident, unstaged["position"]))
                connection.execute("UPDATE carousels SET state='staging',error='' WHERE id=?", (ident,))
            return {"status": "staging", "id": ident, "position": unstaged["position"]}

        missing_child = next((slide for slide in slides if not slide["child_container"]), None)
        if missing_child:
            child = client.create_carousel_child(
                store.directory / missing_child["filename"], staged_photo=missing_child["staged_photo"])
            with store.connect() as connection:
                connection.execute("UPDATE slides SET child_container=? WHERE carousel_id=? AND position=?",
                                   (child["id"], ident, missing_child["position"]))
                connection.execute("UPDATE carousels SET state='processing',error='' WHERE id=?", (ident,))
            return {"status": "processing", "id": ident, "position": missing_child["position"]}

        for slide in slides:
            status = client.container_status(slide["child_container"])
            if status == "IN_PROGRESS":
                return {"status": "processing", "id": ident}
            if status != "FINISHED":
                raise ValueError("A Meta não confirmou um dos slides do carrossel.")

        if not carousel["parent_container"]:
            parent = client.create_carousel([slide["child_container"] for slide in slides], carousel["caption"])
            with store.connect() as connection:
                connection.execute("UPDATE carousels SET parent_container=?,state='publishing',error='' WHERE id=?",
                                   (parent["id"], ident))
            return {"status": "publishing", "id": ident}

        status = client.container_status(carousel["parent_container"])
        if status == "IN_PROGRESS":
            return {"status": "publishing", "id": ident}
        if status != "FINISHED":
            raise ValueError("A Meta não confirmou o carrossel final.")
        published = client.publish(carousel["parent_container"])
        with store.connect() as connection:
            connection.execute("UPDATE carousels SET state='published',remote_id=?,error='' WHERE id=?",
                               (published["id"], ident))
        ensure_horizon(store, now=now)
        return {"status": "published", "id": ident, "remote_id": published["id"]}
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError):
        _review(store, ident, "A Meta não confirmou a etapa; revise antes de qualquer repetição.")
        return {"status": "review", "id": ident}
