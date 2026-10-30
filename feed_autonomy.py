"""Rotina autorizada de feeds: indexação local, rotação e fila persistente."""
import csv
from datetime import datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import time
import unicodedata
import zipfile

from PIL import Image, ImageOps
import drive_source as drive
import feed_composer as composer
import meta
import scheduling
import product_scene

SETTINGS = 'feed-automation.json'
OCR_DATA = Path(__file__).parent / 'design_assets' / 'ocr'
ACCOUNT = 'arte.no.altar'


def initialize(conn):
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS feed_batches (
        id TEXT PRIMARY KEY, account_id TEXT NOT NULL, first_day TEXT NOT NULL,
        last_day TEXT NOT NULL, policy TEXT NOT NULL, created_at INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS feed_models (
        file_id TEXT PRIMARY KEY, version TEXT NOT NULL, active INTEGER NOT NULL,
        state TEXT NOT NULL, theme TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL DEFAULT '',
        model_key TEXT NOT NULL DEFAULT '', visual TEXT NOT NULL DEFAULT '');
      CREATE TABLE IF NOT EXISTS feed_auto_slots (
        slot TEXT PRIMARY KEY, due_at INTEGER NOT NULL, policy TEXT NOT NULL,
        account_id TEXT NOT NULL, file_id TEXT NOT NULL, model_key TEXT NOT NULL,
        cycle INTEGER NOT NULL, theme TEXT NOT NULL, request_id TEXT UNIQUE NOT NULL,
        state TEXT NOT NULL, post_id INTEGER);
      CREATE TABLE IF NOT EXISTS feed_auto_runtime (
        id INTEGER PRIMARY KEY CHECK(id=1), lease TEXT NOT NULL DEFAULT '',
        lease_until INTEGER NOT NULL DEFAULT 0, last_tick INTEGER NOT NULL DEFAULT 0,
        state TEXT NOT NULL DEFAULT 'disabled');
    ''')
    if 'batch_id' not in {row[1] for row in conn.execute('PRAGMA table_info(feed_auto_slots)')}:
        conn.execute("ALTER TABLE feed_auto_slots ADD COLUMN batch_id TEXT NOT NULL DEFAULT ''")


def rules_hash():
    digest = hashlib.sha256(product_scene.VERSION.encode())
    for path in product_scene.asset_files():
        digest.update(str(path.relative_to(product_scene.ASSETS)).encode()+b'\0')
        digest.update(path.read_bytes())
    digest.update(json.dumps(composer.PHRASES, ensure_ascii=False).encode())
    return digest.hexdigest()


def engine():
    binary = shutil.which('tesseract')
    if not binary or not (OCR_DATA / 'por.traineddata').is_file():
        raise ValueError('OCR local indisponível. Verifique Tesseract na hospedagem; não é necessária API paga.')
    return binary


def clean(text):
    return re.sub(r'[^a-z0-9]', '', ''.join(c for c in unicodedata.normalize('NFKD', text.lower())
                                          if not unicodedata.combining(c)))


def detect_theme(words, height):
    scores = {}
    for word in words:
        try:
            confidence, size = float(word['conf']), int(word['height'])
        except (KeyError, ValueError, TypeError):
            continue
        if confidence < 65 or size < max(20, height * .025):
            continue
        token = clean(word.get('text', ''))
        theme = next((t for t, values in {
            'dizimos': ('dizimo', 'dizimos'), 'ofertas': ('oferta', 'ofertas'),
            'primicias': ('primicia', 'primicias'), 'santa_ceia': ('ceia',)
        }.items() if token in values), None)
        if theme:
            scores[theme] = max(scores.get(theme, 0), size * confidence)
    ranked = sorted(scores, key=scores.get, reverse=True)
    if not ranked or len(ranked) > 1 and scores[ranked[0]] < scores[ranked[1]] * 1.7:
        return ''
    return ranked[0]


def recognize(raw):
    # As três amostras foram abertas e classificadas visualmente na configuração.
    # Guardam-se apenas hashes e temas, sem fotos, nomes ou IDs privados do Drive.
    verified = json.loads((Path(__file__).parent / 'design_assets' / 'feed' / 'verified_models.json').read_text())
    known = verified.get(hashlib.sha256(raw).hexdigest())
    if known in composer.PHRASES:
        return known
    binary = engine()
    source = composer.decode(raw)
    variants = [source, ImageOps.autocontrast(ImageOps.grayscale(source))]
    themes = set()
    deadline = time.monotonic() + 12
    for image in variants:
        image = ImageOps.contain(image, (1600, 1600))
        output = io.BytesIO()
        image.save(output, format='PNG')
        try:
            result = subprocess.run([binary, 'stdin', 'stdout', '--tessdata-dir', str(OCR_DATA),
                                     '-l', 'por', '--psm', '11', '-c', 'tessedit_create_tsv=1'],
                                    input=output.getvalue(), capture_output=True,
                                    timeout=max(.1, deadline-time.monotonic()), check=True,
                                    env=dict(os.environ, OMP_THREAD_LIMIT='1'))
        except subprocess.TimeoutExpired:
            break
        except (OSError, subprocess.CalledProcessError):
            raise ValueError('O leitor local não conseguiu analisar a imagem.') from None
        if len(result.stdout) > 1024 * 1024:
            break
        theme = detect_theme(csv.DictReader(io.StringIO(result.stdout.decode('utf-8', 'replace')), delimiter='\t'), image.height)
        if theme:
            themes.add(theme)
    return next(iter(themes)) if len(themes) == 1 else ''


def fingerprint(raw):
    image = composer.decode(raw)
    key = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
    # Duas escalas: aparência geral e região central. Similaridade não é identidade.
    hashes = []
    for view in (image, image.crop((image.width//5, image.height//5, image.width*4//5, image.height*4//5))):
        pixels = list(ImageOps.grayscale(view).resize((9, 8)).tobytes())
        value = 0
        for y in range(8):
            for x in range(8):
                value = (value << 1) | (pixels[y*9+x] > pixels[y*9+x+1])
        hashes.append(f'{value:016x}')
    return key, ''.join(hashes)


def policy(directory):
    if not (directory / SETTINGS).exists():
        return None
    result = drive.read_json(directory / SETTINGS)
    if result.get('enabled') is not True or result.get('layout_review_required'):
        return None
    if (result.get('rules_hash') != rules_hash() or result.get('username') != ACCOUNT or
            not isinstance(result.get('account_id'), str) or not result['account_id'].isdecimal() or
            result.get('timezone') != 'America/Sao_Paulo' or result.get('time') != '12:00' or
            result.get('days_ahead') != 3 or not re.fullmatch(r'[a-f0-9]{32}', result.get('id', ''))):
        raise ValueError('A política da rotina precisa ser atualizada antes de continuar.')
    return result


def enable(directory, *, approve_layout=False, preview=False):
    old = drive.read_json(directory / SETTINGS) if (directory / SETTINGS).exists() else {}
    if (old.get('layout_review_required') or old.get('batch_review_required')) and not approve_layout:
        raise ValueError('O layout automático foi rejeitado e precisa ser corrigido e aprovado antes da reativação.')
    product_scene.backend()
    product_scene.validate_assets([composer.phrase('generico', i) for i in range(15)])
    verification = meta.verify_accounts(directory)
    accounts = [a for a in verification['accounts'] if a['channel'] == 'Instagram'
                and a['name'].lstrip('@').casefold() == ACCOUNT and a.get('publishing_scope_granted')]
    if len(accounts) != 1:
        raise ValueError('A conta Instagram @arte.no.altar não foi confirmada com permissão de publicação.')
    identity = old.get('id') if old.get('rules_hash') == rules_hash() else None
    result = {'enabled': True, 'id': identity or secrets.token_hex(16),
              'username': ACCOUNT, 'account_id': accounts[0]['id'], 'channel': 'Instagram',
              'timezone': 'America/Sao_Paulo', 'time': '12:00', 'days_ahead': 3,
              'rules_hash': rules_hash(), 'authorized_at': int(time.time()),
              'cadence': 'batch3', 'mode': 'preview' if preview else 'publish',
              'layout_review_required': False, 'batch_review_required': preview,
              'authorization': 'Rotina diária autorizada pelo proprietário para os layouts e textos aprovados.'}
    drive.write_private(directory / SETTINGS, result)
    return result


def pause_for_layout_review(connect, directory):
    settings = drive.read_json(directory / SETTINGS) if (directory / SETTINGS).exists() else {}
    drive.write_private(directory / SETTINGS, settings | {'enabled': False, 'layout_review_required': True})
    cancelled = 0
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        rows = conn.execute('''SELECT s.* FROM post_schedule s
            JOIN feed_compositions c ON c.post_id=s.post_id
            JOIN feed_auto_slots a ON a.request_id=c.request_id
            WHERE s.state='queued' ''').fetchall()
        for row in rows:
            scheduling.cancel(conn, {'id': row['post_id'], 'revision': row['revision'],
                                    'expected_due_at': row['due_at']}, begin=False)
            conn.execute("UPDATE feed_auto_slots SET state='paused' WHERE request_id IN (SELECT request_id FROM feed_compositions WHERE post_id=?)", (row['post_id'],))
            cancelled += 1
        in_flight = conn.execute('''SELECT COUNT(*) FROM post_schedule s
            JOIN feed_compositions c ON c.post_id=s.post_id
            JOIN feed_auto_slots a ON a.request_id=c.request_id
            WHERE s.state IN ('running','processing')''').fetchone()[0]
    return {'cancelled': cancelled, 'in_flight': in_flight}


def sync_catalog(connect, directory, client):
    cache = directory / drive.CATALOG_FILE
    with connect() as conn:
        ready = {r[0] for r in conn.execute("SELECT model_key FROM feed_models WHERE active=1 AND state='ready'")}
        cycle = conn.execute('SELECT MAX(cycle) FROM feed_auto_slots').fetchone()[0] or 1
        used = {r[0] for r in conn.execute('SELECT model_key FROM feed_auto_slots WHERE cycle=?', (cycle,))}
        if cycle == 1:
            used.update(r[0] for r in conn.execute('''SELECT m.model_key FROM feed_models m
                JOIN feed_compositions c ON c.file_id=m.file_id AND c.source_sha256=m.sha256
                WHERE c.request_id NOT LIKE 'auto-feed-%' '''))
    # Consultar novos modelos antes de afirmar que o ciclo terminou.
    must_refresh = bool(ready and ready.issubset(used))
    if not must_refresh and cache.exists() and time.time() - cache.stat().st_mtime < 21600:
        catalog = drive.read_json(cache, drive.MAX_JSON)
        config = drive.read_json(directory / drive.CONFIG_FILE)
        if catalog.get('folder_id') != config.get('folder_id') or catalog.get('complete') is not True:
            catalog = drive.inspect(directory, client)
    else:
        catalog = drive.inspect(directory, client)
    files = [f for f in catalog['files'] if f['mimeType'] in ('image/png', 'image/jpeg')]
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('UPDATE feed_models SET active=0')
        migrated = []
        for f in files:
            identity = [f.get(k) for k in ('md5Checksum', 'modifiedTime', 'size')]
            version = json.dumps(identity + ['generic-v1'])
            old = conn.execute('SELECT * FROM feed_models WHERE file_id=?', (f['id'],)).fetchone()
            if old and old['version'] == version:
                conn.execute('UPDATE feed_models SET active=1 WHERE file_id=?', (f['id'],))
            elif (old and old['version'] == json.dumps(identity) and
                  old['sha256'] and old['model_key'] and old['visual']):
                # Reaproveitar a conferência do arquivo antigo. OCR incerto não é
                # mais motivo para retenção; a comparação de duplicações continua.
                conn.execute("UPDATE feed_models SET active=1,version=?,theme='generico',state='ready' WHERE file_id=?", (version, f['id']))
                migrated.append(f['id'])
            else:
                conn.execute('''INSERT OR REPLACE INTO feed_models(file_id,version,active,state)
                                VALUES(?,?,1,'pending')''', (f['id'], version))
        if migrated:
            indexed = conn.execute("SELECT * FROM feed_models WHERE active=1 AND visual!=''").fetchall()
            for item in indexed:
                if item['file_id'] not in migrated:
                    continue
                for other in indexed:
                    if item['model_key'] != other['model_key'] and (int(item['visual'], 16) ^ int(other['visual'], 16)).bit_count() <= 12:
                        conn.execute("UPDATE feed_models SET state='review' WHERE file_id IN (?,?)", (item['file_id'], other['file_id']))
            conn.execute('''UPDATE feed_auto_slots SET theme='generico'
                WHERE state='reserved' AND NOT EXISTS
                    (SELECT 1 FROM feed_compositions c WHERE c.request_id=feed_auto_slots.request_id)
                  AND file_id IN (SELECT file_id FROM feed_models WHERE active=1 AND theme='generico')''')
    return files


def index_one(connect, files, client, recognizer=None, *, file_id=None):
    with connect() as conn:
        row = conn.execute("SELECT * FROM feed_models WHERE active=1 AND state='pending' AND (? IS NULL OR file_id=?) ORDER BY file_id LIMIT 1", (file_id, file_id)).fetchone()
    if not row:
        return False
    item = next(f for f in files if f['id'] == row['file_id'])
    raw = client.download_image(item)
    # A execução normal não lê palavras do envelope. O argumento opcional existe
    # apenas para compatibilidade com testes e ferramentas antigas de revisão.
    theme = recognizer(raw) if recognizer is not None else 'generico'
    key, visual = fingerprint(raw)
    state = 'ready' if theme in composer.PHRASES else 'review'
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for other in conn.execute("SELECT * FROM feed_models WHERE active=1 AND state IN ('ready','review') AND file_id!=?", (row['file_id'],)).fetchall():
            if other['model_key'] == key and other['theme'] and theme and other['theme'] != theme:
                state = 'review'
                conn.execute("UPDATE feed_models SET state='review' WHERE model_key=?", (key,))
            elif other['visual'] and other['model_key'] != key and (int(visual, 16) ^ int(other['visual'], 16)).bit_count() <= 12:
                # Sem confirmação visual, não afirmar que duas fotos são o mesmo modelo.
                state = 'review'
                conn.execute("UPDATE feed_models SET state='review' WHERE file_id=?", (other['file_id'],))
        conn.execute('''UPDATE feed_models SET state=?,theme=?,sha256=?,model_key=?,visual=?
                        WHERE file_id=? AND version=?''',
                     (state, theme, hashlib.sha256(raw).hexdigest(), key, visual, row['file_id'], row['version']))
    return True


def _reserve(connect, rules, now):
    local = datetime.fromtimestamp(now, scheduling.ZONE)
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        pending = conn.execute("SELECT * FROM feed_auto_slots WHERE state='reserved' ORDER BY due_at LIMIT 1").fetchone()
        if pending:
            return dict(pending)
        for offset in range(4):
            day = local.date() + timedelta(days=offset)
            due = int(datetime.combine(day, datetime.min.time(), scheduling.ZONE).replace(hour=12).timestamp())
            if due < now + 120 or due > now + 3*86400:
                continue
            slot = f"{rules['account_id']}:{day.isoformat()}"
            if conn.execute('SELECT 1 FROM feed_auto_slots WHERE slot=?', (slot,)).fetchone():
                continue
            # Se já houver conteúdo desse dia, respeitar seu horário e usar a próxima janela.
            for delta in range(0, 121, 15):
                target = due + delta*60
                busy = conn.execute('''SELECT 1 FROM post_schedule s JOIN posts p ON p.id=s.post_id
                    WHERE s.state IN ('queued','running','processing') AND p.account_id=? AND p.channel='Instagram'
                    AND s.due_at>=? AND s.due_at<?''', (rules['account_id'], target, target+60)).fetchone()
                if not busy:
                    due = target
                    break
            else:
                continue
            cycle = conn.execute('SELECT MAX(cycle) FROM feed_auto_slots').fetchone()[0] or 1
            used = {r[0] for r in conn.execute('SELECT model_key FROM feed_auto_slots WHERE cycle=?', (cycle,))}
            if cycle == 1:
                # Montagens manuais já criadas também contam como uso inicial.
                used.update(r[0] for r in conn.execute('''SELECT m.model_key FROM feed_models m
                    JOIN feed_compositions c ON c.file_id=m.file_id AND c.source_sha256=m.sha256
                    WHERE c.request_id NOT LIKE 'auto-feed-%' '''))
            candidates = [dict(r) for r in conn.execute("SELECT * FROM feed_models WHERE active=1 AND state='ready'") if r['model_key'] not in used]
            if not candidates:
                unresolved = conn.execute("SELECT COUNT(*) FROM feed_models WHERE active=1 AND state!='ready'").fetchone()[0]
                if unresolved:
                    return None
                cycle += 1
                candidates = [dict(r) for r in conn.execute("SELECT * FROM feed_models WHERE active=1 AND state='ready'")]
                previous = conn.execute('SELECT model_key FROM feed_auto_slots ORDER BY rowid DESC LIMIT 1').fetchone()
                if previous and len({r['model_key'] for r in candidates}) > 1:
                    candidates = [r for r in candidates if r['model_key'] != previous[0]]
            if not candidates:
                return None
            # Cada modelo tem uma chance; arquivos duplicados não aumentam sua probabilidade.
            unique = {r['model_key']: r for r in candidates}
            chosen = unique[secrets.choice(list(unique))]
            request_id = 'auto-feed-' + hashlib.sha256(slot.encode()).hexdigest()
            conn.execute('''INSERT INTO feed_auto_slots
                (slot,due_at,policy,account_id,file_id,model_key,cycle,theme,request_id,state,post_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,NULL)''',
                         (slot, due, rules['id'], rules['account_id'], chosen['file_id'], chosen['model_key'],
                          cycle, chosen['theme'], request_id, 'reserved'))
            return dict(conn.execute('SELECT * FROM feed_auto_slots WHERE slot=?', (slot,)).fetchone())
    return None


def _batch_days(connect, rules, now):
    local = datetime.fromtimestamp(now, scheduling.ZONE)
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        latest = conn.execute('SELECT * FROM feed_batches WHERE account_id=? AND policy=? ORDER BY rowid DESC LIMIT 1', (rules['account_id'], rules['id'])).fetchone()
        if latest:
            count = conn.execute('SELECT COUNT(*) FROM feed_auto_slots WHERE batch_id=?', (latest['id'],)).fetchone()[0]
            if count < 3:
                return dict(latest)
            if rules.get('mode') == 'preview' or local.date().isoformat() < latest['last_day']:
                return None
            first = datetime.fromisoformat(latest['last_day']).date()+timedelta(days=1)
        else:
            first = local.date()
        earliest = local.date() + timedelta(days=int(local.hour >= 12 or (local.hour == 11 and local.minute >= 58)))
        first = max(first, earliest)
        identity = secrets.token_hex(16)
        conn.execute('INSERT INTO feed_batches VALUES(?,?,?,?,?,?)', (identity, rules['account_id'], first.isoformat(),
                     (first+timedelta(days=2)).isoformat(), rules['id'], now))
        return dict(conn.execute('SELECT * FROM feed_batches WHERE id=?', (identity,)).fetchone())


def _reserve_batch(connect, rules, batch, now):
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        pending = conn.execute("SELECT * FROM feed_auto_slots WHERE batch_id=? AND state='reserved' LIMIT 1", (batch['id'],)).fetchone()
        if pending:
            return dict(pending)
        for offset in range(3):
            day = datetime.fromisoformat(batch['first_day']).date()+timedelta(days=offset)
            slot = f"{rules['account_id']}:{day.isoformat()}:{batch['id']}"
            if conn.execute('SELECT 1 FROM feed_auto_slots WHERE slot=?', (slot,)).fetchone():
                continue
            cycle = conn.execute('SELECT MAX(cycle) FROM feed_auto_slots').fetchone()[0] or 1
            used = {r[0] for r in conn.execute('SELECT model_key FROM feed_auto_slots WHERE cycle=?', (cycle,))}
            if cycle == 1:
                used.update(r[0] for r in conn.execute('''SELECT m.model_key FROM feed_models m JOIN feed_compositions c
                    ON c.file_id=m.file_id AND c.source_sha256=m.sha256 WHERE c.request_id NOT LIKE 'auto-feed-%' '''))
            ready = [dict(r) for r in conn.execute("SELECT * FROM feed_models WHERE active=1 AND state='ready'")]
            candidates = [r for r in ready if r['model_key'] not in used]
            if not candidates and ready:
                unresolved = conn.execute("SELECT COUNT(*) FROM feed_models WHERE active=1 AND state!='ready'").fetchone()[0]
                if unresolved:
                    return None
                cycle += 1
                candidates = ready
                last = conn.execute('SELECT model_key FROM feed_auto_slots ORDER BY rowid DESC LIMIT 1').fetchone()
                if last and len({r['model_key'] for r in candidates}) > 1:
                    candidates = [r for r in candidates if r['model_key'] != last[0]]
            if not candidates:
                return None
            hints = json.loads((product_scene.ASSETS/'cutout-hints.json').read_text())
            known = [r for r in candidates if r['sha256'] in hints]
            unique = {r['model_key']: r for r in known or candidates}
            model = unique[secrets.choice(list(unique))]
            due = int(datetime.combine(day, datetime.min.time(), scheduling.ZONE).replace(hour=12).timestamp())
            request = 'auto-feed-'+hashlib.sha256(slot.encode()).hexdigest()
            conn.execute('''INSERT INTO feed_auto_slots
                (slot,due_at,policy,account_id,file_id,model_key,cycle,theme,request_id,state,post_id,batch_id)
                VALUES(?,?,?,?,?,?,?,'generico',?,'reserved',NULL,?)''',
                (slot, due, rules['id'], rules['account_id'], model['file_id'], model['model_key'], cycle, request, batch['id']))
            return dict(conn.execute('SELECT * FROM feed_auto_slots WHERE slot=?', (slot,)).fetchone())
    return None


def _produce(connect, directory, rules, slot, client):
    with connect() as conn:
        model = conn.execute('SELECT * FROM feed_models WHERE file_id=?', (slot['file_id'],)).fetchone()
    if (not model or not model['active'] or model['state'] != 'ready' or
            model['model_key'] != slot['model_key'] or model['theme'] != slot['theme'] or
            slot['policy'] != rules['id'] or slot['account_id'] != rules['account_id']):
        with connect() as conn:
            conn.execute("UPDATE feed_auto_slots SET state='held' WHERE slot=?", (slot['slot'],))
        raise ValueError('Modelo ou política mudou durante a preparação.')
    try:
        result = composer.compose(connect, directory, {'theme': slot['theme'], 'file_id': slot['file_id'],
                              'request_id': slot['request_id'], 'channel': 'Instagram'}, client,
                              expected_sha256=model['sha256'])
    except composer.SourceChanged:
        with connect() as conn:
            conn.execute("UPDATE feed_models SET state='pending' WHERE file_id=?", (slot['file_id'],))
            conn.execute("UPDATE feed_auto_slots SET state='held' WHERE slot=?", (slot['slot'],))
        raise
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        post = conn.execute('SELECT * FROM posts WHERE id=?', (result['post_id'],)).fetchone()
        schedule = conn.execute('SELECT * FROM post_schedule WHERE post_id=?', (post['id'],)).fetchone()
        if schedule or post['publish_status'] != 'draft' or post['revision'] != 0:
            state = 'queued' if schedule and schedule['state'] == 'queued' else 'retained'
        elif rules.get('mode') == 'preview':
            conn.execute("UPDATE posts SET account_id=?,source='Prévia de lote · revisar' WHERE id=?", (rules['account_id'], post['id']))
            state = 'draft'
        elif slot['due_at'] < time.time() + 120:
            state = 'expired'
        else:
            due = slot['due_at']
            # Conferir de novo dentro da transação: pode ter entrado outro agendamento.
            for delta in range(0, 121, 15):
                target = due + delta*60
                if target > int(datetime.fromtimestamp(due, scheduling.ZONE).replace(hour=14, minute=0, second=0).timestamp()):
                    continue
                occupied = conn.execute('''SELECT 1 FROM post_schedule s JOIN posts p ON p.id=s.post_id
                    WHERE s.state IN ('queued','running','processing') AND p.account_id=?
                      AND p.channel='Instagram' AND s.due_at>=? AND s.due_at<? AND p.id!=?''',
                    (rules['account_id'], target, target+60, post['id'])).fetchone()
                if not occupied:
                    due = target
                    break
            else:
                raise ValueError('As janelas deste dia foram ocupadas durante a montagem.')
            conn.execute('UPDATE feed_auto_slots SET due_at=? WHERE slot=?', (due, slot['slot']))
            conn.execute("UPDATE posts SET account_id=?,source='Rotina diária autorizada' WHERE id=?", (rules['account_id'], post['id']))
            # Autorização é da política persistida, não uma confirmação humana inventada.
            scheduling.save_automatic(conn, directory, post_id=post['id'], revision=post['revision'],
                                      due_at=due, policy_id=rules['id'])
            state = 'queued'
        conn.execute('UPDATE feed_auto_slots SET post_id=?,state=? WHERE slot=?', (post['id'], state, slot['slot']))
    return 'prepared'


def tick(connect, directory, client=None, recognizer=None):
    rules = policy(directory)
    if not rules:
        return 'disabled'
    # O mesmo destino confirmado na ativação; nunca escolher outra conta por conveniência.
    accounts = meta.status(directory).get('accounts', [])
    if not any(a['channel'] == 'Instagram' and a['id'] == rules['account_id'] and
               a['name'].lstrip('@').casefold() == ACCOUNT and a.get('publishing_scope_granted') for a in accounts):
        raise ValueError('Reconecte a conta autorizada antes de continuar a rotina.')
    now, lease = int(time.time()), secrets.token_hex(16)
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        runtime = conn.execute('SELECT * FROM feed_auto_runtime WHERE id=1').fetchone()
        if runtime and runtime['lease_until'] > now:
            return 'busy'
        conn.execute("INSERT OR REPLACE INTO feed_auto_runtime VALUES(1,?,?,?,'working')", (lease, now+600, now))
    state = 'error'
    try:
        if rules.get('cadence') == 'batch3' and rules.get('mode') != 'preview':
            with connect() as conn:
                draft = conn.execute("SELECT * FROM feed_auto_slots WHERE policy=? AND account_id=? AND state='draft' ORDER BY due_at LIMIT 1", (rules['id'], rules['account_id'])).fetchone()
                if draft:
                    conn.execute("UPDATE feed_auto_slots SET state='reserved' WHERE slot=?", (draft['slot'],))
            if draft:
                client = client or drive.DriveClient(drive.credentials(directory))
                state = _produce(connect, directory, rules, dict(draft), client)
                return state
        batch = _batch_days(connect, rules, now) if rules.get('cadence') == 'batch3' else None
        if rules.get('cadence') == 'batch3' and batch is None:
            state = 'waiting'
            return state
        client = client or drive.DriveClient(drive.credentials(directory))
        files = sync_catalog(connect, directory, client)
        if batch is not None:
            slot = _reserve_batch(connect, rules, batch, now)
            if not slot:
                with connect() as conn:
                    choices = conn.execute("SELECT file_id FROM feed_models WHERE active=1 AND state='pending'").fetchall()
                if choices:
                    # Só conferir a próxima candidata, sem percorrer toda a pasta.
                    selected = secrets.choice(choices)['file_id']
                    index_one(connect, files, client, recognizer, file_id=selected)
                    slot = _reserve_batch(connect, rules, batch, now)
            if slot:
                try:
                    state = _produce(connect, directory, rules, slot, client)
                except product_scene.CutoutError:
                    with connect() as conn:
                        conn.execute('BEGIN IMMEDIATE')
                        if not conn.execute('SELECT 1 FROM feed_compositions WHERE request_id=?', (slot['request_id'],)).fetchone():
                            conn.execute("UPDATE feed_models SET state='review' WHERE file_id=?", (slot['file_id'],))
                            conn.execute("DELETE FROM feed_auto_slots WHERE slot=? AND state='reserved'", (slot['slot'],))
                    state = 'cutout_review'
            else:
                state = 'indexing' if choices else 'waiting'
        elif index_one(connect, files, client, recognizer):
            state = 'indexing'
        else:
            slot = _reserve(connect, rules, now)
            state = _produce(connect, directory, rules, slot, client) if slot else 'waiting'
        return state
    finally:
        with connect() as conn:
            conn.execute("UPDATE feed_auto_runtime SET lease='',lease_until=0,state=? WHERE id=1 AND lease=?", (state, lease))


def status(conn, directory):
    enabled = False
    settings = None
    try:
        settings = policy(directory)
        enabled = bool(settings)
    except (ValueError, OSError):
        pass
    counts = {r[0]: r[1] for r in conn.execute('SELECT state,COUNT(*) FROM feed_models WHERE active=1 GROUP BY state')}
    runtime = conn.execute('SELECT state,last_tick FROM feed_auto_runtime WHERE id=1').fetchone()
    return {'enabled': enabled, 'models': counts, 'state': runtime['state'] if runtime else 'disabled',
            'last_tick': runtime['last_tick'] if runtime else None,
            'mode': settings.get('mode', 'publish') if settings else 'disabled',
            'cadence': settings.get('cadence', 'daily') if settings else 'batch3',
            'account': '@'+ACCOUNT, 'time': '12:00', 'timezone': 'America/Sao_Paulo'}


def export_review(connect, directory, client=None):
    from PIL import ImageDraw
    client = client or drive.DriveClient(drive.credentials(directory))
    catalog = drive.inspect(directory, client)
    entries = {f['id']: f for f in catalog['files']}
    with connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM feed_models WHERE active=1 AND state='review' ORDER BY file_id")]
    if len(rows) > 100:
        raise ValueError('O pacote de revisão aceita até 100 imagens.')
    destination = directory / 'revisao-modelos.zip'
    temporary = directory / ('.review-'+secrets.token_hex(8)+'.zip')
    metadata = {'models': {}, 'note': 'Possíveis duplicações para revisão visual. Frases genéricas; não contém credenciais.'}
    try:
        with zipfile.ZipFile(temporary, 'x') as archive:
            for start in range(0, len(rows), 8):
                page = Image.new('RGB', (1200, 2000), 'white')
                draw = ImageDraw.Draw(page)
                for offset, row in enumerate(rows[start:start+8]):
                    item = entries.get(row['file_id'])
                    if not item:
                        raise ValueError('Catálogo mudou durante a revisão. Atualize o índice.')
                    raw = client.download_image(item)
                    if hashlib.sha256(raw).hexdigest() != row['sha256']:
                        raise ValueError('Um original mudou. Reanalise antes de exportar.')
                    image = ImageOps.contain(composer.decode(raw), (590, 440))
                    x, y = (offset % 2)*600, (offset//2)*500
                    page.paste(image, (x+(600-image.width)//2, y+45))
                    draw.text((x+12, y+10), f'{start+offset+1:02d} · {row["file_id"]}',
                              font=composer.font(16), fill='black')
                    metadata['models'][row['file_id']] = {'sha256': row['sha256'], 'theme': 'generico', 'same_model_as': ''}
                output = io.BytesIO()
                page.save(output, format='JPEG', quality=92)
                archive.writestr(f'pagina-{start//8+1:02d}.jpg', output.getvalue())
            archive.writestr('classificacao.json', json.dumps(metadata, ensure_ascii=False, indent=2))
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def import_review(connect, directory, path):
    data = drive.read_json(Path(path), drive.MAX_JSON).get('models')
    if not isinstance(data, dict) or len(data) > 100:
        raise ValueError('Classificação inválida.')
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        # Conferir todos os hashes antes de aplicar qualquer alteração.
        groups = {}
        for file_id, value in data.items():
            row = conn.execute('SELECT * FROM feed_models WHERE file_id=? AND active=1', (file_id,)).fetchone()
            if (not isinstance(value, dict) or not row or row['sha256'] != value.get('sha256')
                    or row['state'] not in ('ready', 'review') or not re.fullmatch(r'[a-f0-9]{64}', row['sha256'])):
                raise ValueError('A classificação não corresponde aos originais atuais.')
            if value.get('theme') not in composer.PHRASES:
                raise ValueError('Use generico para a revisão atual ou um tema histórico válido.')
            groups.setdefault(row['model_key'], set()).add(value['theme'])
        if any(len(themes) > 1 for themes in groups.values()):
            raise ValueError('Fotos do mesmo modelo não podem ter temas diferentes.')
        for file_id, value in data.items():
            row = conn.execute('SELECT * FROM feed_models WHERE file_id=?', (file_id,)).fetchone()
            key = row['model_key']
            target = value.get('same_model_as')
            if target:
                other = conn.execute("SELECT * FROM feed_models WHERE file_id=? AND active=1", (target,)).fetchone()
                target_theme = data.get(target, {}).get('theme') if target in data else other['theme'] if other else None
                if not other or target_theme != value['theme']:
                    raise ValueError('O agrupamento precisa apontar para um modelo do mesmo tema.')
                # Históricos passam a apontar à identidade canônica, sem alterar posts/horários.
                canonical = other['model_key']
                conn.execute('UPDATE feed_auto_slots SET model_key=? WHERE model_key=?', (canonical, key))
                conn.execute('UPDATE feed_models SET model_key=? WHERE model_key=?', (canonical, key))
                key = canonical
            conn.execute("UPDATE feed_models SET state='ready',theme=? WHERE model_key=? AND active=1", (value['theme'], key))
    return len(data)


def main():
    import argparse
    import app
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['enable', 'prepare-batch', 'disable', 'pause-review', 'status', 'tick', 'export-review', 'import-review'])
    parser.add_argument('--approve-layout', action='store_true', help='Registrar aprovação explícita da nova ambientação')
    parser.add_argument('--file', help='JSON de classificação visual, sem credenciais')
    args = parser.parse_args()
    app.initialize()
    try:
        if args.command == 'enable':
            os.environ.setdefault('ARTENOALTAR_ORIGIN', 'https://artenoaltar.pythonanywhere.com')
            enable(app.DB.parent, approve_layout=args.approve_layout)
            print('Rotina ativada: Instagram @arte.no.altar, 1 feed/dia às 12h, São Paulo, em lotes de 3.')
            print('No último dia do lote serão preparadas as próximas 3 artes. Não será processada a pasta inteira.')
        elif args.command == 'prepare-batch':
            os.environ.setdefault('ARTENOALTAR_ORIGIN', 'https://artenoaltar.pythonanywhere.com')
            pause_for_layout_review(app.connect, app.DB.parent)
            enable(app.DB.parent, approve_layout=True, preview=True)
            print('Teste do lote: somente rascunhos, sem agendamento nem publicação.', flush=True)
            count = 0
            for _ in range(30):
                outcome = tick(app.connect, app.DB.parent)
                print(outcome, flush=True)
                with app.connect() as conn:
                    batch = conn.execute('SELECT id FROM feed_batches ORDER BY rowid DESC LIMIT 1').fetchone()
                    count = conn.execute("SELECT COUNT(*) FROM feed_auto_slots WHERE batch_id=? AND state='draft'", (batch['id'],)).fetchone()[0] if batch else 0
                if count >= 3 or outcome == 'waiting':
                    break
                if outcome == 'busy':
                    time.sleep(1)
            print('Rascunhos preparados:', count)
        elif args.command == 'disable':
            settings = drive.read_json(app.DB.parent / SETTINGS) if (app.DB.parent / SETTINGS).exists() else {}
            drive.write_private(app.DB.parent / SETTINGS, settings | {'enabled': False})
            print('Criação diária desativada. Agendamentos existentes foram preservados.')
        elif args.command == 'pause-review':
            result = pause_for_layout_review(app.connect, app.DB.parent)
            print('Rotina pausada para corrigir o layout. Agendamentos automáticos cancelados:', result['cancelled'])
            print('Outros agendamentos e todas as imagens foram preservados.')
            if result['in_flight']:
                print('Envios automáticos já iniciados, que exigem conferência na rede:', result['in_flight'])
        elif args.command == 'tick':
            print(tick(app.connect, app.DB.parent))
        elif args.command == 'export-review':
            print('Pacote privado para revisão:', export_review(app.connect, app.DB.parent))
        elif args.command == 'import-review':
            if not args.file:
                raise ValueError('Informe o JSON da classificação revisada.')
            print('Imagens classificadas:', import_review(app.connect, app.DB.parent, args.file))
        with app.connect() as conn:
            print(json.dumps(status(conn, app.DB.parent), ensure_ascii=False, indent=2))
    except (ValueError, OSError):
        raise SystemExit('Rotina indisponível. Confira conexão com Drive, conta Meta e política de ativação. Nenhuma credencial deve ser enviada ao chat.') from None


if __name__ == '__main__':
    main()
