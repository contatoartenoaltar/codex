"""Importação e agendamento autônomos de um Reel pronto por dia."""
from __future__ import annotations

from pathlib import Path
import tempfile
import time

import drive_source
import social_schedule

from . import captions
from . import drive
from . import validator
from .queue import ReelError, cleanup_media, schedule, suggest_due, import_video


MAX_CANDIDATES_PER_RUN = 2


def _initialize(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS reel_import_errors(
        source_id TEXT PRIMARY KEY,source_md5 TEXT NOT NULL,
        error TEXT NOT NULL,seen_at INTEGER NOT NULL)""")


def _client(directory):
    try:
        credential = drive_source.credentials(directory)
    except drive_source.DriveError as error:
        raise ReelError(str(error)) from None
    return drive.VideoDriveClient(credential)


def _selected_time(schedule_directory):
    if schedule_directory is None:
        return None
    directory = Path(schedule_directory)
    if not directory.is_absolute() or directory.is_symlink():
        return None
    return social_schedule.selected(directory, "reel", None)


def _queue(store, reel_id, source_id, *, schedule_directory, now):
    adaptive_time = _selected_time(schedule_directory)
    due = suggest_due(store, now=now, adaptive_time=adaptive_time)
    schedule(store, reel_id, due, captions.choose(source_id), confirmed=True,
             now=now, adaptive_time=adaptive_time)
    return due


def run(store, drive_directory, *, client=None, media_validator=validator.inspect, now=None,
        schedule_directory=None):
    """Mantém no máximo um futuro Reel; falhas de um arquivo não param a fila."""
    drive_directory = Path(drive_directory)
    with store.connect() as connection:
        _initialize(connection)
        policy = connection.execute("SELECT enabled,account_id FROM policy WHERE id=1").fetchone()
        if policy is None or not policy["enabled"] or not policy["account_id"]:
            return {"status": "disabled"}
    cleanup_media(store)
    with store.connect() as connection:
        active = connection.execute("""SELECT id FROM reels
            WHERE state IN ('queued','processing') LIMIT 1""").fetchone()
        if active:
            return {"status": "idle"}
        if connection.execute("SELECT 1 FROM reels WHERE state='review' LIMIT 1").fetchone():
            return {"status": "review"}
        ready = connection.execute(
            "SELECT id,source_id FROM reels WHERE state='ready' ORDER BY imported_at LIMIT 1"
        ).fetchone()
    if ready:
        due = _queue(store, ready["id"], ready["source_id"],
                     schedule_directory=schedule_directory, now=now)
        return {"status": "queued", "reel_id": ready["id"], "due_at": int(due.timestamp())}

    client = client or _client(drive_directory)
    source = drive.catalog(drive_directory, client)
    with store.connect() as connection:
        known = {row["source_id"]: row["source_md5"] for row in connection.execute(
            "SELECT source_id,source_md5 FROM reels")}
        rejected = {row["source_id"]: row["source_md5"] for row in connection.execute(
            "SELECT source_id,source_md5 FROM reel_import_errors")}
    candidates = [item for item in source["files"]
                  if item["id"] not in known and rejected.get(item["id"]) != item["md5Checksum"]]
    if not candidates:
        return {"status": "empty"}

    for item in candidates[:MAX_CANDIDATES_PER_RUN]:
        try:
            with tempfile.TemporaryDirectory(dir=store.directory, prefix=".reel-import-") as temporary:
                downloaded = Path(temporary) / "source.mp4"
                client.download_video(item, downloaded)
                receipt = import_video(store, item, downloaded, validator=media_validator, now=now)
            with store.connect() as connection:
                connection.execute(
                    "DELETE FROM reel_import_errors WHERE source_id=?", (item["id"],))
            due = _queue(store, receipt["id"], item["id"],
                         schedule_directory=schedule_directory, now=now)
            return {"status": "queued", "reel_id": receipt["id"],
                    "due_at": int(due.timestamp())}
        except (OSError, ValueError) as error:
            with store.connect() as connection:
                _initialize(connection)
                connection.execute("""INSERT OR REPLACE INTO reel_import_errors
                    (source_id,source_md5,error,seen_at) VALUES(?,?,?,?)""",
                    (item["id"], item["md5Checksum"], str(error)[:300], int(time.time())))
    return {"status": "review"}
