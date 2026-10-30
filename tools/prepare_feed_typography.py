"""Build the approved phrase bank as transparent layers, without network calls.

The first phrase accepts its original transparent lettering asset. Other phrases
are recovered from the existing, approved JPEG bank over a near-black matte.
This development command is not used by the daily publication worker.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SIZE = (1080, 450)
CONTENT_SIZE = (1030, 420)


def transparent_from_black(image, *, black_floor=18, feather=16):
    """Remove a near-black photographic matte without an opaque header panel.

    Recover alpha from the brightest channel and unpremultiply the remaining
    color. On black this reconstructs the corrected source; over a warm scene,
    the old black background is transparent. A short edge feather removes JPEG
    boundary discontinuities. Decorative gold particles remain deliberate parts
    of the lettering layer, rather than being replaced by invented text.
    """
    source = np.asarray(image.convert('RGB'), dtype=np.float32)
    source = np.clip((source-black_floor)/(255-black_floor), 0, 1)
    alpha = source.max(axis=2)
    # Ignore low-level JPEG noise so an empty dark area is truly transparent.
    alpha = np.where(alpha <= 3/255, 0, alpha)
    color = np.divide(source, alpha[..., None], out=np.zeros_like(source),
                      where=alpha[..., None] > 0)
    h, w = alpha.shape
    yy, xx = np.mgrid[:h, :w]
    edge = np.minimum.reduce((xx, yy, w-1-xx, h-1-yy))
    alpha *= np.clip(edge/max(feather, 1), 0, 1)
    rgba = np.dstack((color, alpha))
    return Image.fromarray(np.round(np.clip(rgba, 0, 1)*255).astype(np.uint8))


def fit_layer(image):
    image = image.convert('RGBA')
    bounds = image.getchannel('A').getbbox()
    if bounds is None:
        raise ValueError('A camada de tipografia ficou vazia.')
    content = ImageOps.contain(image.crop(bounds), CONTENT_SIZE,
                               Image.Resampling.LANCZOS)
    layer = Image.new('RGBA', SIZE)
    layer.alpha_composite(content, ((SIZE[0]-content.width)//2,
                                    (SIZE[1]-content.height)//2))
    return layer


def build(first_title, destination):
    source_dir = ROOT/'design_assets'/'feed'/'headers'
    original = json.loads((source_dir/'manifest.json').read_text())
    destination.mkdir(parents=True, exist_ok=True)
    with Image.open(first_title) as first:
        if first.mode != 'RGBA' or first.getchannel('A').getextrema() != (0, 255):
            raise ValueError('A primeira chamada precisa do PNG RGBA original.')
        first_layer = fit_layer(first)
    manifest = {}
    for index in range(15):
        if index == 0:
            layer = first_layer
        else:
            with Image.open(source_dir/f'{index:02d}.jpg') as source:
                layer = fit_layer(transparent_from_black(source))
        path = destination/f'{index:02d}.png'
        layer.save(path, optimize=True)
        manifest[str(index)] = {
            'phrase': original[str(index)]['phrase'],
            'filename': path.name,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    (destination/'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    return manifest


def contact_sheet(scene_path, destination, manifest, output):
    with Image.open(scene_path) as original:
        scene = original.convert('RGBA').resize((1080, 1350),
                                                Image.Resampling.LANCZOS)
    card_w, card_h = 360, 490
    sheet = Image.new('RGB', (card_w*3, card_h*5), '#efefed')
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 12)
    except OSError:
        font = ImageFont.load_default()
    for index in range(15):
        canvas = scene.copy()
        with Image.open(destination/f'{index:02d}.png') as layer:
            canvas.alpha_composite(layer, (0, 0))
        x, y = index%3*card_w, index//3*card_h
        sheet.paste(canvas.convert('RGB').resize((360, 450), Image.Resampling.LANCZOS), (x, y))
        draw.text((x+6, y+456), f'{index:02d}  {manifest[str(index)]["phrase"]}',
                  fill='#202020', font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=94)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first-title', required=True, type=Path)
    parser.add_argument('--destination', type=Path,
                        default=ROOT/'design_assets'/'feed'/'typography')
    parser.add_argument('--scene', type=Path)
    parser.add_argument('--contact-sheet', type=Path)
    args = parser.parse_args()
    if bool(args.scene) != bool(args.contact_sheet):
        parser.error('--scene e --contact-sheet devem ser fornecidos juntos.')
    manifest = build(args.first_title, args.destination)
    if args.scene:
        contact_sheet(args.scene, args.destination, manifest, args.contact_sheet)
    print(f'{len(manifest)} camadas RGBA salvas em {args.destination}')


if __name__ == '__main__':
    main()
