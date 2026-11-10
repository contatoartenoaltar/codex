"""Fila persistente e isolada para Reels já finalizados com áudio.

Este módulo não consulta o Drive nem chama a Meta. Ele recebe um MP4 local
temporário, valida seus metadados por uma função injetada e preserva os bytes
originais. A política nasce desativada e nenhuma publicação acontece sem uma
ativação explícita posterior.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import tempfile
import time as clock
from zoneinfo import ZoneInfo


ZONE = ZoneInfo("America/Sao_Paulo")
APPLICATION_ID = 0x4141524C
DATABASE = "reels-queue.sqlite3"
INITIAL_TIMES = ((11, 0), (17, 0), (21, 0))
MIN_NOTICE = 120
MAX_LATENESS = 30 * 60
MAX_PROCESSING_AGE = 6 * 60 * 60
LEASE_SECONDS = 10 * 60
# Nome curto mantido para os executores HTTP isolados.
LEASE = LEASE_SECONDS
MEDIA_GRANT_SECONDS = 6 * 60 * 60
MAX_VIDEO_BYTES = 1_000_000_000
MIN_DURATION = 3.0
MAX_DURATION = 90.0
CONFIGURE_CONFIRMATION = "CONFIGURE-REELS-DISABLED"
ENABLE_CONFIRMATION = "ENABLE-ONE-REEL-PER-DAY"
PUBLISH_TEST_CONFIRMATION = "PUBLISH-QUEUED-REEL-NOW"


SCHEMA = (
    """CREATE TABLE IF NOT EXISTS policy(
        id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL,
        mode TEXT NOT NULL, account_id TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS reels(
        id TEXT PRIMARY KEY, source_id TEXT NOT NULL UNIQUE,
        source_name TEXT NOT NULL, source_md5 TEXT NOT NULL,
        source_size INTEGER NOT NULL, filename TEXT NOT NULL UNIQUE,
        sha256 TEXT NOT NULL, duration REAL NOT NULL, width INTEGER NOT NULL,
        height INTEGER NOT NULL, fps REAL NOT NULL, caption TEXT NOT NULL DEFAULT '',
        publication_day TEXT UNIQUE, due_at INTEGER UNIQUE,
        state TEXT NOT NULL, container TEXT NOT NULL DEFAULT '',
        remote_id TEXT NOT NULL DEFAULT '', claim TEXT NOT NULL DEFAULT '',
        claimed_at INTEGER, error TEXT NOT NULL DEFAULT '',
        imported_at INTEGER NOT NULL, published_at INTEGER)""",
    """CREATE TABLE IF NOT EXISTS attempts(
        id TEXT PRIMARY KEY, reel_id TEXT NOT NULL REFERENCES reels(id),
        phase TEXT NOT NULL, created_at INTEGER NOT NULL,
        outcome TEXT NOT NULL DEFAULT 'pending')""",
    """CREATE TABLE IF NOT EXISTS media_grants(
        token_hash TEXT PRIMARY KEY, reel_id TEXT NOT NULL REFERENCES reels(id),
        expires_at INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)""",
    "CREATE INDEX IF NOT EXISTS reels_due ON reels(state,due_at)",
    """CREATE TABLE IF NOT EXISTS policy_events(
        id INTEGER PRIMARY KEY, action TEXT NOT NULL,
        account_id TEXT NOT NULL, created_at INTEGER NOT NULL)""",
)


class ReelError(ValueError):
    """Entrada recusada sem revelar detalhes internos do provedor."""


def local_now(value=None):
    current = datetime.now(ZONE) if value is None else value
    if current.tzinfo is None or current.utcoffset() is None:
        raise ReelError("Informe data e hora com fuso horário.")
    return current.astimezone(ZONE)


def stamp(value):
    return int(local_now(value).timestamp())


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / DATABASE
        self.media = self.directory / "media"
        if self.directory.is_symlink() or self.path.is_symlink() or self.media.is_symlink():
            raise ReelError("O armazenamento de Reels não aceita links simbólicos.")

    def initialize(self):
        if self.directory.is_symlink() or self.path.is_symlink() or self.media.is_symlink():
            raise ReelError("O armazenamento de Reels não aceita links simbólicos.")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.media.mkdir(mode=0o700, exist_ok=True)
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("BEGIN IMMEDIATE")
            identity = connection.execute("PRAGMA application_id").fetchone()[0]
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if identity not in (0, APPLICATION_ID) or (identity == 0 and tables):
                raise ReelError("O banco existente não pertence à fila de Reels.")
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            for statement in SCHEMA:
                connection.execute(statement)
            connection.execute("INSERT OR IGNORE INTO policy VALUES(1,0,'live','')")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def connect(self):
        if not self.path.is_file() or self.path.is_symlink():
            raise ReelError("Inicialize o armazenamento de Reels.")
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise ReelError("O banco existente não pertence à fila de Reels.")
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def agenda(self):
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM reels ORDER BY COALESCE(due_at,9223372036854775807),imported_at")]


def _source_item(item):
    if not isinstance(item, dict):
        raise ReelError("O arquivo do Drive não possui metadados válidos.")
    source_id = item.get("id")
    name = item.get("name")
    mime = item.get("mimeType")
    checksum = item.get("md5Checksum")
    size = item.get("size")
    if not isinstance(source_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,160}", source_id):
        raise ReelError("O vídeo não possui identificador válido no Drive.")
    if not isinstance(name, str) or not name.strip() or len(name) > 240:
        raise ReelError("O vídeo não possui nome válido.")
    video_mimes = {"video/mp4": ".mp4", "video/quicktime": ".mov"}
    if mime not in video_mimes:
        raise ReelError("A pasta de Reels aceita somente vídeos MP4 ou MOV.")
    suffix = Path(name).suffix.lower()
    if suffix != video_mimes[mime]:
        raise ReelError("A extensão do vídeo não corresponde ao formato informado pelo Drive.")
    if not isinstance(checksum, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", checksum):
        raise ReelError("O Drive não informou a integridade do vídeo.")
    try:
        size = int(size)
    except (TypeError, ValueError):
        raise ReelError("O Drive não informou o tamanho do vídeo.") from None
    if not 1 <= size <= MAX_VIDEO_BYTES:
        raise ReelError("O vídeo excede o limite seguro da fila.")
    return source_id, name.strip(), checksum.lower(), size, suffix


def _validate_media(metadata):
    if not isinstance(metadata, dict):
        raise ReelError("Não foi possível validar o vídeo.")
    try:
        duration = float(metadata["duration"])
        width = int(metadata["width"])
        height = int(metadata["height"])
        fps = float(metadata["fps"])
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ReelError("O vídeo não possui metadados compatíveis.") from None
    if metadata.get("video_codec") not in ("h264", "hevc") or metadata.get("audio_codec") != "aac":
        raise ReelError("Use MP4 ou MOV com vídeo H.264/HEVC e áudio AAC.")
    if metadata.get("has_audio") is not True:
        raise ReelError("O Reel precisa conter a música já incorporada.")
    if not MIN_DURATION <= duration <= MAX_DURATION:
        raise ReelError("O Reel precisa ter entre 3 e 90 segundos.")
    if not (540 <= width <= 2160 and 960 <= height <= 3840 and 0.54 <= width / height <= 0.59):
        raise ReelError(
            f"O vídeo foi identificado como {width} × {height}. "
            "Use vídeo vertical 9:16, preferencialmente 1080 × 1920.")
    if not 23 <= fps <= 60:
        raise ReelError("A taxa de quadros do vídeo não é compatível.")
    return duration, width, height, fps


def _file_hashes(path):
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            md5.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest()


def _flush_media(stream):
    stream.flush()
    try:
        os.fsync(stream.fileno())
    except OSError as error:
        if error.errno != errno.EBUSY:
            raise


def import_video(store, item, source, *, validator, now=None):
    """Importa uma cópia byte a byte; nunca altera áudio, imagem ou metadados."""
    source_id, source_name, expected_md5, expected_size, suffix = _source_item(item)
    source = Path(source)
    if source.is_symlink() or not source.is_file() or source.stat().st_size != expected_size:
        raise ReelError("O vídeo recebido não corresponde ao arquivo informado pelo Drive.")
    with source.open("rb") as stream:
        header = stream.read(12)
    if len(header) != 12 or header[4:8] != b"ftyp":
        raise ReelError("O arquivo recebido não é um MP4 válido.")
    actual_md5, sha256 = _file_hashes(source)
    if not secrets.compare_digest(actual_md5, expected_md5):
        raise ReelError("A integridade do vídeo recebido não foi confirmada.")
    duration, width, height, fps = _validate_media(validator(source))
    now_stamp = stamp(local_now(now))
    with store.connect() as connection:
        known = connection.execute(
            "SELECT * FROM reels WHERE source_id=?", (source_id,)).fetchone()
        if known:
            if known["source_md5"] != expected_md5 or known["source_size"] != expected_size:
                raise ReelError("Um arquivo já importado foi substituído no Drive.")
            return {"id": known["id"], "created": False}
    ident = secrets.token_hex(16)
    target = store.media / f"{ident}{suffix}"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=store.media, prefix=".reel-", suffix=suffix)
    try:
        with os.fdopen(descriptor, "wb") as destination, source.open("rb") as origin:
            shutil.copyfileobj(origin, destination, length=1024 * 1024)
            _flush_media(destination)
        temporary = Path(temporary_name)
        copied_md5, copied_sha256 = _file_hashes(temporary)
        if copied_md5 != expected_md5 or copied_sha256 != sha256:
            raise ReelError("A cópia local do vídeo não foi confirmada.")
        os.link(temporary, target)
        target.chmod(0o600)
        with store.connect() as connection:
            connection.execute("""INSERT INTO reels(
                id,source_id,source_name,source_md5,source_size,filename,sha256,
                duration,width,height,fps,state,imported_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ident, source_id, source_name, expected_md5, expected_size,
                 target.name, sha256, duration, width, height, fps, "ready", now_stamp))
        return {"id": ident, "created": True}
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def configure(store, account_id, *, confirmed=False):
    if confirmed is not True or not isinstance(account_id, str) or not account_id.isdecimal():
        raise ReelError("Confirme a conta Instagram antes de configurar Reels.")
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        policy = connection.execute("SELECT * FROM policy WHERE id=1").fetchone()
        if policy["enabled"] or (policy["account_id"] and policy["account_id"] != account_id):
            raise ReelError("A conta configurada para Reels não pode ser substituída.")
        connection.execute("UPDATE policy SET account_id=?,enabled=0 WHERE id=1", (account_id,))
        connection.execute("INSERT INTO policy_events(action,account_id,created_at) VALUES(?,?,?)",
                           ("configure_disabled", account_id, int(clock.time())))


def enable(store, account_id, *, confirmed=False):
    if confirmed is not True:
        raise ReelError("Confirme a ativação exclusiva da fila de Reels.")
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        policy = connection.execute("SELECT * FROM policy WHERE id=1").fetchone()
        if not policy["account_id"] or policy["account_id"] != account_id:
            raise ReelError("A conta Instagram não corresponde à configuração de Reels.")
        connection.execute("UPDATE policy SET enabled=1 WHERE id=1")
        connection.execute("INSERT INTO policy_events(action,account_id,created_at) VALUES(?,?,?)",
                           ("enable_live", account_id, int(clock.time())))


def pause(store):
    with store.connect() as connection:
        connection.execute("UPDATE policy SET enabled=0 WHERE id=1")
        connection.execute("INSERT INTO policy_events(action,account_id,created_at) "
                           "SELECT 'pause',account_id,? FROM policy WHERE id=1", (int(clock.time()),))


def policy_status(store):
    """Return a compact, read-only operational view of the isolated queue."""
    with store.connect() as connection:
        policy = connection.execute(
            "SELECT enabled,mode,account_id FROM policy WHERE id=1").fetchone()
        counts = {row["state"]: row["total"] for row in connection.execute(
            "SELECT state,COUNT(*) AS total FROM reels GROUP BY state")}
        next_reel = connection.execute("""SELECT id,source_name,due_at,state
            FROM reels WHERE state IN ('queued','processing')
            ORDER BY COALESCE(due_at,9223372036854775807) LIMIT 1""").fetchone()
        has_import_errors = connection.execute("""SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='reel_import_errors'""").fetchone()
        invalid_files = (connection.execute(
            "SELECT COUNT(*) FROM reel_import_errors").fetchone()[0]
            if has_import_errors else 0)
        invalid_details = []
        if has_import_errors:
            has_names = connection.execute("""SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='reel_import_error_names'""").fetchone()
            name_join = ("LEFT JOIN reel_import_error_names n ON n.source_id=e.source_id"
                         if has_names else "")
            name_column = "n.source_name" if has_names else "NULL"
            errors = connection.execute(f"""SELECT {name_column} AS source_name,e.error
                FROM reel_import_errors e {name_join}
                ORDER BY e.seen_at DESC,e.source_id LIMIT 20""").fetchall()
            for index, row in enumerate(errors, 1):
                invalid_details.append({
                    "file": row["source_name"] or f"Arquivo {index}",
                    "error": _public_import_error(row["error"]),
                })
    if policy is None:
        raise ReelError("The Reels policy is not initialized.")
    result = {
        "enabled": bool(policy["enabled"]),
        "mode": policy["mode"],
        "account_id": policy["account_id"],
        "counts": counts,
        "invalid_files": invalid_files,
        "invalid_file_details": invalid_details,
        "next": dict(next_reel) if next_reel is not None else None,
    }
    return result


def _public_import_error(value):
    """Keep actionable validation errors while hiding provider and filesystem details."""
    message = str(value).strip()
    safe_messages = {
        "O MP4 possui metadados incompletos.",
        "O MP4 possui uma estrutura inválida.",
        "O MP4 não informou as faixas esperadas.",
        "O MP4 não informou duração válida.",
        "O MP4 usa uma versão de metadados incompatível.",
        "O MP4 não informou o formato das faixas.",
        "O MP4 informou orientação inválida.",
        "O MP4 informou orientação incompleta.",
        "O MP4 não identificou uma faixa.",
        "O MP4 não informou as dimensões do vídeo.",
        "O MP4 não informou a taxa de quadros.",
        "O MP4 não informou metadados de reprodução.",
        "Não foi possível ler os metadados do MP4.",
        "O arquivo de Reel não é um MP4 local válido.",
        "Não foi possível validar o MP4 no servidor.",
        "O MP4 não informou faixas válidas.",
        "Use MP4 ou MOV com vídeo H.264/HEVC e áudio AAC.",
        "O Reel precisa conter a música já incorporada.",
        "O Reel precisa ter entre 3 e 90 segundos.",
        "A taxa de quadros do vídeo não é compatível.",
        "O Reel precisa conter uma faixa de vídeo e uma de áudio.",
        "O MP4 não passou pela validação técnica.",
        "O MP4 não informou dimensões ou duração válidas.",
        "O arquivo não possui um contêiner MP4 válido.",
        "O arquivo recebido não é um MP4 válido.",
        "O vídeo excede o limite seguro da fila.",
        "O vídeo não possui metadados compatíveis.",
        "O vídeo recebido não corresponde ao arquivo informado pelo Drive.",
        "A integridade do vídeo recebido não foi confirmada.",
        "A extensão do vídeo não corresponde ao formato informado pelo Drive.",
        "O Drive não informou a integridade do vídeo.",
        "O Drive não informou o tamanho do vídeo.",
        "A cópia local do vídeo não foi confirmada.",
        "O Drive não confirmou a retomada segura do vídeo.",
        "Acesso ao vídeo não confirmado. Confira o compartilhamento da pasta como Leitor.",
        "O download do vídeo foi interrompido repetidamente pelo Drive.",
        "Falha temporária ao baixar o vídeo do Drive.",
        "O arquivo recebido não contém uma estrutura MP4 válida.",
        "O vídeo mudou desde a consulta. Atualize o catálogo antes de tentar novamente.",
        "O vídeo recebido excedeu o tamanho confirmado no catálogo.",
        "O vídeo recebido não corresponde ao tamanho confirmado no catálogo.",
        "O download do vídeo excedeu o tempo de espera. Tente novamente mais tarde.",
        "Não foi possível baixar o vídeo do Drive. O arquivo de origem foi preservado.",
    }
    if message in safe_messages:
        return message
    if re.fullmatch(
            r"O vídeo foi identificado como \d{1,5} × \d{1,5}\. "
            r"Use vídeo vertical 9:16, preferencialmente 1080 × 1920\.", message):
        return message
    if re.fullmatch(
            r"Falha interna durante [A-Za-zÀ-ÿ ]+ \([A-Za-z][A-Za-z0-9_]*(?: errno \d+)?\)\. "
            r"O arquivo do Drive foi preservado\.", message):
        return message
    return ("Não foi possível validar tecnicamente este vídeo. Exporte novamente em MP4 "
            "vertical 9:16, com vídeo H.264, áudio AAC e duração entre 3 e 90 segundos.")


def _adaptive_time(value):
    if value is None:
        return None
    if (type(value) is not tuple or len(value) != 2 or
            type(value[0]) is not int or type(value[1]) is not int or
            not 0 <= value[0] <= 23 or not 0 <= value[1] <= 59):
        raise ReelError("O horário adaptativo de Reels não é válido.")
    return value


def suggest_due(store, *, now=None, adaptive_time=None):
    now = local_now(now)
    adaptive_time = _adaptive_time(adaptive_time)
    with store.connect() as connection:
        rows = connection.execute(
            "SELECT publication_day FROM reels WHERE publication_day IS NOT NULL ORDER BY publication_day"
        ).fetchall()
    used = {date.fromisoformat(row[0]) for row in rows}
    sequence = len(rows)
    day = now.date()
    while True:
        hour, minute = adaptive_time or INITIAL_TIMES[sequence % len(INITIAL_TIMES)]
        due = datetime.combine(day, time(hour, minute), ZONE)
        if day not in used and due.timestamp() >= now.timestamp() + MIN_NOTICE:
            return due
        day += timedelta(days=1)


def schedule(store, reel_id, due, caption, *, confirmed=False, now=None, adaptive_time=None):
    if confirmed is not True:
        raise ReelError("Confirme o Reel, a legenda, a conta e o horário.")
    due = local_now(due)
    now = local_now(now)
    adaptive_time = _adaptive_time(adaptive_time)
    approved_times = (adaptive_time,) if adaptive_time is not None else INITIAL_TIMES
    if (due.hour, due.minute) not in approved_times or due.second or due.microsecond:
        raise ReelError("Use o horário aprovado para Reels.")
    if due.timestamp() < now.timestamp() + MIN_NOTICE:
        raise ReelError("Agende o Reel com pelo menos dois minutos de antecedência.")
    if not isinstance(caption, str) or not caption.strip() or len(caption.strip()) > 2200:
        raise ReelError("Informe uma legenda válida para o Reel.")
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        policy = connection.execute("SELECT * FROM policy WHERE id=1").fetchone()
        if not policy["account_id"]:
            raise ReelError("Configure a conta Instagram antes de agendar Reels.")
        row = connection.execute("SELECT * FROM reels WHERE id=?", (reel_id,)).fetchone()
        if not row or row["state"] != "ready":
            raise ReelError("O Reel não está disponível para agendamento.")
        try:
            connection.execute("""UPDATE reels SET caption=?,publication_day=?,due_at=?,state='queued',
                error='' WHERE id=? AND state='ready'""",
                (caption.strip(), due.date().isoformat(), stamp(due), reel_id))
        except sqlite3.IntegrityError:
            raise ReelError("Já existe um Reel agendado para este dia ou horário.") from None
    return {"due_at": stamp(due)}


def cancel(store, reel_id, *, expected_due_at=None):
    filename = None
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT due_at,state,filename FROM reels WHERE id=?", (reel_id,)).fetchone()
        if (not row or row["state"] != "queued" or
                (expected_due_at is not None and row["due_at"] != expected_due_at)):
            raise ReelError("O Reel mudou ou o envio já começou.")
        connection.execute("""UPDATE reels SET state='cancelled',publication_day=NULL,due_at=NULL,
            claim='',claimed_at=NULL,error='' WHERE id=?""", (reel_id,))
        filename = row["filename"]
    _remove_media_copy(store, filename)


def expedite_test(store, *, confirmed=False, now=None):
    """Make today's single queued Reel due now for one supervised live test."""
    if confirmed is not True:
        raise ReelError("Confirme a publicação real imediata do Reel agendado.")
    current = local_now(now)
    current_stamp = stamp(current)
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        policy = connection.execute("SELECT * FROM policy WHERE id=1").fetchone()
        if not policy or not policy["enabled"] or not policy["account_id"]:
            raise ReelError("Ative e configure a fila antes do teste real.")
        rows = connection.execute(
            "SELECT id,publication_day,due_at FROM reels WHERE state='queued'").fetchall()
        if len(rows) != 1:
            raise ReelError("O teste real exige exatamente um Reel agendado.")
        row = rows[0]
        if row["publication_day"] != current.date().isoformat():
            raise ReelError("O teste real só antecipa o Reel agendado para hoje.")
        if connection.execute(
                "SELECT 1 FROM reels WHERE state='published' AND publication_day=? LIMIT 1",
                (current.date().isoformat(),)).fetchone():
            raise ReelError("Já existe um Reel publicado hoje.")
        connection.execute(
            "UPDATE reels SET due_at=?,error='' WHERE id=? AND state='queued'",
            (current_stamp, row["id"]))
        connection.execute(
            "INSERT INTO policy_events(action,account_id,created_at) VALUES(?,?,?)",
            ("expedite_test", policy["account_id"], current_stamp))
    return {"status": "queued", "due_at": current_stamp}


def _remove_media_copy(store, filename):
    """Remove only the verified private copy; the Drive original is untouched."""
    if not isinstance(filename, str) or not re.fullmatch(r"[a-f0-9]{32}\.(?:mp4|mov)", filename):
        return False
    target = store.media / filename
    try:
        if target.parent != store.media or target.is_symlink():
            return False
        info = target.stat()
        if not target.is_file() or info.st_nlink != 1:
            return False
        target.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def cleanup_media(store):
    """Best-effort cleanup for terminal rows after a previous interrupted cleanup."""
    with store.connect() as connection:
        rows = connection.execute("""SELECT filename FROM reels
            WHERE state IN ('published','cancelled')""").fetchall()
    return sum(_remove_media_copy(store, row["filename"]) for row in rows)


def _move_to_review(connection, reel_id, error):
    connection.execute("""UPDATE reels SET state='review',claim='',claimed_at=NULL,error=?
        WHERE id=?""", (error[:300], reel_id))
    connection.execute("UPDATE media_grants SET revoked=1 WHERE reel_id=?", (reel_id,))
    connection.execute("""UPDATE attempts SET outcome='review'
        WHERE reel_id=? AND outcome IN ('pending','processing')""", (reel_id,))


def claim_due(store, *, now=None):
    now_stamp = stamp(local_now(now))
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        policy = connection.execute("SELECT * FROM policy WHERE id=1").fetchone()
        if not policy["enabled"]:
            return None
        stale = connection.execute(
            "SELECT id FROM reels WHERE state='processing' AND claimed_at<?",
            (now_stamp - LEASE_SECONDS,)).fetchall()
        for row in stale:
            _move_to_review(
                connection, row["id"],
                "Processamento interrompido; confira o Instagram antes de reenviar.")
        row = connection.execute("""SELECT * FROM reels
            WHERE (state='processing' AND claim='') OR (state='queued' AND due_at<=?)
            ORDER BY CASE state WHEN 'processing' THEN 0 ELSE 1 END,due_at LIMIT 1""",
            (now_stamp,)).fetchone()
        if row is None:
            return None
        age = now_stamp - row["due_at"]
        if row["state"] == "queued" and age > MAX_LATENESS:
            _move_to_review(
                connection, row["id"],
                "Horário vencido há mais de 30 minutos; revise antes de reagendar.")
            return None
        if row["state"] == "processing" and age > MAX_PROCESSING_AGE:
            _move_to_review(
                connection, row["id"],
                "A Meta não concluiu o processamento em seis horas; confira o Instagram.")
            return None
        claim = secrets.token_hex(16)
        connection.execute("""UPDATE reels SET state='processing',claim=?,claimed_at=?,error=''
            WHERE id=? AND state IN ('queued','processing') AND claim=''""",
            (claim, now_stamp, row["id"]))
        attempt = secrets.token_hex(16)
        connection.execute("INSERT INTO attempts VALUES(?,?,?,?,'pending')",
                           (attempt, row["id"], "publish", now_stamp))
        result = dict(connection.execute("SELECT * FROM reels WHERE id=?", (row["id"],)).fetchone())
        result["attempt_id"] = attempt
        return result


def finish(store, reel_id, claim, *, remote_id=None, error=None, now=None):
    if not isinstance(claim, str) or not claim:
        raise ReelError("A tentativa de publicação não foi identificada.")
    published = isinstance(remote_id, str) and bool(re.fullmatch(r"[0-9_]{1,80}", remote_id))
    if not published and (not isinstance(error, str) or not error.strip()):
        raise ReelError("Um resultado incerto precisa ser enviado para revisão.")
    filename = None
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM reels WHERE id=? AND state='processing' AND claim=?",
            (reel_id, claim)).fetchone()
        if row is None:
            raise ReelError("A tentativa não está mais ativa.")
        if published:
            connection.execute("""UPDATE reels SET state='published',remote_id=?,published_at=?,
                claim='',claimed_at=NULL,error='' WHERE id=? AND claim=?""",
                (remote_id, stamp(local_now(now)), reel_id, claim))
            outcome = "published"
            filename = row["filename"]
        else:
            connection.execute("""UPDATE reels SET state='review',claim='',claimed_at=NULL,error=?
                WHERE id=? AND claim=?""", (error.strip()[:300], reel_id, claim))
            outcome = "review"
        connection.execute("UPDATE media_grants SET revoked=1 WHERE reel_id=?", (reel_id,))
        connection.execute("""UPDATE attempts SET outcome=?
            WHERE reel_id=? AND outcome IN ('pending','processing')""",
                           (outcome, reel_id))
    if published:
        _remove_media_copy(store, filename)
    return {"status": outcome}


def issue_media_grant(store, reel_id, claim, *, now=None):
    """Cria uma capacidade temporária sem expor o nome local do MP4."""
    from .media import issue_token

    now_stamp = stamp(local_now(now))
    token = issue_token()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("""SELECT id FROM reels
            WHERE id=? AND state='processing' AND claim=?""", (reel_id, claim)).fetchone()
        if row is None:
            raise ReelError("A tentativa do Reel não está ativa.")
        connection.execute("UPDATE media_grants SET revoked=1 WHERE reel_id=?", (reel_id,))
        connection.execute("INSERT INTO media_grants VALUES(?,?,?,0)",
                           (token_hash, reel_id, now_stamp + MEDIA_GRANT_SECONDS))
    return token


def resolve_media_grant(store, token, *, now=None):
    """Resolve um token para o servidor MP4 sem revelar o banco ao cliente."""
    from .media import MediaGrant

    if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token):
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now_stamp = int(clock.time()) if now is None else stamp(local_now(now))
    with store.connect() as connection:
        row = connection.execute("""SELECT g.expires_at,g.revoked,r.filename,r.state
            FROM media_grants g JOIN reels r ON r.id=g.reel_id
            WHERE g.token_hash=?""", (token_hash,)).fetchone()
    if row is None or row["state"] != "processing":
        return None
    return MediaGrant(row["filename"], row["expires_at"], bool(row["revoked"]))


def _release_processing(store, reel_id, claim, *, error=""):
    with store.connect() as connection:
        connection.execute("""UPDATE reels SET claim='',claimed_at=NULL,error=?
            WHERE id=? AND state='processing' AND claim=?""", (error[:300], reel_id, claim))


def _save_container(store, reel_id, claim, container):
    with store.connect() as connection:
        changed = connection.execute("""UPDATE reels SET container=?,claim='',claimed_at=NULL,error=''
            WHERE id=? AND state='processing' AND claim=? AND container=''""",
            (container, reel_id, claim))
        if changed.rowcount != 1:
            raise ReelError("A tentativa do Reel mudou durante a preparação.")
        connection.execute("""UPDATE attempts SET outcome='processing'
            WHERE reel_id=? AND outcome='pending'""", (reel_id,))


def row_account(store):
    with store.connect() as connection:
        row = connection.execute("SELECT account_id FROM policy WHERE id=1").fetchone()
    if row is None or not row["account_id"]:
        raise ReelError("A conta Instagram dos Reels não está configurada.")
    return row["account_id"]


def tick(store, client, *, now=None):
    """Avança no máximo uma etapa remota; nunca repete publicação incerta."""
    from .media import url_path
    from .meta_client import (MetaRejectedError, PreparationRetryError,
                              PublishUncertainError)

    current = local_now(now)
    row = claim_due(store, now=current)
    if row is None:
        return {"status": "idle"}
    ident, claim = row["id"], row["claim"]
    try:
        if not row["container"]:
            client.verify_account(row_account(store))
            token = issue_media_grant(store, ident, claim, now=current)
            video_url = client.media_origin + url_path(token, Path(row["filename"]).suffix)
            container = client.create_container(
                video_url, row["caption"], share_to_feed=True)["id"]
            _save_container(store, ident, claim, container)
            return {"status": "processing"}
        status = client.container_status(row["container"])
        if status == "IN_PROGRESS":
            _release_processing(store, ident, claim)
            return {"status": "processing"}
        if status != "FINISHED":
            return finish(store, ident, claim,
                          error="A Meta não confirmou o processamento do Reel.", now=current)
        remote = client.publish(row["container"])["id"]
        return finish(store, ident, claim, remote_id=remote, now=current)
    except PreparationRetryError as error:
        _release_processing(store, ident, claim, error=str(error))
        return {"status": "processing"}
    except (PublishUncertainError, MetaRejectedError, ReelError, ValueError) as error:
        return finish(store, ident, claim, error=str(error), now=current)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Operate the isolated Reels queue. New queues are disabled by default.")
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
            ("initialize", "Create the isolated queue in disabled state."),
            ("status", "Show policy and queue counts without changing state."),
            ("pause", "Disable new Reels processing immediately.")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--directory", required=True, type=Path)

    configure_command = commands.add_parser(
        "configure", help="Bind the Instagram account while keeping publishing disabled.")
    configure_command.add_argument("--directory", required=True, type=Path)
    configure_command.add_argument("--account-id", required=True)
    configure_command.add_argument("--confirm", required=True,
                                   metavar=CONFIGURE_CONFIRMATION)

    enable_command = commands.add_parser(
        "enable", help="Enable one automatic Reel per day for the configured account.")
    enable_command.add_argument("--directory", required=True, type=Path)
    enable_command.add_argument("--account-id", required=True)
    enable_command.add_argument("--confirm", required=True,
                                metavar=ENABLE_CONFIRMATION)

    test_command = commands.add_parser(
        "publish-test-now", help="Make today's one queued Reel due now for a supervised test.")
    test_command.add_argument("--directory", required=True, type=Path)
    test_command.add_argument("--confirm", required=True,
                              metavar=PUBLISH_TEST_CONFIRMATION)

    arguments = parser.parse_args(argv)
    store = Store(arguments.directory)
    if arguments.command == "initialize":
        store.initialize()
        print("Reels queue initialized. Publishing is disabled.")
        return
    if arguments.command == "configure":
        if arguments.confirm != CONFIGURE_CONFIRMATION:
            parser.error(f"--confirm must be exactly {CONFIGURE_CONFIRMATION}")
        configure(store, arguments.account_id, confirmed=True)
        print("Instagram account configured. Publishing remains disabled.")
        return
    if arguments.command == "enable":
        if arguments.confirm != ENABLE_CONFIRMATION:
            parser.error(f"--confirm must be exactly {ENABLE_CONFIRMATION}")
        enable(store, arguments.account_id, confirmed=True)
        print("Reels publishing enabled: at most one Reel per day.")
        return
    if arguments.command == "pause":
        pause(store)
        print("Reels publishing paused.")
        return
    if arguments.command == "publish-test-now":
        if arguments.confirm != PUBLISH_TEST_CONFIRMATION:
            parser.error(f"--confirm must be exactly {PUBLISH_TEST_CONFIRMATION}")
        result = expedite_test(store, confirmed=True)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return
    print(json.dumps(policy_status(store), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
