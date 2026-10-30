"""Recorta a impressão original e projeta o papel na cena, sem redesenhar a arte."""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps
from layout_preview import decode

ASSETS = Path(__file__).parent / 'design_assets' / 'feed'
VERSION = 'ambient-scene-v1'


class CutoutError(ValueError):
    pass


def backend():
    try:
        import cv2
        import numpy
        cv2.setNumThreads(1)
        return cv2, numpy
    except ImportError:
        raise CutoutError('Instale as dependências do recorte antes de ativar a rotina.') from None


def validate_quad(points, size):
    import math
    if not isinstance(points, (list, tuple)) or len(points) != 4:
        raise CutoutError('O recorte precisa dos quatro cantos do papel.')
    if any(not isinstance(p, (list, tuple)) or len(p) != 2 or
           any(type(v) not in (int, float) or not math.isfinite(v) for v in p) for p in points):
        raise CutoutError('Coordenadas de recorte inválidas.')
    w, h = size
    if any(not (0 <= x < w and 0 <= y < h) for x, y in points):
        raise CutoutError('O recorte saiu da imagem original.')
    cross = []
    for i in range(4):
        a, b, c = points[i], points[(i+1)%4], points[(i+2)%4]
        cross.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
    if min(cross) <= 0:
        raise CutoutError('O papel precisa formar um quadrilátero convexo.')
    area = abs(sum(points[i][0]*points[(i+1)%4][1]-points[(i+1)%4][0]*points[i][1] for i in range(4)))/2
    if not .12*w*h <= area <= .9*w*h:
        raise CutoutError('A área do envelope não foi identificada com segurança.')
    return points


def detect_quad(raw):
    image = decode(raw)
    known = json.loads((ASSETS/'cutout-hints.json').read_text())
    hint = known.get(hashlib.sha256(raw).hexdigest())
    if hint:
        return validate_quad(hint, image.size)
    cv, np = backend()
    small = ImageOps.contain(image, (1400, 1400))
    pixels = np.array(small)
    hsv = cv.cvtColor(pixels, cv.COLOR_RGB2HSV)
    h, w = pixels.shape[:2]
    candidates = []
    for brightness in (185, 205, 225, 240):
        mask = cv.inRange(hsv, np.array((0, 0, brightness)), np.array((179, 70, 255)))
        mask = cv.morphologyEx(mask, cv.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        contours, _ = cv.findContours(mask, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            hull = cv.convexHull(contour)
            for epsilon in (.01, .02, .035):
                quad = cv.approxPolyDP(hull, cv.arcLength(hull, True)*epsilon, True)
                if len(quad) != 4 or not cv.isContourConvex(quad):
                    continue
                points = quad.reshape(4, 2).astype(float)
                center = points.mean(axis=0)
                points = points[np.argsort(np.arctan2(points[:, 1]-center[1], points[:, 0]-center[0]))]
                points = np.roll(points, -int(np.argmin(points.sum(axis=1))), axis=0)
                try:
                    validate_quad(points.tolist(), (w, h))
                except CutoutError:
                    continue
                lengths = [float(np.linalg.norm(points[(i+1)%4]-points[i])) for i in range(4)]
                ratio = (lengths[0]+lengths[2])/(lengths[1]+lengths[3])
                if not 1.25 < ratio < 2.1 or center[1] < h*.42:
                    continue
                if (points[:, 0].min() < w*.015 or points[:, 0].max() > w*.985 or
                        points[:, 1].min() < h*.015 or points[:, 1].max() > h*.985):
                    continue
                # As quatro bordas precisam ser papel claro. Isso rejeita cortes
                # internos sobre a impressão e papéis ocultos por objetos.
                border_ok = True
                for i in range(4):
                    samples = np.array([points[i]*(1-t)+points[(i+1)%4]*t for t in np.linspace(.08, .92, 60)])
                    samples = samples*.995 + center*.005
                    colors = pixels[samples[:, 1].astype(int), samples[:, 0].astype(int)].astype(int)
                    white = (colors.min(axis=1) >= 180) & (colors.max(axis=1)-colors.min(axis=1) <= 35)
                    if white.mean() < .72:
                        border_ok = False
                if border_ok:
                    area = cv.contourArea(points.astype(np.float32))
                    candidates.append((area, points))
    if not candidates:
        raise CutoutError('Não foi possível separar o papel inteiro do envelope. A imagem ficou para revisão.')
    candidates.sort(key=lambda item: item[0], reverse=True)
    quad = candidates[0][1]
    return validate_quad([[float(x*image.width/w), float(y*image.height/h)] for x, y in quad], image.size)


def _solve(matrix, values):
    rows = [list(map(float, row))+[float(v)] for row, v in zip(matrix, values)]
    for k in range(8):
        pivot = max(range(k, 8), key=lambda i: abs(rows[i][k]))
        rows[k], rows[pivot] = rows[pivot], rows[k]
        scale = rows[k][k]
        if abs(scale) < 1e-10:
            raise CutoutError('Perspectiva inválida.')
        rows[k] = [v/scale for v in rows[k]]
        for i in range(8):
            if i != k:
                scale = rows[i][k]
                rows[i] = [a-scale*b for a, b in zip(rows[i], rows[k])]
    return [row[-1] for row in rows]


def project(image, quad, size):
    w, h = image.size
    matrix, values = [], []
    for (x, y), (u, v) in zip(quad, [(0, 0), (w-1, 0), (w-1, h-1), (0, h-1)]):
        matrix.extend(([x, y, 1, 0, 0, 0, -u*x, -u*y], [0, 0, 0, x, y, 1, -v*x, -v*y]))
        values.extend((u, v))
    return image.transform(size, Image.Transform.PERSPECTIVE, _solve(matrix, values), Image.Resampling.BICUBIC)


def render(raw, index, *, expected_phrase=None):
    source = decode(raw).convert('RGBA')
    quad = detect_quad(raw)
    # QUAD pede UL, LL, LR, UR. A fonte fornece a impressão inteira, sem IA.
    face = source.transform((940, 606), Image.Transform.QUAD,
                            tuple(v for i in (0, 3, 2, 1) for v in quad[i]), Image.Resampling.BICUBIC)
    with Image.open(ASSETS/'template.jpg') as base:
        canvas = base.convert('RGBA')
    path = ASSETS/'headers'/f'{index:02d}.jpg'
    manifest = json.loads((ASSETS/'headers'/'manifest.json').read_text())
    record = manifest.get(str(index), {})
    if record.get('sha256') != hashlib.sha256(path.read_bytes()).hexdigest() or expected_phrase is not None and record.get('phrase') != expected_phrase:
        raise CutoutError('O cabeçalho precisa corresponder à frase aprovada.')
    with Image.open(path) as header:
        if header.size != (1080, 345):
            raise CutoutError('Cabeçalho inválido.')
        canvas.paste(header, (0, 0))
    shadow = Image.new('RGBA', canvas.size)
    ImageDraw.Draw(shadow).ellipse((60, 810, 790, 946), fill=(22, 9, 0, 155))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(23)))
    stack = [(40, 555), (602, 428), (829, 591), (239, 775)]
    pages = Image.new('RGBA', canvas.size)
    draw = ImageDraw.Draw(pages)
    for i in range(48, 0, -1):
        paper = [(x, y+i*2) for x, y in stack]
        draw.polygon(paper, fill=(213+i%3*6, 207+i%3*6, 195+i%3*6, 255))
        draw.line(paper+[paper[0]], fill=(245, 242, 229, 255), width=1)
    canvas.alpha_composite(pages)
    canvas.alpha_composite(project(face, stack, canvas.size))
    front = [(165, 572), (970, 558), (989, 1072), (148, 1080)]
    shadow = Image.new('RGBA', canvas.size)
    ImageDraw.Draw(shadow).polygon([(x+15, y+13) for x, y in front], fill=(25, 10, 0, 135))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
    contact = Image.new('RGBA', canvas.size)
    ImageDraw.Draw(contact).ellipse((151, 1065, 1010, 1102), fill=(24, 10, 0, 155))
    canvas.alpha_composite(contact.filter(ImageFilter.GaussianBlur(8)))
    paper = Image.new('RGBA', canvas.size)
    ImageDraw.Draw(paper).polygon([(x+1, y+4) for x, y in front], fill='#dfd5bd')
    canvas.alpha_composite(paper)
    canvas.alpha_composite(project(face, front, canvas.size))
    return canvas.convert('RGB'), tuple(front)
