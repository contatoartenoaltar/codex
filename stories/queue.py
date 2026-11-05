"""Lotes locais de três Stories, em armazenamento independente do sistema.

Não importa app nem lê credenciais. Transporte e modo precisam corresponder;
o modo real exige armazenamento novo e ativação explícita, separada dos testes.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, time
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
from zoneinfo import ZoneInfo

from . import preview


ZONE = ZoneInfo('America/Sao_Paulo')
ACCOUNT = 'arte.no.altar'
APPLICATION_ID = 0x41415354
MIN_NOTICE = 120
MAX_LATENESS = 1800
LEASE = 600
PREPARE_AHEAD = 300


def local_now(now=None):
    value = datetime.now(ZONE) if now is None else now
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Informe uma data com fuso horário.')
    return value.astimezone(ZONE)


def stamp(value):
    return int(value.timestamp())


def catalog():
    values = preview.verses()
    if (len(values) < 3 or len({v['id'] for v in values}) != len(values) or
            len({v['reference'] for v in values}) != len(values) or
            any(v['translation'] != 'ARC' for v in values)):
        raise ValueError('O catálogo precisa de ao menos três versículos ARC distintos.')
    return values


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'story-queue.sqlite3'
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValueError('Não use links simbólicos no armazenamento de Stories.')

    @contextmanager
    def connect(self):
        if not self.path.is_file() or self.path.is_symlink():
            raise ValueError('Inicialize o armazenamento isolado de Stories.')
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            if conn.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
                raise ValueError('Este banco não pertence ao módulo de Stories.')
            conn.execute('PRAGMA foreign_keys=ON')
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValueError('Não use links simbólicos no armazenamento de Stories.')
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.execute('BEGIN IMMEDIATE')
            identity = conn.execute('PRAGMA application_id').fetchone()[0]
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if identity not in (0, APPLICATION_ID) or (identity == 0 and tables):
                raise ValueError('Recusado: banco existente não pertence aos Stories.')
            conn.execute(f'PRAGMA application_id={APPLICATION_ID}')
            for statement in SCHEMA:
                conn.execute(statement)
            if 'staged_photo' not in {r[1] for r in conn.execute('PRAGMA table_info(slots)')}:
                conn.execute("ALTER TABLE slots ADD COLUMN staged_photo TEXT NOT NULL DEFAULT ''")
            conn.execute("INSERT OR IGNORE INTO policy VALUES(1,0,'simulation','')")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def agenda(self):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute('SELECT * FROM slots ORDER BY due_at')]


SCHEMA = [
    "CREATE TABLE IF NOT EXISTS policy(id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL, mode TEXT NOT NULL, account_id TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, first_day TEXT NOT NULL UNIQUE, last_day TEXT NOT NULL, created_at INTEGER NOT NULL)",
    """CREATE TABLE IF NOT EXISTS slots(
        id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id), day TEXT NOT NULL UNIQUE,
        due_at INTEGER NOT NULL UNIQUE, verse_id TEXT NOT NULL, verse_json TEXT NOT NULL,
        cycle INTEGER NOT NULL, filename TEXT NOT NULL, image_hash TEXT NOT NULL, manifest_hash TEXT NOT NULL,
        state TEXT NOT NULL, container TEXT NOT NULL DEFAULT '', remote_id TEXT NOT NULL DEFAULT '',
        claim TEXT NOT NULL DEFAULT '', claimed_at INTEGER, error TEXT NOT NULL DEFAULT '')""",
    "CREATE TABLE IF NOT EXISTS verse_history(cycle INTEGER NOT NULL, reference TEXT NOT NULL, PRIMARY KEY(cycle,reference))",
    """CREATE TABLE IF NOT EXISTS attempts(
        id TEXT PRIMARY KEY, slot_id TEXT NOT NULL REFERENCES slots(id), phase TEXT NOT NULL,
        created_at INTEGER NOT NULL, outcome TEXT NOT NULL DEFAULT 'pending')""",
    """CREATE TABLE IF NOT EXISTS http_runtime(
        id INTEGER PRIMARY KEY CHECK(id=1), last_started INTEGER NOT NULL,
        lease TEXT NOT NULL, lease_until INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS policy_events(
        id INTEGER PRIMARY KEY, action TEXT NOT NULL, account_id TEXT NOT NULL, created_at INTEGER NOT NULL)""",
]


def prepare_batch(store, *, now=None):
    """Cria três artes atomicamente; repetição e reinício preservam o mesmo lote."""
    now = local_now(now)
    values = catalog()
    if (store.directory / 'media').is_symlink() or not preview.layout_approved(preview.assets()):
        raise ValueError('Use o armazenamento local e o layout aprovado antes de preparar o lote.')
    created = []
    try:
        with store.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            latest = conn.execute('SELECT * FROM batches ORDER BY first_day DESC LIMIT 1').fetchone()
            if (latest and
                    datetime.fromisoformat(latest['last_day']).date() > now.date() + timedelta(days=1)):
                return {'batch_id': latest['id'], 'created': False}
            earliest = now.date()
            due = datetime.combine(earliest, time(7, 30), ZONE)
            if stamp(due) < stamp(now) + MIN_NOTICE:
                earliest += timedelta(days=1)
            if latest:
                # Um lote de revisão ainda não autorizado não provoca reposição.
                if conn.execute("SELECT 1 FROM slots WHERE batch_id=? AND state='draft'", (latest['id'],)).fetchone():
                    return {'batch_id': latest['id'], 'created': False}
                earliest = max(earliest, datetime.fromisoformat(latest['last_day']).date() + timedelta(days=1))
            batch = secrets.token_hex(16)
            conn.execute('INSERT INTO batches VALUES(?,?,?,?)',
                         (batch, earliest.isoformat(), (earliest + timedelta(days=2)).isoformat(), stamp(now)))
            for index in range(3):
                cycle = conn.execute('SELECT COALESCE(MAX(cycle),1) FROM verse_history').fetchone()[0]
                used = {r[0] for r in conn.execute('SELECT reference FROM verse_history WHERE cycle=?', (cycle,))}
                remaining = [v for v in values if v['reference'] not in used]
                if not remaining:
                    cycle += 1
                    last = conn.execute('SELECT verse_json FROM slots ORDER BY due_at DESC LIMIT 1').fetchone()
                    previous = json.loads(last[0])['reference'] if last else None
                    remaining = [v for v in values if v['reference'] != previous]
                verse = secrets.choice(remaining)
                day = earliest + timedelta(days=index)
                ident = secrets.token_hex(16)
                image = store.directory / 'media' / (ident + '.jpg')
                metadata = preview.export(None, image, verse_id=verse['id'])
                created.extend((image, image.with_suffix('.json')))
                conn.execute('INSERT INTO verse_history VALUES(?,?)', (cycle, verse['reference']))
                conn.execute('''INSERT INTO slots(id,batch_id,day,due_at,verse_id,verse_json,cycle,
                    filename,image_hash,manifest_hash,state) VALUES(?,?,?,?,?,?,?,?,?,?,'draft')''',
                    (ident, batch, day.isoformat(), stamp(datetime.combine(day, time(7, 30), ZONE)),
                     verse['id'], json.dumps(verse, ensure_ascii=False), cycle, image.name,
                     metadata['image_sha256'], hashlib.sha256(image.with_suffix('.json').read_bytes()).hexdigest()))
            return {'batch_id': batch, 'created': True}
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def queue_batch(store, batch_id, *, confirmed=False, now=None):
    if confirmed is not True:
        raise ValueError('Confirme os três Stories e os horários do lote revisado.')
    now = local_now(now)
    with store.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        rows = conn.execute('SELECT * FROM slots WHERE batch_id=? ORDER BY due_at', (batch_id,)).fetchall()
        if len(rows) != 3:
            raise ValueError('O lote precisa conter exatamente três Stories.')
        for row in rows:
            if row['state'] != 'draft' or row['due_at'] < stamp(now) + MIN_NOTICE:
                raise ValueError('Lote alterado ou horário vencido; não será reagendado automaticamente.')
            verify_image(store, row)
        conn.execute("UPDATE slots SET state='queued' WHERE batch_id=?", (batch_id,))


def verify_image(store, row):
    name = row['filename']
    if name != row['id'] + '.jpg' or len(row['id']) != 32 or any(c not in '0123456789abcdef' for c in row['id']):
        raise ValueError('Arquivo do Story inválido.')
    directory = store.directory / 'media'
    image, manifest = directory / name, (directory / name).with_suffix('.json')
    if directory.is_symlink() or image.is_symlink() or manifest.is_symlink():
        raise ValueError('Arquivo do Story precisa ser local, sem links.')
    if (hashlib.sha256(image.read_bytes()).hexdigest() != row['image_hash'] or
            hashlib.sha256(manifest.read_bytes()).hexdigest() != row['manifest_hash']):
        raise ValueError('Arte ou manifesto alterados após a revisão.')
    metadata = json.loads(manifest.read_text())
    layout = preview.assets()
    if (not metadata.get('layout_approved') or not preview.layout_approved(layout) or
            metadata['verse'] != json.loads(row['verse_json']) or metadata['asset_hashes'] != layout['files']):
        raise ValueError('O texto ou o layout do Story mudou.')
    return image


def enable_simulation(store, account_id, *, confirmed=False):
    if confirmed is not True or not isinstance(account_id, str) or not account_id.isdecimal():
        raise ValueError('Confirme uma conta de teste para a simulação.')
    with store.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        policy = conn.execute('SELECT * FROM policy WHERE id=1').fetchone()
        if policy['mode'] != 'simulation':
            raise ValueError('Não misture simulação e publicação real.')
        previous = policy['account_id']
        if previous and previous != account_id:
            raise ValueError('A conta autorizada deste armazenamento não pode ser substituída.')
        conn.execute("UPDATE policy SET enabled=1,account_id=? WHERE id=1 AND mode='simulation'", (account_id,))


def configure_live(store, account_id, *, confirmed=False):
    if confirmed is not True or not isinstance(account_id, str) or not account_id.isdecimal() or int(account_id) <= 0:
        raise ValueError('Confirme a conta empresarial de destino.')
    with store.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        policy = conn.execute('SELECT * FROM policy WHERE id=1').fetchone()
        if (policy['enabled'] or policy['account_id'] or
                conn.execute('SELECT 1 FROM slots LIMIT 1').fetchone() or
                conn.execute('SELECT 1 FROM batches LIMIT 1').fetchone()):
            raise ValueError('Use um armazenamento novo; não promova uma fila de simulação.')
        conn.execute("UPDATE policy SET mode='live',account_id=?,enabled=0 WHERE id=1", (account_id,))
        conn.execute('INSERT INTO policy_events(action,account_id,created_at) VALUES(?,?,?)',
                     ('configure_live_disabled', account_id, stamp(local_now())))


def enable_live(store, *, confirmed=False, now=None):
    if confirmed is not True:
        raise ValueError('Confirme explicitamente a ativação dos Stories reais.')
    now = local_now(now)
    with store.connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        policy = conn.execute('SELECT * FROM policy WHERE id=1').fetchone()
        rows = conn.execute("SELECT * FROM slots WHERE state IN ('queued','staged','processing','sending','review')").fetchall()
        if policy['mode'] != 'live' or not policy['account_id'] or not rows:
            raise ValueError('Prepare e revise uma fila exclusiva para a conta real.')
        for row in rows:
            if row['state'] != 'queued' or row['due_at'] < stamp(now) + MIN_NOTICE:
                raise ValueError('Há horário vencido ou envio que exige conferência antes de ativar.')
            verify_image(store, row)
        conn.execute('UPDATE policy SET enabled=1 WHERE id=1')
        conn.execute('INSERT INTO policy_events(action,account_id,created_at) VALUES(?,?,?)',
                     ('enable_live', policy['account_id'], stamp(now)))


def pause(store):
    """Interrompe os próximos acionamentos; não desfaz envio já iniciado."""
    with store.connect() as conn:
        conn.execute('UPDATE policy SET enabled=0 WHERE id=1')
        conn.execute('INSERT INTO policy_events(action,account_id,created_at) SELECT ?,account_id,? FROM policy WHERE id=1',
                     ('pause', stamp(local_now())))


def tick(store, transport=None, *, now=None):
    """Processa uma etapa; modo real nunca usa a fila/transportes de simulação."""
    now = local_now(now)
    with store.connect() as conn:
        policy = conn.execute('SELECT * FROM policy WHERE id=1').fetchone()
        if not policy['enabled']:
            return {'status': 'disabled'}
        simulation = getattr(transport, 'simulation', None)
        if (type(simulation) is not bool or policy['mode'] != ('simulation' if simulation else 'live') or
                (not simulation and (getattr(transport, 'account_id', None) != policy['account_id'] or
                                     getattr(transport, 'requires_staging', None) is not True))):
            return {'status': 'unconfigured'}
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("UPDATE slots SET state='review',error='Resultado incerto; não reenviar.' WHERE state='sending' AND claimed_at<=?", (stamp(now)-LEASE,))
        conn.execute("UPDATE attempts SET outcome='review' WHERE outcome='pending' AND slot_id IN (SELECT id FROM slots WHERE state='review')")
        row = conn.execute("""SELECT * FROM slots WHERE
            (state='processing' AND due_at<=?) OR
            (state IN ('queued','staged') AND due_at<=?)
            ORDER BY due_at LIMIT 1""", (stamp(now), stamp(now) + (0 if simulation else PREPARE_AHEAD))).fetchone()
        if row is None:
            pending = conn.execute("SELECT 1 FROM slots WHERE state='sending'").fetchone()
            if pending:
                return {'status': 'busy'}
        else:
            if stamp(now) - row['due_at'] > MAX_LATENESS:
                conn.execute("UPDATE slots SET state='review',error='Horário vencido; requer conferência.' WHERE id=?", (row['id'],))
                return {'status': 'expired'}
            claim = secrets.token_hex(16)
            phase = ('publish' if row['state'] == 'processing' else
                     'stage' if row['state'] == 'queued' and not simulation else 'create')
            conn.execute("UPDATE slots SET state='sending',claim=?,claimed_at=? WHERE id=?", (claim, stamp(now), row['id']))
            conn.execute('INSERT INTO attempts(id,slot_id,phase,created_at) VALUES(?,?,?,?)', (claim, row['id'], phase, stamp(now)))
    if row is None:
        batch = prepare_batch(store, now=now)
        if batch['created']:
            queue_batch(store, batch['batch_id'], confirmed=True, now=now)
            return {'status': 'batch_prepared', 'batch_id': batch['batch_id']}
        return {'status': 'idle'}
    try:
        image = verify_image(store, row)
        account = transport.verify_account(policy['account_id'])
        if (account.get('id') != policy['account_id'] or account.get('username') != ACCOUNT or
                account.get('account_type') != 'BUSINESS' or account.get('stories_allowed') is not True):
            raise ValueError('A conta de teste não corresponde ao Instagram empresarial autorizado.')
        photo = row['staged_photo']
        if phase == 'stage':
            photo = transport.stage_image(image).get('id')
            if not isinstance(photo, str) or not photo:
                raise ValueError('Imagem de apoio sem confirmação; conferir antes de repetir.')
            state, container, remote = 'staged', '', ''
        elif phase == 'create':
            options = {'media_type': 'STORIES'}
            if not simulation:
                options['staged_photo'] = photo
            result = transport.create_container(image, **options)
            container = result.get('id')
            if not isinstance(container, str) or not container:
                raise ValueError('Contêiner sem confirmação; conferir antes de repetir.')
            state, remote = 'processing', ''
        else:
            container = row['container']
            status = transport.container_status(container)
            if status == 'IN_PROGRESS':
                state, remote = 'processing', ''
            elif status == 'FINISHED':
                remote = transport.publish(container).get('id')
                if not isinstance(remote, str) or not remote:
                    raise ValueError('Envio sem confirmação; conferir antes de repetir.')
                state = 'simulated' if simulation else 'published'
            else:
                raise ValueError('O processamento não foi confirmado.')
    except Exception:
        with store.connect() as conn:
            conn.execute("UPDATE slots SET state='review',error='Falha ou resultado incerto no Story; conferir antes de repetir.' WHERE id=? AND claim=?", (row['id'], claim))
            conn.execute("UPDATE attempts SET outcome='review' WHERE id=?", (claim,))
        return {'status': 'review'}
    with store.connect() as conn:
        changed = conn.execute("UPDATE slots SET state=?,container=?,remote_id=?,staged_photo=?,claim='',claimed_at=NULL WHERE id=? AND claim=? AND state='sending'", (state, container, remote, photo, row['id'], claim))
        if changed.rowcount != 1:
            state = 'review'
        conn.execute('UPDATE attempts SET outcome=? WHERE id=?', (state, claim))
    return {'status': state}


def main():
    parser = argparse.ArgumentParser(description='Gestão isolada de Stories; ativação real exige confirmação.')
    parser.add_argument('--directory', required=True, type=Path, help='Diretório exclusivo dos Stories.')
    parser.add_argument('--account')
    parser.add_argument('--batch')
    parser.add_argument('--confirm', action='store_true')
    parser.add_argument('action', choices=['prepare', 'agenda', 'configure-live', 'queue', 'enable-live', 'pause'])
    args = parser.parse_args()
    store = Store(args.directory)
    store.initialize()
    if args.action == 'prepare':
        prepare_batch(store)
    elif args.action == 'configure-live':
        configure_live(store, args.account, confirmed=args.confirm)
    elif args.action == 'queue':
        queue_batch(store, args.batch, confirmed=args.confirm)
    elif args.action == 'enable-live':
        enable_live(store, confirmed=args.confirm)
    elif args.action == 'pause':
        pause(store)
    with store.connect() as conn:
        policy = conn.execute('SELECT * FROM policy WHERE id=1').fetchone()
    print(json.dumps({'environment': policy['mode'], 'publishing_enabled': bool(policy['mode'] == 'live' and policy['enabled']),
                      'items': store.agenda()}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
