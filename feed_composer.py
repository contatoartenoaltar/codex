"""Composição de feed com textos aprovados. Não agenda nem publica."""
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import time

from PIL import Image, ImageDraw, ImageOps

import drive_source
import publishing
from layout_preview import decode, font
from feed_reference_preview import lettering

TEMPLATE = Path(__file__).parent / 'design_assets' / 'feed' / 'template.jpg'
SIZE = (1080, 1350)
PHOTO_AREA = (0, 345, 1080, 1135)
# prefixo, tema em dourado, complemento: ordem de leitura da chamada aprovada.
PHRASES = {
    'dizimos': [('','Dízimos','com a sua identidade'), ('Seu','dízimo,','sua identidade'),
                ('Envelopes de','dízimo','personalizados')],
    'ofertas': [('Sua','oferta','merece destaque'), ('','Ofertas','com a sua identidade'),
                ('Envelopes de','ofertas','personalizados')],
    'primicias': [('','Primícias','com a sua identidade'), ('Personalize seus envelopes de','primícias',''),
                  ('Suas','primícias','em destaque')],
    'santa_ceia': [('','Comunhão','em cada detalhe'), ('','Santa Ceia','com identidade'),
                  ('Personalize seus envelopes de','Santa Ceia','')],
}
LABELS = dict(zip(PHRASES, ('Dízimos', 'Ofertas', 'Primícias', 'Santa Ceia')))


def phrase(theme, index):
    return ' '.join(part for part in PHRASES[theme][index] if part)


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS feed_compositions (
        request_id TEXT PRIMARY KEY, signature TEXT NOT NULL, theme TEXT NOT NULL,
        phrase_index INTEGER NOT NULL, cycle INTEGER NOT NULL, file_id TEXT NOT NULL,
        source_sha256 TEXT NOT NULL, post_id INTEGER NOT NULL, created_at INTEGER NOT NULL)''')


def render(original, theme, index):
    if theme not in PHRASES or type(index) is not int or not 0 <= index < 3:
        raise ValueError('Selecione um dos temas e chamadas aprovados.')
    source = decode(original)
    with Image.open(TEMPLATE) as template:
        canvas = template.convert('RGBA')
    prefix, topic, suffix = PHRASES[theme][index]
    if prefix:
        mask_width = font(59, weight=800).getlength(prefix)
        size = min(59, int(59 * 980 / max(mask_width, 1)))
        lettering(canvas, prefix, size, 22)
    # Mantém o tema grande e reserva uma altura fixa para não invadir a foto.
    face = font(150, weight=800)
    width = min(990, int(face.getlength(topic.upper())))
    lettering(canvas, topic.upper(), 150, 102 if prefix else 58,
              gold=True, target=(width, 128))
    if suffix:
        size = min(65, int(65 * 990 / max(font(65, weight=800).getlength(suffix), 1)))
        lettering(canvas, suffix, size, 258 if prefix else 235)
    # Sem crop, máscara ou texto sobre a fotografia original.
    photo = ImageOps.contain(source, (1080, 790), Image.Resampling.LANCZOS)
    x, y = (1080 - photo.width) // 2, 345 + (790 - photo.height) // 2
    canvas.paste(photo, (x, y))
    result = canvas.convert('RGB')
    box = (x, y, x + photo.width, y + photo.height)
    if result.crop(box).tobytes() != photo.tobytes():
        raise ValueError('A fotografia não foi preservada na composição.')
    return result, box


def models(directory, client=None):
    catalog = drive_source.inspect(directory, client)
    return {'models': [{k: f[k] for k in ('id', 'name')} for f in catalog['files']
                       if f['mimeType'] in ('image/png', 'image/jpeg')],
            'themes': LABELS, 'phrases': {t: [phrase(t, n) for n in range(3)] for t in PHRASES}}


def _existing(conn, request_id, signature):
    row = conn.execute('SELECT * FROM feed_compositions WHERE request_id=?', (request_id,)).fetchone()
    if row:
        if row['signature'] != signature:
            raise ValueError('Esta solicitação já foi usada para outro conteúdo.')
        post = conn.execute('SELECT publish_status FROM posts WHERE id=?', (row['post_id'],)).fetchone()
        if not post:
            raise ValueError('O rascunho desta solicitação foi excluído. Inicie uma nova montagem.')
        return {'post_id': row['post_id'], 'status': post['publish_status'], 'reused': True}


def compose(connect, directory, data, client=None):
    theme, file_id = data.get('theme'), drive_source.identifier(data.get('file_id'))
    request_id, channel = data.get('request_id'), data.get('channel', 'Instagram')
    if (not isinstance(theme, str) or theme not in PHRASES or
            not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', request_id)
            or channel not in ('Instagram', 'Facebook')):
        raise ValueError('Selecione tema, modelo e canal válidos.')
    signature = hashlib.sha256(json.dumps([theme, file_id, channel]).encode()).hexdigest()
    with connect() as conn:
        found = _existing(conn, request_id, signature)
        if found:
            return found
    client = client or drive_source.DriveClient(drive_source.credentials(directory))
    catalog = drive_source.inspect(directory, client)
    item = next((f for f in catalog['files'] if f['id'] == file_id), None)
    if not item or item['mimeType'] not in ('image/png', 'image/jpeg'):
        raise ValueError('Escolha um PNG ou JPEG da pasta de originais autorizada.')
    original = client.download_image(item)
    uploaded = None
    try:
        with connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            found = _existing(conn, request_id, signature)
            if found:
                return found
            rows = conn.execute('SELECT phrase_index,cycle FROM feed_compositions WHERE theme=? ORDER BY rowid', (theme,)).fetchall()
            cycle = rows[-1]['cycle'] if rows else 1
            used = {r['phrase_index'] for r in rows if r['cycle'] == cycle}
            if len(used) == 3:
                cycle += 1
                used = set()
            candidates = set(range(3)) - used
            if rows and len(candidates) > 1:
                candidates.discard(rows[-1]['phrase_index'])
            index = secrets.choice(sorted(candidates))
            image, _ = render(original, theme, index)
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=95, subsampling=0)
            uploaded = publishing.upload(directory, base64.b64encode(buffer.getvalue()).decode())
            caption = (phrase(theme, index) + '.\n\nPeça seu orçamento pelo WhatsApp: 35 9 8442-8442.'
                       '\n\n#ArteNoAltar #EnvelopesPersonalizados #PersonalizadosParaIgrejas')
            post_id = conn.execute('''INSERT INTO posts(product,channel,caption,source,image_name)
                VALUES(?,?,?,?,?)''', ('Envelopes — ' + LABELS[theme], channel, caption,
                                     'Montagem Drive · revisar', uploaded['name'])).lastrowid
            conn.execute('INSERT INTO feed_compositions VALUES(?,?,?,?,?,?,?,?,?)',
                         (request_id, signature, theme, index, cycle, file_id,
                          hashlib.sha256(original).hexdigest(), post_id, int(time.time())))
        return {'post_id': post_id, 'status': 'draft', 'phrase': phrase(theme, index), 'reused': False}
    except Exception:
        if uploaded:
            (directory / 'media' / uploaded['name']).unlink(missing_ok=True)
        raise
