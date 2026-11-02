"""Compositor local independente; somente imagens e manifesto de revisão.

Uso: python -m stories.preview --output previa.jpg
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parent
FONTS = ROOT / 'fonts'
SIZE = (1080, 1920)
# Margens editoriais conservadoras; não são garantia para todas as interfaces.
SAFE_BOX = (140, 250, 1000, 1640)
TEXT_BOX = (210, 520, 935, 820)
CATALOG = ROOT / 'verses.json'
TEMPLATE = ROOT / 'assets' / 'morning-template.jpg'
LAYOUT = ROOT / 'assets' / 'layout.json'
APPROVAL = ROOT / 'assets' / 'approval.json'


def verses():
    """Catálogo local conferido. Nenhuma busca ou geração de texto em execução."""
    return json.loads(CATALOG.read_text(encoding='utf-8'))


def load_image(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError('Use um arquivo local de imagem, sem link simbólico.')
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('A imagem deve ter até 20 MB.')
    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as source:
        if source.width * source.height > 40_000_000:
            raise ValueError('Imagem grande demais para a prévia.')
        source.load()
        return ImageOps.exif_transpose(source).convert('RGBA'), hashlib.sha256(raw).hexdigest()


def assets():
    """Impede trocar silenciosamente o fundo ou as fontes da composição."""
    layout = json.loads(LAYOUT.read_text(encoding='utf-8'))
    expected = {'assets/morning-template.jpg', 'fonts/playfairdisplay.ttf',
                'fonts/greatvibes.ttf', 'fonts/manrope.ttf'}
    if set(layout['files']) != expected or layout['size'] != list(SIZE):
        raise ValueError('Manifesto do layout inválido.')
    for name, digest in layout['files'].items():
        path = ROOT / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Fundo ou fonte alterados; revise o layout antes de exportar.')
    return layout


def layout_approved(layout):
    """Aprovação vinculada ao template, geometria e fontes da prévia conferida."""
    try:
        approval = json.loads(APPROVAL.read_text(encoding='utf-8'))
        return (approval.get('layout') == layout['layout'] and
                approval.get('files') == layout['files'] and
                approval.get('layout_sha256') == hashlib.sha256(LAYOUT.read_bytes()).hexdigest())
    except (OSError, ValueError):
        return False


def font_for(size, family='black'):
    filename = {'black': 'playfairdisplay.ttf', 'gold': 'greatvibes.ttf', 'label': 'manrope.ttf'}[family]
    font = ImageFont.truetype(str(FONTS / filename), size)
    if family == 'black':
        font.set_variation_by_name('Bold')
    elif family == 'label':
        font.set_variation_by_name('Regular')
    return font


def fit_text(draw, text, box, *, maximum=116, minimum=42, family='black', lines=None):
    """Reduz fonte e quebra linhas; recusa texto que ultrapasse a área segura."""
    width, height = box[2] - box[0], box[3] - box[1]
    for size in range(maximum, minimum - 1, -2):
        font = font_for(size, family)
        if lines is not None:
            if not isinstance(lines, list) or not all(isinstance(line, str) and line for line in lines) or ' '.join(lines) != text:
                raise ValueError('As linhas precisam preservar o texto integral do versículo.')
            wrapped = lines
        else:
            wrapped, current = [], ''
            for word in text.split():
                candidate = (current + ' ' + word).strip()
                if draw.textlength(candidate, font=font) <= width:
                    current = candidate
                else:
                    if current:
                        wrapped.append(current)
                    current = word
            if current:
                wrapped.append(current)
        if not wrapped or any(draw.textlength(line, font=font) > width for line in wrapped):
            continue
        content = '\n'.join(wrapped)
        bounds = draw.multiline_textbbox((0, 0), content, font=font, spacing=4, align='center')
        if bounds[2] - bounds[0] <= width and bounds[3] - bounds[1] <= height:
            return content, font, bounds
    raise ValueError('O versículo não cabe na área segura. Revise o texto antes de exportar.')


def place_text(draw, text, box, **options):
    content, font, bounds = fit_text(draw, text, box, **options)
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    left = box[0] + (box[2] - box[0] - width) / 2
    top = box[1] + (box[3] - box[1] - height) / 2
    origin = (left - bounds[0], top - bounds[1])
    return content, font, origin, [left, top, left + width, top + height]


def gold_text(canvas, text, font, origin):
    """Cursiva real com preenchimento dourado; não estica nem gera letras."""
    mask = Image.new('L', SIZE)
    ImageDraw.Draw(mask).multiline_text(origin, text, font=font, fill=255, spacing=4, align='center')
    bounds = mask.getbbox()
    layer = Image.new('RGB', SIZE)
    draw = ImageDraw.Draw(layer)
    stops = [(0, (243, 188, 60)), (.32, (192, 125, 23)),
             (.46, (249, 207, 101)), (.57, (184, 113, 13)), (1, (118, 63, 8))]
    for y in range(bounds[1], bounds[3]):
        position = (y - bounds[1]) / max(1, bounds[3] - bounds[1] - 1)
        for (a, first), (b, second) in zip(stops, stops[1:]):
            if a <= position <= b:
                ratio = (position - a) / (b - a)
                color = tuple(round(x + (z - x) * ratio) for x, z in zip(first, second))
                draw.line((bounds[0], y, bounds[2], y), fill=color)
                break
    canvas.paste(layer, (0, 0), mask)


def label_text(draw, text, box, *, maximum=32, minimum=24, tracking=10):
    """Referência com letras espaçadas, como na amostra aprovada."""
    for size in range(maximum, minimum - 1, -1):
        font = font_for(size, 'label')
        cursor, glyphs = 0, []
        for char in text:
            glyphs.append((cursor, char, draw.textbbox((cursor, 0), char, font=font)))
            cursor += draw.textlength(char, font=font) + tracking
        bounds = (min(g[2][0] for g in glyphs), min(g[2][1] for g in glyphs),
                  max(g[2][2] for g in glyphs), max(g[2][3] for g in glyphs))
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        if width > box[2] - box[0] or height > box[3] - box[1]:
            continue
        left = box[0] + (box[2] - box[0] - width) / 2
        top = box[1] + (box[3] - box[1] - height) / 2
        for cursor, char, _ in glyphs:
            draw.text((left - bounds[0] + cursor, top - bounds[1]), char, font=font, fill='#090807')
        return [left, top, left + width, top + height]
    raise ValueError('A referência bíblica não cabe na área segura.')


def render(background=None, *, verse_id='php-4-13'):
    verse = next((v for v in verses() if v['id'] == verse_id), None)
    if not verse or verse['translation'] != 'ARC':
        raise ValueError('Selecione um versículo ARC do catálogo conferido.')
    layout = assets()
    source, background_hash = load_image(background if background is not None else TEMPLATE)
    if source.size != SIZE or background_hash != layout['files']['assets/morning-template.jpg']:
        raise ValueError('O fundo precisa corresponder ao template conferido, sem recorte ou substituição.')
    canvas = source.convert('RGB')
    draw = ImageDraw.Draw(canvas)
    highlight = verse.get('highlight')
    if not isinstance(highlight, str) or not highlight.strip() or not verse['text'].endswith(highlight):
        raise ValueError('O destaque deve preservar o trecho final exato do versículo.')
    raw_prefix = verse['text'][:-len(highlight)]
    if not raw_prefix or not raw_prefix[-1].isspace():
        raise ValueError('O destaque precisa começar em uma palavra inteira.')
    prefix = raw_prefix.rstrip()
    content, font, origin, black_bounds = place_text(draw, prefix, layout['black_box'],
                                                    lines=verse.get('lines'), minimum=60)
    draw.multiline_text(origin, content, font=font, fill='#090807', spacing=4, align='center')
    first_line = draw.textbbox((0, 0), content.split('\n')[0], font=font)
    first_left = (layout['black_box'][0] + layout['black_box'][2] - (first_line[2] - first_line[0])) / 2
    opening = (first_left - 50, black_bounds[1] - 5)
    draw.text(opening, '“', font=font_for(80), fill='#090807', anchor='lt')
    opening_bounds = draw.textbbox(opening, '“', font=font_for(80), anchor='lt')
    gold, script, origin, gold_bounds = place_text(draw, highlight, layout['gold_box'],
                                                  family='gold', maximum=260, minimum=72)
    gold_text(canvas, gold, script, origin)
    closing = (min(945, gold_bounds[2] + 12), gold_bounds[1] + 12)
    draw.text(closing, '”', font=font_for(74), fill='#090807', anchor='lt')
    closing_bounds = draw.textbbox(closing, '”', font=font_for(74), anchor='lt')
    reference_bounds = label_text(draw, verse['reference'].upper(), layout['reference_box'])
    translation_bounds = label_text(draw, 'ARC', layout['translation_box'], maximum=23, minimum=20, tracking=5)
    text_bounds = {'black': black_bounds, 'gold': gold_bounds,
                   'opening_quote': list(opening_bounds), 'closing_quote': list(closing_bounds),
                   'reference': reference_bounds, 'translation': translation_bounds}
    if any(b[0] < SAFE_BOX[0] or b[1] < SAFE_BOX[1] or b[2] > SAFE_BOX[2] or b[3] > SAFE_BOX[3]
           for b in text_bounds.values()):
        raise ValueError('A composição ultrapassou as margens; revise antes de exportar.')
    metadata = {
        'layout': layout['layout'], 'size': list(SIZE),
        'safe_box': list(SAFE_BOX), 'verse': verse,
        'background_sha256': background_hash, 'branding': False,
        'asset_hashes': layout['files'], 'style_reference_approved': True,
        'text_bounds': text_bounds,
        'layout_approved': layout_approved(layout), 'publishing_enabled': False, 'scheduling_enabled': False,
    }
    return canvas.convert('RGB'), metadata


def export(background, output, *, verse_id='php-4-13'):
    """Não sobrescreve entrada ou saída; falhas removem somente arquivos novos."""
    target = Path(output)
    manifest = target.with_suffix('.json')
    if target.suffix.lower() not in ('.jpg', '.jpeg'):
        raise ValueError('A saída precisa ser .jpg ou .jpeg.')
    inputs = {Path(p).resolve() for p in (background if background is not None else TEMPLATE, CATALOG, LAYOUT)}
    inputs.update(path.resolve() for path in FONTS.iterdir())
    if target.resolve() in inputs or manifest.resolve() in inputs:
        raise ValueError('A saída não pode substituir os arquivos de origem.')
    if target.exists() or manifest.exists() or target.is_symlink() or manifest.is_symlink():
        raise FileExistsError('A prévia ou seu manifesto já existe; escolha outro nome.')
    image, metadata = render(background, verse_id=verse_id)
    content = io.BytesIO()
    image.save(content, 'JPEG', quality=94, subsampling=0)
    metadata['image_sha256'] = hashlib.sha256(content.getvalue()).hexdigest()
    target.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        for path, payload in ((target, content.getvalue()),
                              (manifest, json.dumps(metadata, ensure_ascii=False, indent=2).encode('utf-8'))):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return metadata


def main():
    parser = argparse.ArgumentParser(description='Prévia local de Story; não publica nem agenda.')
    parser.add_argument('--background', type=Path, help='Cópia idêntica do template; opcional.')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--verse', default='php-4-13', choices=[v['id'] for v in verses()])
    args = parser.parse_args()
    export(args.background, args.output, verse_id=args.verse)
    print('Prévia local criada. Publicação e agendamento permanecem desativados.')


if __name__ == '__main__':
    main()
