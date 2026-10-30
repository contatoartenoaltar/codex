"""Prepara o cenário aprovado; não usa fotos do Drive nem acessa serviços."""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]


def prepare(source):
    assets = ROOT / 'design_assets' / 'feed'
    with Image.open(source) as image:
        original_size = image.size
        image = ImageOps.fit(image.convert('RGB'), (1080, 1350), Image.Resampling.LANCZOS)
        image.save(assets / 'scene-v2.jpg', quality=96, subsampling=0)
    # Cantos conferidos na base sem impressão, antes de inserir modelos privados.
    # São pontos normalizados do master: UL, UR, LR, LL. A pilha é parcialmente
    # oculta pelo papel frontal; a máscara de oclusão é aplicada em tempo de execução.
    def normalized(points):
        return [[round(x / 1122 * 1080, 3), round(y / 1402 * 1350, 3)] for x, y in points]
    specification = {
        'version': 'continuous-scene-v2', 'filename': 'scene-v2.jpg',
        'sha256': hashlib.sha256((assets / 'scene-v2.jpg').read_bytes()).hexdigest(),
        'size': [1080, 1350],
        'front': normalized([[236, 607], [1016, 637], [1009, 1130], [189, 1079]]),
        'front_paper': normalized([[232, 600], [1020, 633], [1012, 1136], [183, 1083]]),
        'stack': normalized([[-78, 555], [491, 462], [702, 596], [136, 723]]),
        'typography_box': [0, 0, 1080, 450],
        'illumination_min': 0.94, 'illumination_max': 1.04,
        'source_master_size': list(original_size),
    }
    (assets / 'scene-v2.json').write_text(json.dumps(specification, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    prepare(parser.parse_args().source)
