"""Prévia local de layouts. Não importa rascunhos, não agenda e não publica."""
import argparse
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import warnings
import zipfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

WIDTH = 1080
FONTS = Path(__file__).parent / 'design_assets' / 'fonts'
WHITE = '#f7f2e9'
GOLD = '#d4b468'
MUTED = '#c1b9a8'
PHONE = '(35) 98442-8442'
HANDLE = '@arte.no.altar'
MAX_PIXELS = 20000000


def font(size, family='manrope', weight=600):
    result = ImageFont.truetype(str(FONTS / (family + '.ttf')), size)
    axes = result.get_variation_axes()
    result.set_variation_by_axes([min(max(weight, axis['minimum']), axis['maximum']) for axis in axes])
    return result


def decode(data):
    if len(data) > 20 * 1024 * 1024:
        raise ValueError('O original excede 20 MiB.')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ('PNG', 'JPEG') or source.width * source.height > MAX_PIXELS:
                raise ValueError('Use uma imagem PNG/JPEG de até 20 milhões de pixels.')
            source.load()
            result = ImageOps.exif_transpose(source).convert('RGBA')
    # Transparência é aplicada sobre branco, sem recortar a fotografia.
    background = Image.new('RGBA', result.size, 'white')
    background.alpha_composite(result)
    return background.convert('RGB')


@dataclass
class Layout:
    image: Image.Image
    photo_box: tuple | None


class Canvas:
    def __init__(self, height, logo=None):
        gradient = Image.linear_gradient('L').resize((WIDTH, height))
        self.image = ImageOps.colorize(gradient, '#25231e', '#101413').convert('RGBA')
        glow = Image.new('RGBA', self.image.size)
        draw = ImageDraw.Draw(glow)
        draw.ellipse((490, -230, 1310, 520), fill=(157, 119, 53, 25))
        draw.ellipse((-370, height - 560, 290, height + 180), fill=(154, 114, 48, 18))
        self.image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(115)))
        self.draw = ImageDraw.Draw(self.image)
        self.draw.line((64, 27, 196, 27), fill=GOLD, width=2)
        self.height = height
        self.photo_box = None
        self.brand(logo)

    def text(self, text, xy, size=32, color=WHITE, family='manrope', weight=600,
             max_width=952, gold=False, center=False, tracking=0):
        if size < 8:
            raise ValueError('Tamanho de texto inválido.')
        while size >= 8:
            face = font(size, family, weight)
            width = face.getlength(text) + max(0, len(text) - 1) * tracking
            if width <= max_width:
                break
            size -= 1
        if width > max_width:
            raise ValueError('Texto maior que a área reservada no layout.')
        x, y = xy
        if center:
            x = (WIDTH - width) / 2
        if gold:
            self.draw.text((x + 2, y + 4), text, font=face, fill='#70501f', anchor='lt')
            self.draw.text((x + 1, y + 1), text, font=face, fill='#ae8740', anchor='lt')
            color = '#e8c97e'
        if tracking:
            for character in text:
                self.draw.text((x, y), character, font=face, fill=color, anchor='lt')
                x += face.getlength(character) + tracking
        else:
            self.draw.text((x, y), text, font=face, fill=color, anchor='lt')

    def brand(self, logo):
        y = 244 if self.height == 1920 else 56
        self.draw.rounded_rectangle((64, y, 385, y + 74), radius=10, fill='#fffdf8')
        if logo is not None:
            mark = ImageOps.contain(logo.convert('RGBA'), (287, 58), Image.Resampling.LANCZOS)
            self.image.alpha_composite(mark, (64 + (321 - mark.width) // 2, y + (74 - mark.height) // 2))
        else:
            self.text('ARTE NO ALTAR', (84, y + 16), 22, '#252522', weight=800, max_width=281, tracking=1.4)
            self.text('IDEIAS QUE EDIFICAM', (85, y + 46), 10, '#7b6b49', max_width=281, tracking=1.7)

    def kicker(self, text, y):
        self.text(text, (64, y), 17, GOLD, weight=700, tracking=2)

    def photo(self, source, top):
        photo = ImageOps.contain(source, (960, 720), Image.Resampling.LANCZOS)
        x, y = (WIDTH - photo.width) // 2, top + (720 - photo.height) // 2
        shadow = Image.new('RGBA', self.image.size)
        ImageDraw.Draw(shadow).rectangle((x - 9, y + 6, x + photo.width + 9, y + photo.height + 24), fill=(0, 0, 0, 140))
        self.image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(22)))
        self.draw.rounded_rectangle((x - 10, y - 10, x + photo.width + 10, y + photo.height + 10),
                                    radius=10, fill='#1c1f1c', outline='#77633b', width=1)
        # Fonte inteira, sem máscara, recorte, texto ou efeitos sobre o produto.
        self.image.paste(photo, (x, y))
        self.photo_box = (x, y, x + photo.width, y + photo.height)

    def cta(self, text, y=1208):
        self.draw.rounded_rectangle((64, y, 1016, y + 90), radius=16, fill='#272a23', outline='#8c7847', width=1)
        self.text(text, (90, y + 30), 23, WHITE, weight=700, max_width=475)
        self.text('WHATSAPP', (660, y + 14), 12, GOLD, weight=700, max_width=324, tracking=1.5)
        self.text(PHONE, (660, y + 38), 27, WHITE, weight=800, max_width=324)

    def mini_footer(self):
        self.draw.line((64, 1234, 1016, 1234), fill='#5b5139', width=1)
        self.text(HANDLE, (64, 1266), 20, MUTED)
        self.text(PHONE, (706, 1266), 23, WHITE, max_width=310)

    def result(self):
        return Layout(self.image.convert('RGB'), self.photo_box)


def feed(source, logo=None):
    canvas = Canvas(1350, logo)
    canvas.kicker('ENVELOPES PERSONALIZADOS', 154)
    canvas.text('Envelopes que', (64, 204), 82, family='cormorantgaramond', weight=700)
    canvas.text('levam propósito.', (64, 283), 82, family='cormorantgaramond', weight=700, gold=True)
    canvas.photo(source, 382)
    canvas.text('Modelo de referência para personalização.', (64, 1124), 17, MUTED)
    canvas.text('Sua igreja em cada detalhe.', (64, 1162), 26, WHITE)
    canvas.cta('Peça seu orçamento')
    return canvas.result()


def story(source, logo=None):
    canvas = Canvas(1920, logo)
    canvas.kicker('FEITO PARA A SUA IGREJA', 354)
    canvas.text('Sua igreja.', (64, 406), 109, family='cormorantgaramond', weight=700)
    canvas.text('Seu propósito.', (64, 512), 109, family='cormorantgaramond', weight=700, gold=True)
    canvas.text('Envelopes com a sua identidade.', (64, 616), 27, MUTED)
    canvas.photo(source, 670)
    canvas.draw.rounded_rectangle((64, 1452, 1016, 1532), radius=16, fill='#ceb06b')
    canvas.text('FAÇA SEU PEDIDO', (0, 1480), 25, '#171b17', weight=800, center=True)
    canvas.text('WHATSAPP', (0, 1570), 16, GOLD, weight=700, center=True)
    canvas.text(PHONE, (0, 1606), 50, WHITE, weight=800, center=True)
    canvas.text(HANDLE, (0, 1678), 19, MUTED, center=True)
    return canvas.result()


def carousel(source, logo=None):
    first, second, third = [Canvas(1350, logo) for _ in range(3)]
    for index, canvas in enumerate((first, second, third), 1):
        canvas.text(f'{index:02d} / 03', (920, 80), 17, MUTED, max_width=96)
        canvas.kicker('PERGUNTAS DE QUEM PERSONALIZA', 168)
    first.draw.ellipse((64, 258, 196, 390), outline='#8d7440', width=1)
    first.text('?', (105, 278), 84, GOLD, family='cormorantgaramond', weight=700, max_width=70)
    first.text('Posso colocar', (64, 450), 100, family='cormorantgaramond', weight=700)
    first.text('o nome da', (64, 558), 100, family='cormorantgaramond', weight=700)
    first.text('minha igreja?', (64, 666), 108, family='cormorantgaramond', weight=700, gold=True)
    first.draw.line((64, 862, 208, 862), fill=GOLD, width=2)
    first.text('Veja como funciona a personalização.', (64, 908), 29, MUTED)
    first.text('ARRASTE PARA DESCOBRIR', (64, 1050), 16, GOLD, tracking=2)
    first.draw.line((884, 1060, 1008, 1060), fill=GOLD, width=2)
    first.draw.line((993, 1046, 1008, 1060, 993, 1074), fill=GOLD, width=2)
    first.mini_footer()
    second.text('Sim. Do seu jeito.', (64, 240), 83, family='cormorantgaramond', weight=700, gold=True)
    second.photo(source, 382)
    second.text('Nome, logo e informações da sua igreja.', (64, 1144), 27, WHITE)
    second.text('Modelo de referência para personalização.', (64, 1188), 17, MUTED)
    second.mini_footer()
    third.text('Sua ideia,', (64, 370), 106, family='cormorantgaramond', weight=700)
    third.text('com a identidade', (64, 478), 91, family='cormorantgaramond', weight=700)
    third.text('da sua igreja.', (64, 582), 104, family='cormorantgaramond', weight=700, gold=True)
    for y, text in [(828, 'Nome da igreja'), (904, 'Seu logotipo'), (980, 'Informações para a personalização')]:
        third.draw.ellipse((68, y + 11, 78, y + 21), fill=GOLD)
        third.text(text, (108, y), 30, WHITE, max_width=900)
    third.cta('Fale conosco')
    return [first.result(), second.result(), third.result()]


def read_samples(path):
    with zipfile.ZipFile(path) as archive:
        if (sum(info.file_size for info in archive.infolist()) > 28 * 1024 * 1024 or
                len(archive.infolist()) > 7):
            raise ValueError('Pacote de amostras excedeu o limite.')
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or '..' in name.parts:
                raise ValueError('Caminho inválido no pacote.')
        raw = archive.read('catalogo.json')
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('Catálogo maior que o limite.')
        manifest = json.loads(raw)
        samples = manifest.get('samples', [])
        if len(samples) < 3:
            raise ValueError('A proposta usa três modelos; gere um pacote com pelo menos três amostras.')
        sources, digests = [], set()
        for item in samples[:3]:
            name = item['archive_path']
            if not name.startswith('originais/') or PurePosixPath(name).suffix.lower() not in ('.png', '.jpg'):
                raise ValueError('Referência de imagem inválida no pacote.')
            data = archive.read(name)
            digest = hashlib.sha256(data).hexdigest()
            if digest in digests:
                raise ValueError('As três amostras devem ser originais diferentes.')
            digests.add(digest)
            sources.append({'image': decode(data), 'id': item['id'], 'name': item['name'], 'sha256': digest})
    return sources


def contact_sheet(layouts):
    sheet = Image.new('RGB', (1660, 1920), '#eeeae2')
    draw = ImageDraw.Draw(sheet)
    draw.text((52, 36), 'PROPOSTA 01 · PRETO E DOURADO', fill='#242721', font=font(32, weight=800))
    draw.text((52, 84), 'Montagem com originais preservados · identidade tipográfica provisória', fill='#6f705f', font=font(19))
    for key, title, x, y, size in [('feed', 'FEED · 1080 × 1350', 52, 160, (640, 800)),
                                  ('story', 'STORY · 1080 × 1920', 822, 160, (450, 800))]:
        draw.text((x, y), title, fill='#34372c', font=font(22, weight=800))
        image = layouts[key].image.resize(size, Image.Resampling.LANCZOS)
        sheet.paste(image, (x, y + 48))
    draw.text((52, 1082), 'CARROSSEL · 3 SLIDES · 1080 × 1350', fill='#34372c', font=font(24, weight=800))
    for index in range(1, 4):
        image = layouts[f'carousel-{index:02d}'].image.resize((492, 615), Image.Resampling.LANCZOS)
        x = 52 + (index - 1) * 530
        sheet.paste(image, (x, 1144))
        draw.text((x, 1776), f'{index:02d} / 03', fill='#686b5c', font=font(17))
    draw.text((52, 1850), 'Prévia para aprovação. Nenhuma arte foi agendada ou publicada.', fill='#686b5c', font=font(20))
    return sheet


def build_review(archive_path, directory, logo_path=None):
    directory = Path(directory)
    destination = directory.parent / 'proposta-layouts.zip'
    if destination.resolve() == Path(archive_path).resolve():
        raise ValueError('A proposta não pode sobrescrever o pacote de originais.')
    sources = read_samples(archive_path)
    logo = None
    if logo_path:
        with Image.open(logo_path) as original:
            if original.width * original.height > MAX_PIXELS:
                raise ValueError('Logo excedeu o limite de pixels.')
            original.load()
            logo = original.convert('RGBA')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    layouts = {'feed': feed(sources[0]['image'], logo), 'story': story(sources[1]['image'], logo)}
    layouts.update({f'carousel-{i:02d}': layout for i, layout in enumerate(carousel(sources[2]['image'], logo), 1)})
    files, details = [], {}
    for name, layout in layouts.items():
        for extension in ('png', 'jpg'):
            path = directory / f'{name}.{extension}'
            options = {'quality': 94, 'subsampling': 0} if extension == 'jpg' else {'compress_level': 6}
            layout.image.save(path, **options)
            path.chmod(0o600)
            files.append(path)
        details[name] = {'size': list(layout.image.size), 'photo_box': layout.photo_box}
    preview = directory / 'preview.png'
    contact_sheet(layouts).save(preview)
    preview.chmod(0o600)
    files.append(preview)
    manifest = {'layout': 'black-gold-v1', 'approved': False, 'official_logo_supplied': logo is not None,
                'sources': [{k: value for k, value in source.items() if k != 'image'} for source in sources],
                'canvases': details, 'phone': PHONE,
                'note': 'Proposta local. Não ativa agendamento, publicação, sorteio ou geração diária.'}
    metadata = directory / 'proposta.json'
    metadata.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    metadata.chmod(0o600)
    files.append(metadata)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_STORED) as archive:
        for path in files:
            archive.write(path, path.name)
    destination.chmod(0o600)
    return {'preview': str(preview), 'zip': str(destination), 'official_logo_supplied': logo is not None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', required=True)
    parser.add_argument('--logo')
    args = parser.parse_args()
    import app
    try:
        result = build_review(Path(args.samples), app.DB.parent / 'layout-review', args.logo)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise SystemExit('Não foi possível montar a prévia. Confira o pacote de amostras e a imagem da logo.') from None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print('Proposta criada para aprovação. Nenhuma publicação ou agendamento foi realizado.')
