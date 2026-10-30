"""Integra a impressão original aos papéis de uma cena contínua aprovada."""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
from layout_preview import decode

ASSETS = Path(__file__).parent / 'design_assets' / 'feed'
VERSION = 'continuous-scene-v2'
MASTER = ASSETS / 'scene-v2.jpg'
SCENE_SPEC = ASSETS / 'scene-v2.json'
TYPOGRAPHY = ASSETS / 'typography'


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


def asset_files():
    """Inclui a geometria e as máscaras na identidade da política autorizada."""
    return [MASTER, SCENE_SPEC, ASSETS/'cutout-hints.json', TYPOGRAPHY/'manifest.json',
            *(TYPOGRAPHY/f'{index:02d}.png' for index in range(15))]


def _scene():
    spec = json.loads(SCENE_SPEC.read_text())
    if (spec.get('version') != VERSION or spec.get('filename') != MASTER.name or
            spec.get('size') != [1080, 1350] or
            spec.get('sha256') != hashlib.sha256(MASTER.read_bytes()).hexdigest()):
        raise CutoutError('O cenário precisa corresponder à montagem conferida.')
    with Image.open(MASTER) as image:
        if image.size != (1080, 1350):
            raise CutoutError('Dimensões do cenário inválidas.')
        canvas = image.convert('RGBA')
    return canvas, spec


def _typography(index, expected_phrase=None):
    manifest = json.loads((TYPOGRAPHY/'manifest.json').read_text())
    record = manifest.get(str(index), {})
    path = TYPOGRAPHY/f'{index:02d}.png'
    if (record.get('filename') != path.name or
            record.get('sha256') != hashlib.sha256(path.read_bytes()).hexdigest() or
            expected_phrase is not None and record.get('phrase') != expected_phrase):
        raise CutoutError('A tipografia precisa corresponder à frase aprovada.')
    with Image.open(path) as image:
        if image.size != (1080, 450) or image.mode != 'RGBA' or image.getchannel('A').getextrema() != (0, 255):
            raise CutoutError('A frase precisa ter fundo transparente, sem painel opaco.')
        return image.copy()


def validate_assets(expected_phrases=None):
    _scene()
    for index in range(15):
        _typography(index, None if expected_phrases is None else expected_phrases[index])


def _paper_light(layer, master, limits):
    """Compartilha a luz do papel sem redesenhar letras, logos ou QR Codes."""
    _, np = backend()
    paper = np.asarray(master.convert('RGB'), dtype=np.float32)
    # Uma variação discreta de luminosidade evita brancos luminosos recortados.
    # A impressão é reamostrada geometricamente; não há geração de texto por IA.
    luminance = paper.mean(axis=2)/240.0
    gain = np.clip(luminance, *limits)
    pixels = np.asarray(layer).copy()
    pixels[:, :, :3] = np.clip(pixels[:, :, :3].astype(np.float32)*gain[:, :, None], 0, 255).astype(np.uint8)
    return Image.fromarray(pixels)


def render(raw, index, *, expected_phrase=None):
    if type(index) is not int or not 0 <= index < 15:
        raise CutoutError('Chamada fora do banco aprovado.')
    source = decode(raw).convert('RGBA')
    quad = detect_quad(raw)
    # Afasta a amostragem poucos pixels da borda externa para não transportar
    # o filete escuro da mesa fotografada junto com o papel claro.
    center = [sum(point[axis] for point in quad)/4 for axis in range(2)]
    inner = [[value*.994+center[axis]*.006 for axis, value in enumerate(point)] for point in quad]
    # QUAD pede UL, LL, LR, UR. A fonte fornece a impressão inteira, sem IA.
    face = source.transform((940, 606), Image.Transform.QUAD,
                            tuple(v for i in (0, 3, 2, 1) for v in inner[i]), Image.Resampling.BICUBIC)
    canvas, spec = _scene()
    master = canvas.copy()
    limits = (spec['illumination_min'], spec['illumination_max'])
    # O fundo inteiro já contém a mesa, papéis, sombras, espessura e CTA.
    # Substitui-se somente a superfície impressa; não se cola outra fotografia.
    stack = project(face, spec['stack'], canvas.size).filter(ImageFilter.GaussianBlur(.45))
    occlusion = Image.new('L', canvas.size)
    ImageDraw.Draw(occlusion).polygon([tuple(point) for point in spec['front_paper']], fill=255)
    stack.putalpha(ImageChops.subtract(stack.getchannel('A'), occlusion))
    canvas.alpha_composite(_paper_light(stack, master, limits))
    canvas.alpha_composite(_paper_light(project(face, spec['front'], canvas.size), master, limits))
    canvas.alpha_composite(_typography(index, expected_phrase), (0, 0))
    return canvas.convert('RGB'), tuple(tuple(point) for point in spec['front'])
