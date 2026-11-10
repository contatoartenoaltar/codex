"""Importação e agendamento autônomos de um Reel pronto por dia."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import shutil
import time

import drive_source
import feed_composer
import social_schedule

from . import drive
from . import validator
from .queue import (ReelError, Store, _public_import_error, _validate_media, cleanup_media,
                    import_video, schedule, suggest_due)


MAX_CANDIDATES_PER_RUN = 2
STALE_STAGING_SECONDS = 30 * 60
STAGING_PREFIXES = (".reel-analysis-", ".reel-import-", ".reel-preflight-", ".reel-drive-")


def _initialize(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS reel_import_errors(
        source_id TEXT PRIMARY KEY,source_md5 TEXT NOT NULL,
        error TEXT NOT NULL,seen_at INTEGER NOT NULL)""")
    connection.execute("""CREATE TABLE IF NOT EXISTS reel_import_error_names(
        source_id TEXT PRIMARY KEY,source_name TEXT NOT NULL)""")


def _catalog_state(connection, files):
    """Reconcile remembered failures with the current complete Drive catalog."""
    known = {row["source_id"]: row["source_md5"] for row in connection.execute(
        "SELECT source_id,source_md5 FROM reels")}
    rejected = {row["source_id"]: row["source_md5"] for row in connection.execute(
        "SELECT source_id,source_md5 FROM reel_import_errors")}
    for source_id in set(rejected) & set(known):
        connection.execute("DELETE FROM reel_import_errors WHERE source_id=?", (source_id,))
        connection.execute("DELETE FROM reel_import_error_names WHERE source_id=?", (source_id,))
        rejected.pop(source_id, None)
    current_source_ids = {item["id"] for item in files}
    for source_id in set(rejected) - current_source_ids:
        connection.execute("DELETE FROM reel_import_errors WHERE source_id=?", (source_id,))
        connection.execute("DELETE FROM reel_import_error_names WHERE source_id=?", (source_id,))
        rejected.pop(source_id, None)
    for item in files:
        if item["id"] in rejected:
            connection.execute("""INSERT OR REPLACE INTO reel_import_error_names
                (source_id,source_name) VALUES(?,?)""", (item["id"], item["name"][:240]))
    return known, rejected


def _remember_error(connection, item, error):
    _initialize(connection)
    connection.execute("""INSERT OR REPLACE INTO reel_import_errors
        (source_id,source_md5,error,seen_at) VALUES(?,?,?,?)""",
        (item["id"], item["md5Checksum"], str(error)[:300], int(time.time())))
    connection.execute("""INSERT OR REPLACE INTO reel_import_error_names
        (source_id,source_name) VALUES(?,?)""", (item["id"], item["name"][:240]))


def _staging_file(directory, prefix, suffix):
    """Return a private, unpredictable destination that does not exist yet."""
    directory = Path(directory)
    for _ in range(20):
        candidate = directory / f".{prefix}-{secrets.token_hex(16)}{suffix}"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise ReelError("Não foi possível preparar o arquivo temporário do Reel.")


def _discard_staging(path):
    """Cleanup must never turn a successfully validated Reel into a rejection."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def cleanup_staging(store, *, now=None, force=False):
    """Remove legacy temporary directories and abandoned staging files safely."""
    current = time.time() if now is None else float(now)
    removed = 0
    for entry in store.directory.iterdir():
        if entry == store.media or entry.is_symlink():
            continue
        legacy_directory = entry.is_dir() and entry.name.startswith(STAGING_PREFIXES)
        stale_file = (entry.is_file() and
                      entry.name.startswith(STAGING_PREFIXES) and
                      (force or entry.stat().st_mtime <= current - STALE_STAGING_SECONDS))
        if not legacy_directory and not stale_file:
            continue
        try:
            shutil.rmtree(entry) if legacy_directory else entry.unlink()
            removed += 1
        except OSError:
            pass
    for entry in store.media.iterdir():
        if (entry.is_file() and not entry.is_symlink() and entry.name.startswith(".reel-") and
                (force or entry.stat().st_mtime <= current - STALE_STAGING_SECONDS)):
            try:
                entry.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def analyze_next(store, drive_directory, *, client=None, media_validator=validator.inspect,
                 now=None):
    """Validate and preserve one pending Drive video without scheduling or publishing it."""
    drive_directory = Path(drive_directory)
    cleanup_staging(store)
    client = client or _client(drive_directory)
    source = drive.catalog(drive_directory, client)
    with store.connect() as connection:
        _initialize(connection)
        known, _ = _catalog_state(connection, source["files"])
    # A manual request deliberately retries rejected files after operational fixes.
    candidates = [item for item in source["files"] if item["id"] not in known]
    if not candidates:
        return {"status": "up_to_date", "checked": 0}
    item = candidates[0]
    downloaded = _staging_file(
        store.directory, "reel-analysis", Path(item["name"]).suffix.lower())
    try:
        client.download_video(item, downloaded)
        receipt = import_video(store, item, downloaded, validator=media_validator, now=now,
                               move_source=True)
        with store.connect() as connection:
            connection.execute("DELETE FROM reel_import_errors WHERE source_id=?", (item["id"],))
            connection.execute("DELETE FROM reel_import_error_names WHERE source_id=?", (item["id"],))
        return {"status": "eligible", "checked": 1, "file": item["name"],
                "reel_id": receipt["id"]}
    except (OSError, ValueError) as error:
        with store.connect() as connection:
            _remember_error(connection, item, error)
        return {"status": "incompatible", "checked": 1, "file": item["name"],
                "error": _public_import_error(error)}
    finally:
        _discard_staging(downloaded)


def _client(directory):
    try:
        credential = drive_source.credentials(directory)
    except drive_source.DriveError as error:
        raise ReelError(str(error)) from None
    return drive.VideoDriveClient(credential)


def preflight(drive_directory, *, client=None, media_validator=validator.inspect):
    """Validate one real Drive video without importing, scheduling or publishing it."""
    drive_directory = Path(drive_directory)
    client = client or _client(drive_directory)
    source = drive.catalog(drive_directory, client)
    if not source["files"]:
        if source.get("skipped_invalid_video"):
            raise ReelError("A pasta possui vídeo incompatível com os limites de Reels.")
        raise ReelError("A pasta de Reels ainda não possui um vídeo MP4 ou MOV.")
    item = source["files"][0]
    downloaded = drive_directory / (
        ".reel-preflight-" + secrets.token_hex(16) + Path(item["name"]).suffix.lower())
    try:
        client.download_video(item, downloaded)
        duration, width, height, fps = _validate_media(media_validator(downloaded))
    finally:
        downloaded.unlink(missing_ok=True)
    return {
        "status": "ready",
        "file_name": item["name"],
        "bytes": item["size"],
        "duration_seconds": round(duration, 3),
        "width": width,
        "height": height,
        "fps": round(fps, 3),
        "publishing_enabled": False,
    }


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
    schedule(store, reel_id, due, feed_composer.standard_caption(), confirmed=True,
             now=now, adaptive_time=adaptive_time)
    return due


def apply_feed_caption(store):
    """Apply the official Feed caption only to untouched queued Reels."""
    caption = feed_composer.standard_caption()
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        changed = connection.execute("""UPDATE reels SET caption=?
            WHERE state='queued' AND claim='' AND container='' AND remote_id=''""", (caption,))
    return {"updated": changed.rowcount, "caption_length": len(caption)}


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
    cleanup_staging(store)
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
        known, rejected = _catalog_state(connection, source["files"])
    candidates = [item for item in source["files"]
                  if item["id"] not in known and rejected.get(item["id"]) != item["md5Checksum"]]
    if not candidates:
        return {"status": "empty"}

    for item in candidates[:MAX_CANDIDATES_PER_RUN]:
        downloaded = _staging_file(
            store.directory, "reel-import", Path(item["name"]).suffix.lower())
        try:
            client.download_video(item, downloaded)
            receipt = import_video(store, item, downloaded, validator=media_validator, now=now,
                                   move_source=True)
            with store.connect() as connection:
                connection.execute(
                    "DELETE FROM reel_import_errors WHERE source_id=?", (item["id"],))
                connection.execute(
                    "DELETE FROM reel_import_error_names WHERE source_id=?", (item["id"],))
            due = _queue(store, receipt["id"], item["id"],
                         schedule_directory=schedule_directory, now=now)
            return {"status": "queued", "reel_id": receipt["id"],
                    "due_at": int(due.timestamp())}
        except (OSError, ValueError) as error:
            with store.connect() as connection:
                _remember_error(connection, item, error)
        finally:
            _discard_staging(downloaded)
    return {"status": "review"}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate a finished Reel from Drive without scheduling or publishing it.")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser(
        "preflight", help="Download and validate the first accepted MP4/MOV, then delete the copy.")
    command.add_argument("--drive-directory", required=True, type=Path)
    caption_command = commands.add_parser(
        "apply-feed-caption", help="Use the official Feed caption on untouched queued Reels.")
    caption_command.add_argument("--reels-directory", required=True, type=Path)
    cleanup_command = commands.add_parser(
        "cleanup-staging", help="Remove only abandoned private Reels temporary files.")
    cleanup_command.add_argument("--reels-directory", required=True, type=Path)
    cleanup_command.add_argument("--confirm", required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "preflight":
            result = preflight(arguments.drive_directory)
        elif arguments.command == "apply-feed-caption":
            result = apply_feed_caption(Store(arguments.reels_directory))
        else:
            if arguments.confirm != "CLEANUP-REELS-TEMPORARY-FILES":
                raise ReelError("Confirme a limpeza exclusiva dos temporários de Reels.")
            result = {"removed": cleanup_staging(
                Store(arguments.reels_directory), force=True)}
    except (OSError, ValueError) as error:
        raise SystemExit("ERROR: " + str(error)) from None
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
