"""Nova prévia de feed baseada na referência comercial; não publica nem agenda."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from layout_preview import decode, font, PHONE, HANDLE

SIZE = (1080, 1350)
PHOTO_BOX = (24, 350, 1056, 1124)


def text_mask(text, size, target=None):
    face = font(size, weight=800)
    bounds = face.getbbox(text, anchor='lt')
    mask = Image.new('L', (bounds[2] - bounds[0] + 8, bounds[3] + 8))
    ImageDraw.Draw(mask).text((4 - bounds[0], 4), text, fill=255, font=face, anchor='lt')
    box = mask.getbbox()
    mask = mask.crop(box)
    return mask.resize(target, Image.Resampling.LANCZOS) if target else mask


def lettering(canvas, text, size, y, gold=False, target=None):
    mask = text_mask(text, size, target)
    x = (canvas.width - mask.width) // 2
    outline = mask.filter(ImageFilter.MaxFilter(3)) if gold else mask
    for depth in range(7 if gold else 4, 0, -1):
        canvas.paste('#6d2903' if gold else '#2c2c28', (x + 1, y + depth), outline)
    if gold:
        canvas.paste('#fff1a0', (x, y), outline)
    gradient = Image.linear_gradient('L').resize(mask.size)
    face = ImageOps.colorize(gradient, '#fffaa1' if gold else '#ffffff', '#f18b00' if gold else '#dcdedb')
    if gold:
        grain = Image.frombytes('L', mask.size, random.Random(42).randbytes(mask.width * mask.height))
        grain = grain.point(lambda p: 235 + p // 13)
        face = ImageChops.multiply(face, grain.convert('RGB'))
    canvas.paste(face, (x, y), mask)


def flare(canvas, x, y, radius=55):
    glow = Image.new('RGBA', canvas.size)
    draw = ImageDraw.Draw(glow)
    for r in range(radius, 0, -1):
        opacity = int(60 * (1 - r / radius) ** 2)
        draw.ellipse((x - r, y - r // 3, x + r, y + r // 3), fill=(255, 156, 20, opacity))
    draw.line((x - radius, y, x + radius, y), fill=(255, 198, 57, 200), width=2)
    draw.line((x - 15, y, x + 15, y), fill=(255, 255, 222, 255), width=3)
    draw.line((x, y - 14, x, y + 14), fill=(255, 231, 128, 180), width=2)
    canvas.alpha_composite(glow)


def background():
    canvas = Image.new('RGBA', SIZE, '#080908')
    draw = ImageDraw.Draw(canvas)
    rng = random.Random(20261030)
    for _ in range(6000):
        x, y = rng.randrange(SIZE[0]), rng.randrange(SIZE[1])
        if 345 < y < 1130:
            continue
        distance = min(math.hypot(x, y), math.hypot(1080 - x, 1350 - y))
        if rng.random() < max(0.015, 1 - distance / 520):
            alpha = rng.randrange(30, 140)
            r = rng.choice((1, 1, 1, 2))
            draw.ellipse((x, y, x + r, y + r),
                         fill=(237 * alpha // 255, 153 * alpha // 255, 28 * alpha // 255, 255))
    accent = Image.new('RGBA', SIZE)
    ad = ImageDraw.Draw(accent)
    ad.polygon(((0, 0), (188, 0), (0, 126)), fill='#d88e0b')
    ad.line((0, 116, 174, 0), fill='#fff2a0', width=3)
    ad.arc((-280, 990, 1190, 1720), 13, 112, fill='#d48b08', width=18)
    ad.arc((-280, 990, 1190, 1720), 13, 112, fill='#fff39b', width=3)
    canvas.alpha_composite(accent)
    return canvas


def contact_button(canvas):
    box = (60, 1145, 1020, 1282)
    mask = Image.new('L', SIZE)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=66, fill=255)
    glow = Image.new('RGBA', SIZE, '#ffb718')
    glow.putalpha(mask.filter(ImageFilter.GaussianBlur(21)).point(lambda p: p // 3))
    canvas.alpha_composite(glow)
    gold = ImageOps.colorize(Image.linear_gradient('L').resize((960, 137)), '#fff292', '#ec930a')
    canvas.paste(gold, (60, 1145), mask.crop(box))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius=66, outline='#aa5709', width=5)
    draw.rounded_rectangle((66, 1151, 1014, 1276), radius=61, outline='#fff5a4', width=3)
    draw.line((923, 1175, 923, 1253), fill='#af660b', width=2)
    for x in (948, 974):
        draw.line((x, 1193, x + 20, 1214, x, 1235), fill='#0e110b', width=8)
    # Ícone de contato em verde, com balão e telefone em branco.
    draw.ellipse((80, 1162, 190, 1272), fill='#0c9e35', outline='#fff7a7', width=3)
    draw.ellipse((101, 1181, 169, 1249), outline='white', width=5)
    draw.polygon(((108, 1233), (101, 1253), (124, 1246)), fill='white')
    draw.polygon(((111, 1238), (108, 1246), (121, 1241)), fill='#0c9e35')
    phone = Image.new('RGBA', (70, 70))
    pd = ImageDraw.Draw(phone)
    pd.arc((16, 10, 54, 56), 50, 225, fill='white', width=10)
    pd.rounded_rectangle((10, 10, 24, 26), radius=4, fill='white')
    pd.rounded_rectangle((41, 43, 58, 56), radius=4, fill='white')
    canvas.alpha_composite(phone, (101, 1183))
    draw = ImageDraw.Draw(canvas)
    for text, y, size in [('Peça seu orçamento', 1168, 47), ('pelo WhatsApp', 1223, 44)]:
        face = font(size, weight=800)
        x = 206 + (700 - face.getlength(text)) / 2
        draw.text((x, y), text, font=face, fill='#10120c', anchor='lt')
    flare(canvas, 377, 1148, 62)
    flare(canvas, 780, 1280, 70)


def render(source, logo):
    canvas = background()
    lettering(canvas, 'Sua igreja precisa de', 62, 18)
    lettering(canvas, 'envelopes', 182, 91, gold=True, target=(966, 145))
    lettering(canvas, 'personalizados?', 98, 251, target=(968, 82))
    draw = ImageDraw.Draw(canvas)
    for left, right in ((58, 170), (910, 1022)):
        draw.line((left, 49, right, 49), fill='#e4ac32', width=3)
    flare(canvas, 535, 238, 114)
    photo = ImageOps.contain(source, (1032, 774), Image.Resampling.LANCZOS)
    if photo.size != (1032, 774):
        raise ValueError('Esta prévia usa uma foto horizontal 4:3, preservada inteira.')
    contact_button(canvas)
    # A foto vem depois dos brilhos: nem o halo do botão cobre seus pixels.
    canvas.paste(photo, PHOTO_BOX[:2])
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((36, 1293, 246, 1343), radius=7, fill='#fffdf7')
    mark = ImageOps.contain(logo.convert('RGBA'), (190, 46), Image.Resampling.LANCZOS)
    canvas.alpha_composite(mark, (36 + (210 - mark.width) // 2, 1293 + (50 - mark.height) // 2))
    draw.text((360, 1306), PHONE, font=font(27, weight=800), fill='#fff5d7', anchor='lt')
    draw.text((815, 1312), HANDLE, font=font(20, weight=700), fill='#d7b86d', anchor='lt')
    return canvas.convert('RGB')


def build(photo_path, logo_path, directory):
    photo_path, logo_path, directory = map(Path, (photo_path, logo_path, directory))
    sources = {photo_path.resolve(), logo_path.resolve()}
    if any((directory / name).resolve() in sources for name in ('feed.png', 'feed.jpg', 'proposta.json')):
        raise ValueError('A saída não pode sobrescrever a foto ou a logo original.')
    photo_data, logo_data = photo_path.read_bytes(), logo_path.read_bytes()
    source = decode(photo_data)
    with Image.open(logo_path) as original:
        original.load()
        logo = original.convert('RGBA')
    image = render(source, logo)
    # A foto é conferida antes da exportação JPEG, que comprime os pixels.
    resized = ImageOps.contain(source, (1032, 774), Image.Resampling.LANCZOS)
    assert image.crop(PHOTO_BOX).tobytes() == resized.tobytes()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for extension in ('png', 'jpg'):
        path = directory / ('feed.' + extension)
        image.save(path, **({'quality': 95, 'subsampling': 0} if extension == 'jpg' else {}))
        path.chmod(0o600)
    metadata = {
        'layout': 'feed-gold-commercial-v2', 'size': list(SIZE),
        'approved': False, 'publishing_authorized': False,
        'purpose': 'Prévia de layout com amostra existente; não é nova seleção da rotação.',
        'photo_box': PHOTO_BOX,
        'source_sha256': hashlib.sha256(photo_data).hexdigest(),
        'logo_sha256': hashlib.sha256(logo_data).hexdigest(),
        'note': 'Composição local. Não cria rascunho, agendamento ou rotina diária.',
    }
    path = directory / 'proposta.json'
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    path.chmod(0o600)
    return str(directory / 'feed.png')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--photo', required=True)
    parser.add_argument('--logo', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(build(args.photo, args.logo, args.output))
