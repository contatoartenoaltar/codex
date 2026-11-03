"""Prepara e publica Stories promocionais sem tocar nas filas existentes."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta, time
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
from zoneinfo import ZoneInfo

import drive_source
import promotional_story
from PIL import Image


ZONE = ZoneInfo("America/Sao_Paulo")
ACCOUNT = "arte.no.altar"
APPLICATION_ID = 0x41415053
MIN_NOTICE = 120
MAX_LATENESS = 1800
LEASE = 600
PREPARE_AHEAD = 300
MEDIA_LIMIT = 500 * 1024 * 1024
RETENTION_DAYS = 30


def local_now(now=None):
    value = datetime.now(ZONE) if now is None else now
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Informe uma data com fuso horário.")
    return value.astimezone(ZONE)


def stamp(value):
    return int(value.timestamp())


def _due(day: date, value: str):
    hour, minute = map(int, value.split(":"))
    return datetime.combine(day, time(hour, minute), ZONE)


SCHEMA = [
    "CREATE TABLE IF NOT EXISTS policy(id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL, mode TEXT NOT NULL, account_id TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, day TEXT NOT NULL UNIQUE, cycle INTEGER NOT NULL, created_at INTEGER NOT NULL)",
    """CREATE TABLE IF NOT EXISTS slots(
        id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id), day TEXT NOT NULL,
        position INTEGER NOT NULL, due_at INTEGER NOT NULL UNIQUE, model_id TEXT NOT NULL,
        model_name TEXT NOT NULL, phrase_index INTEGER NOT NULL, filename TEXT NOT NULL,
        image_hash TEXT NOT NULL, manifest_hash TEXT NOT NULL, state TEXT NOT NULL,
        staged_photo TEXT NOT NULL DEFAULT '', container TEXT NOT NULL DEFAULT '',
        remote_id TEXT NOT NULL DEFAULT '', claim TEXT NOT NULL DEFAULT '', claimed_at INTEGER,
        error TEXT NOT NULL DEFAULT '', UNIQUE(batch_id,position), UNIQUE(batch_id,model_id),
        UNIQUE(batch_id,phrase_index))""",
    """CREATE TABLE IF NOT EXISTS model_history(
        cycle INTEGER NOT NULL, model_id TEXT NOT NULL, batch_id TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(cycle,model_id))""",
    """CREATE TABLE IF NOT EXISTS attempts(
        id TEXT PRIMARY KEY, slot_id TEXT NOT NULL REFERENCES slots(id), phase TEXT NOT NULL,
        created_at INTEGER NOT NULL, outcome TEXT NOT NULL DEFAULT 'pending')""",
    """CREATE TABLE IF NOT EXISTS http_runtime(
        id INTEGER PRIMARY KEY CHECK(id=1), last_started INTEGER NOT NULL,
        lease TEXT NOT NULL, lease_until INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS policy_events(
        id INTEGER PRIMARY KEY, action TEXT NOT NULL, account_id TEXT NOT NULL, created_at INTEGER NOT NULL)""",
]


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "promotional-story-queue.sqlite3"
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValueError("Não use links simbólicos no armazenamento promocional.")

    def initialize(self):
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValueError("Não use links simbólicos no armazenamento promocional.")
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.execute("BEGIN IMMEDIATE")
            identity = conn.execute("PRAGMA application_id").fetchone()[0]
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if identity not in (0, APPLICATION_ID) or (identity == 0 and tables):
                raise ValueError("Recusado: banco existente não pertence aos Stories promocionais.")
            conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
            for statement in SCHEMA:
                conn.execute(statement)
            if "batch_id" not in {row[1] for row in conn.execute("PRAGMA table_info(model_history)")}:
                conn.execute("ALTER TABLE model_history ADD COLUMN batch_id TEXT NOT NULL DEFAULT ''")
            conn.execute("INSERT OR IGNORE INTO policy VALUES(1,0,'live','')")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def connect(self):
        if not self.path.is_file() or self.path.is_symlink():
            raise ValueError("Inicialize o armazenamento promocional isolado.")
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            if conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise ValueError("Este banco não pertence aos Stories promocionais.")
            conn.execute("PRAGMA foreign_keys=ON")
            with conn:
                yield conn
        finally:
            conn.close()

    def agenda(self):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM slots ORDER BY due_at")]


def drive_catalog(directory, client=None):
    """Consulta a pasta configurada sem reescrever configuração ou cache do feed."""
    directory = Path(directory)
    config = drive_source.read_json(directory / drive_source.CONFIG_FILE)
    folder = drive_source.identifier(config.get("folder_id"))
    client = client or drive_source.DriveClient(drive_source.credentials(directory))
    catalog = client.catalog(folder)
    if catalog.get("complete") is not True or catalog.get("folder_id") != folder:
        raise ValueError("O Drive não confirmou o catálogo completo.")
    files = [item for item in catalog.get("files", [])
             if item.get("mimeType") in ("image/png", "image/jpeg")]
    files.sort(key=lambda item: (tuple(item.get("path", [])), item.get("id", "")))
    unique = {item.get("id") for item in files}
    if len(files) < 10 or len(unique) != len(files) or None in unique:
        raise ValueError("O catálogo precisa ter ao menos 10 modelos válidos e diferentes.")
    return files, client


def _candidates(conn, files):
    cycle = conn.execute("SELECT COALESCE(MAX(cycle),1) FROM model_history").fetchone()[0]
    used = [row[0] for row in conn.execute(
        "SELECT model_id FROM model_history WHERE cycle=? ORDER BY rowid", (cycle,))]
    active = {item["id"] for item in files}
    active_used = {ident for ident in used if ident in active}
    remaining = [item for item in files if item["id"] not in active_used]
    previous = [item for item in files if item["id"] in active_used]
    # Tenta cada modelo no máximo uma vez no lote. Se os remanescentes não
    # renderizarem dez faces, atravessa o fim do ciclo sem repetir no dia.
    return ([(cycle, item) for item in remaining] +
            [(cycle + 1, item) for item in previous])


def _next_day(conn, now):
    latest = conn.execute("SELECT day FROM batches ORDER BY day DESC LIMIT 1").fetchone()
    day = now.date()
    if _due(day, promotional_story.TIMES[0]).timestamp() < now.timestamp() + MIN_NOTICE:
        day += timedelta(days=1)
    if latest:
        day = max(day, date.fromisoformat(latest[0]) + timedelta(days=1))
    return day


def _write_art(media, ident, raw, phrase_index, source):
    image, metadata = promotional_story.render(raw, phrase_index)
    target = media / f"{ident}.jpg"
    manifest = target.with_suffix(".json")
    fd_image, temporary_image = tempfile.mkstemp(dir=media, prefix=".promo-", suffix=".jpg")
    fd_manifest, temporary_manifest = tempfile.mkstemp(dir=media, prefix=".promo-", suffix=".json")
    try:
        if target.exists() or target.is_symlink() or manifest.exists() or manifest.is_symlink():
            raise ValueError("O identificador da nova arte promocional já existe.")
        with os.fdopen(fd_image, "wb") as image_stream, \
             os.fdopen(fd_manifest, "w", encoding="utf-8") as stream:
            image.save(image_stream, "JPEG", quality=95, subsampling=0, optimize=True)
            image_stream.flush()
            image_hash = hashlib.sha256(Path(temporary_image).read_bytes()).hexdigest()
            payload = metadata | {"model_id": source["id"], "model_name": source["name"],
                                  "image_sha256": image_hash}
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.link(temporary_image, target)
        try:
            os.link(temporary_manifest, manifest)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        target.chmod(0o600)
        manifest.chmod(0o600)
        return target, image_hash, hashlib.sha256(manifest.read_bytes()).hexdigest()
    finally:
        Path(temporary_image).unlink(missing_ok=True)
        Path(temporary_manifest).unlink(missing_ok=True)


def cleanup_media(store, *, now=None):
    """Remove só arquivos promocionais publicados e vencidos; preserva o histórico."""
    cutoff = stamp(local_now(now) - timedelta(days=RETENTION_DAYS))
    removed = 0
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT id,filename FROM slots WHERE state='published' AND due_at<?", (cutoff,)).fetchall()
        media = store.directory / "media"
        if media.is_symlink():
            raise ValueError("A mídia promocional precisa estar em diretório local.")
        for row in rows:
            if row["filename"] != row["id"] + ".jpg":
                raise ValueError("Registro promocional inválido; retenção interrompida.")
            image = media / row["filename"]
            for path in (image, image.with_suffix(".json")):
                if path.is_symlink():
                    raise ValueError("A retenção não remove links simbólicos.")
                if path.exists():
                    path.unlink()
                    removed += 1
    return removed


def prepare_batch(store, drive_directory, *, client=None, now=None):
    """Cria um lote diário em rascunho; nunca o autoriza nem ativa publicação."""
    now = local_now(now)
    media = store.directory / "media"
    if media.is_symlink():
        raise ValueError("A mídia promocional precisa estar em diretório local.")
    media.mkdir(parents=True, exist_ok=True)
    cleanup_media(store, now=now)
    with store.connect() as conn:
        draft = conn.execute("SELECT id FROM batches WHERE id IN (SELECT batch_id FROM slots WHERE state='draft') ORDER BY day LIMIT 1").fetchone()
        if draft:
            return {"batch_id": draft[0], "created": False}
        day = _next_day(conn, now)
    files, client = drive_catalog(drive_directory, client)
    created = []
    try:
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM batches WHERE day=?", (day.isoformat(),)).fetchone():
                row = conn.execute("SELECT id FROM batches WHERE day=?", (day.isoformat(),)).fetchone()
                return {"batch_id": row[0], "created": False}
            batch = secrets.token_hex(16)
            phrase_indices = promotional_story.daily_phrase_indices(day.toordinal())
            rows = []
            history = []
            batch_cycle = 1
            for cycle, source in _candidates(conn, files):
                if len(rows) == len(promotional_story.TIMES):
                    break
                history.append((cycle, source["id"], batch))
                raw = client.download_image(source)
                ident = secrets.token_hex(16)
                position = len(rows) + 1
                time_value = promotional_story.TIMES[position - 1]
                phrase_index = phrase_indices[position - 1]
                try:
                    target, image_hash, manifest_hash = _write_art(
                        media, ident, raw, phrase_index, source)
                except promotional_story.PreviewError:
                    continue
                created.extend((target, target.with_suffix(".json")))
                rows.append((ident, batch, day.isoformat(), position, stamp(_due(day, time_value)),
                             source["id"], source["name"], phrase_index, target.name,
                             image_hash, manifest_hash, "draft"))
                batch_cycle = cycle
            if len(rows) != len(promotional_story.TIMES):
                raise ValueError(
                    "O catálogo não contém 10 faces de envelope identificáveis para este lote.")
            if sum(path.stat().st_size for path in media.iterdir() if path.is_file()) > MEDIA_LIMIT:
                raise ValueError("O armazenamento promocional atingiu o limite; revise a retenção.")
            conn.execute("INSERT INTO batches VALUES(?,?,?,?)",
                         (batch, day.isoformat(), batch_cycle, stamp(now)))
            conn.executemany("""INSERT INTO slots(id,batch_id,day,position,due_at,model_id,model_name,
                phrase_index,filename,image_hash,manifest_hash,state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
            conn.executemany(
                "INSERT INTO model_history(cycle,model_id,batch_id) VALUES(?,?,?)", history)
            return {"batch_id": batch, "created": True, "day": day.isoformat()}
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def verify_image(store, row):
    name = row["filename"]
    ident = row["id"]
    if name != ident + ".jpg" or len(ident) != 32 or any(c not in "0123456789abcdef" for c in ident):
        raise ValueError("Arquivo promocional inválido.")
    media = store.directory / "media"
    image, manifest = media / name, (media / name).with_suffix(".json")
    if media.is_symlink() or image.is_symlink() or manifest.is_symlink():
        raise ValueError("A arte promocional precisa ser um arquivo local.")
    if (hashlib.sha256(image.read_bytes()).hexdigest() != row["image_hash"] or
            hashlib.sha256(manifest.read_bytes()).hexdigest() != row["manifest_hash"]):
        raise ValueError("Arte ou manifesto alterados após a revisão.")
    try:
        with Image.open(image) as decoded:
            if decoded.format != "JPEG" or decoded.size != promotional_story.SIZE:
                raise ValueError("A arte promocional precisa ser JPEG 1080 × 1920.")
            decoded.verify()
    except (OSError, SyntaxError):
        raise ValueError("A arte promocional não é um JPEG válido.") from None
    data = json.loads(manifest.read_text(encoding="utf-8"))
    expected = promotional_story.PHRASES[row["phrase_index"]]
    if (data.get("version") != "promotional-story-envelope-face-v5" or
            data.get("cutout_version") != "paper-quad-v2" or
            data.get("size") != list(promotional_story.SIZE) or
            data.get("model_id") != row["model_id"] or
            data.get("model_name") != row["model_name"] or
            data.get("phrase_index") != row["phrase_index"] or
            data.get("title_lines") != list(expected) or
            data.get("image_sha256") != row["image_hash"]):
        raise ValueError("Modelo, título ou cenário promocional mudou.")
    return image


def reject_batch(store, batch_id, *, confirmed=False):
    """Descarta um lote ainda não aprovado e libera seus modelos para nova arte."""
    if confirmed is not True:
        raise ValueError("Confirme o descarte do lote promocional reprovado.")
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        batch = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        rows = conn.execute(
            "SELECT * FROM slots WHERE batch_id=? ORDER BY position", (batch_id,)).fetchall()
        if batch is None or len(rows) != 10 or any(row["state"] != "draft" for row in rows):
            raise ValueError("Somente um lote completo ainda em rascunho pode ser descartado.")
        model_ids = [row["model_id"] for row in rows]
        placeholders = ",".join("?" for _ in model_ids)
        conn.execute("DELETE FROM model_history WHERE batch_id=? OR (cycle=? AND model_id IN (" +
                     placeholders + "))", (batch_id, batch["cycle"], *model_ids))
        conn.execute("DELETE FROM slots WHERE batch_id=?", (batch_id,))
        conn.execute("DELETE FROM batches WHERE id=?", (batch_id,))
        conn.execute("INSERT INTO policy_events(action,account_id,created_at) "
                     "SELECT ?,account_id,? FROM policy WHERE id=1",
                     ("reject_batch:" + batch_id, stamp(local_now())))
    media = store.directory / "media"
    for row in rows:
        image = media / row["filename"]
        for path in (image, image.with_suffix(".json")):
            if path.is_symlink():
                raise ValueError("O descarte não remove links simbólicos.")
            path.unlink(missing_ok=True)
    return {"batch_id": batch_id, "rejected": True}


def queue_batch(store, batch_id, *, confirmed=False, now=None):
    if confirmed is not True:
        raise ValueError("Confirme as 10 artes e os horários do lote revisado.")
    now = local_now(now)
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("SELECT * FROM slots WHERE batch_id=? ORDER BY position", (batch_id,)).fetchall()
        if len(rows) != 10:
            raise ValueError("O lote promocional precisa conter exatamente 10 Stories.")
        if [datetime.fromtimestamp(row["due_at"], ZONE).strftime("%H:%M") for row in rows] != list(promotional_story.TIMES):
            raise ValueError("Os horários promocionais mudaram.")
        for row in rows:
            if row["state"] != "draft" or row["due_at"] < stamp(now) + MIN_NOTICE:
                raise ValueError("Lote alterado ou horário vencido; não será reagendado automaticamente.")
            verify_image(store, row)
        conn.execute("UPDATE slots SET state='queued' WHERE batch_id=?", (batch_id,))


def configure_live(store, account_id, *, confirmed=False):
    if confirmed is not True or not isinstance(account_id, str) or not account_id.isdecimal() or int(account_id) <= 0:
        raise ValueError("Confirme a conta empresarial de destino.")
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        policy = conn.execute("SELECT * FROM policy WHERE id=1").fetchone()
        if policy["enabled"] or (policy["account_id"] and policy["account_id"] != account_id):
            raise ValueError("A conta desta fila promocional não pode ser substituída.")
        conn.execute("UPDATE policy SET account_id=?,enabled=0 WHERE id=1", (account_id,))
        conn.execute("INSERT INTO policy_events(action,account_id,created_at) VALUES(?,?,?)",
                     ("configure_live_disabled", account_id, stamp(local_now())))


def enable_live(store, *, confirmed=False, now=None):
    if confirmed is not True:
        raise ValueError("Confirme explicitamente a ativação dos Stories promocionais reais.")
    now = local_now(now)
    with store.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        policy = conn.execute("SELECT * FROM policy WHERE id=1").fetchone()
        rows = conn.execute("SELECT * FROM slots WHERE state IN ('queued','staged','processing','sending','review')").fetchall()
        if not policy["account_id"] or not rows:
            raise ValueError("Prepare e revise uma fila promocional para a conta real.")
        for row in rows:
            if row["state"] != "queued" or row["due_at"] < stamp(now) + MIN_NOTICE:
                raise ValueError("Há horário vencido ou envio que exige conferência.")
            verify_image(store, row)
        conn.execute("UPDATE policy SET enabled=1 WHERE id=1")
        conn.execute("INSERT INTO policy_events(action,account_id,created_at) VALUES(?,?,?)",
                     ("enable_live", policy["account_id"], stamp(now)))


def pause(store):
    with store.connect() as conn:
        conn.execute("UPDATE policy SET enabled=0 WHERE id=1")
        conn.execute("INSERT INTO policy_events(action,account_id,created_at) SELECT ?,account_id,? FROM policy WHERE id=1",
                     ("pause", stamp(local_now())))


def tick(store, transport=None, *, now=None):
    """Processa somente itens já revisados; nunca cria ou aprova um lote."""
    now = local_now(now)
    with store.connect() as conn:
        policy = conn.execute("SELECT * FROM policy WHERE id=1").fetchone()
        if not policy["enabled"]:
            return {"status": "disabled"}
        if (transport is None or getattr(transport, "simulation", None) is not False or
                getattr(transport, "requires_staging", None) is not True or
                getattr(transport, "account_id", None) != policy["account_id"]):
            return {"status": "unconfigured"}
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE slots SET state='review',error='Resultado incerto; não reenviar.' WHERE state='sending' AND claimed_at<=?", (stamp(now)-LEASE,))
        conn.execute("UPDATE attempts SET outcome='review' WHERE outcome='pending' AND slot_id IN (SELECT id FROM slots WHERE state='review')")
        row = conn.execute("""SELECT * FROM slots WHERE
            (state='processing' AND due_at<=?) OR (state IN ('queued','staged') AND due_at<=?)
            ORDER BY due_at LIMIT 1""", (stamp(now), stamp(now)+PREPARE_AHEAD)).fetchone()
        if row is None:
            return {"status": "busy" if conn.execute("SELECT 1 FROM slots WHERE state='sending'").fetchone() else "idle"}
        if stamp(now) - row["due_at"] > MAX_LATENESS:
            conn.execute("UPDATE slots SET state='review',error='Horário vencido; requer conferência.' WHERE id=?", (row["id"],))
            return {"status": "expired"}
        claim = secrets.token_hex(16)
        phase = "publish" if row["state"] == "processing" else "stage" if row["state"] == "queued" else "create"
        conn.execute("UPDATE slots SET state='sending',claim=?,claimed_at=? WHERE id=?", (claim, stamp(now), row["id"]))
        conn.execute("INSERT INTO attempts(id,slot_id,phase,created_at) VALUES(?,?,?,?)", (claim, row["id"], phase, stamp(now)))
    try:
        image = verify_image(store, row)
        account = transport.verify_account(policy["account_id"])
        if (account.get("id") != policy["account_id"] or account.get("username") != ACCOUNT or
                account.get("account_type") != "BUSINESS" or account.get("stories_allowed") is not True):
            raise ValueError("A conta não corresponde ao Instagram empresarial autorizado.")
        photo, container, remote = row["staged_photo"], row["container"], ""
        if phase == "stage":
            photo = transport.stage_image(image).get("id")
            if not isinstance(photo, str) or not photo:
                raise ValueError("Imagem de apoio não confirmada.")
            state, container = "staged", ""
        elif phase == "create":
            container = transport.create_container(image, media_type="STORIES", staged_photo=photo).get("id")
            if not isinstance(container, str) or not container:
                raise ValueError("Contêiner não confirmado.")
            state = "processing"
        else:
            status = transport.container_status(container)
            if status == "IN_PROGRESS":
                state = "processing"
            elif status == "FINISHED":
                remote = transport.publish(container).get("id")
                if not isinstance(remote, str) or not remote:
                    raise ValueError("Publicação não confirmada.")
                state = "published"
            else:
                raise ValueError("Processamento não confirmado.")
    except Exception:
        with store.connect() as conn:
            conn.execute("UPDATE slots SET state='review',error='Falha ou resultado incerto; conferir antes de repetir.' WHERE id=? AND claim=?", (row["id"], claim))
            conn.execute("UPDATE attempts SET outcome='review' WHERE id=?", (claim,))
        return {"status": "review"}
    with store.connect() as conn:
        changed = conn.execute("""UPDATE slots SET state=?,container=?,remote_id=?,staged_photo=?,
            claim='',claimed_at=NULL WHERE id=? AND claim=? AND state='sending'""",
            (state, container, remote, photo, row["id"], claim))
        if changed.rowcount != 1:
            state = "review"
        conn.execute("UPDATE attempts SET outcome=? WHERE id=?", (state, claim))
    return {"status": state}


def main():
    parser = argparse.ArgumentParser(description="Fila isolada dos Stories promocionais.")
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--drive-directory", type=Path)
    parser.add_argument("--account")
    parser.add_argument("--batch")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("action", choices=[
        "prepare", "agenda", "configure-live", "queue", "reject", "enable-live", "pause"])
    args = parser.parse_args()
    store = Store(args.directory)
    store.initialize()
    if args.action == "prepare":
        if not args.drive_directory:
            parser.error("--drive-directory é obrigatório para preparar")
        prepare_batch(store, args.drive_directory)
    elif args.action == "configure-live":
        configure_live(store, args.account, confirmed=args.confirm)
    elif args.action == "queue":
        queue_batch(store, args.batch, confirmed=args.confirm)
    elif args.action == "reject":
        reject_batch(store, args.batch, confirmed=args.confirm)
    elif args.action == "enable-live":
        enable_live(store, confirmed=args.confirm)
    elif args.action == "pause":
        pause(store)
    with store.connect() as conn:
        policy = dict(conn.execute("SELECT * FROM policy WHERE id=1").fetchone())
    print(json.dumps({"environment": policy["mode"], "publishing_enabled": bool(policy["enabled"]),
                      "account_id": policy["account_id"], "items": store.agenda()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
