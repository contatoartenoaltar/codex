"""Gera prévias locais de Stories comerciais. Não agenda nem publica."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops

from layout_preview import decode
from product_scene import project


SIZE = (1080, 1920)
ASSETS = Path(__file__).parent / "design_assets" / "promotional_story"
TITLES = ASSETS / "titles"
SPEC = ASSETS / "approved-scenes.json"
CTA = "Peça seu orçamento pelo WhatsApp"
PHONE = "35 9 8442-8442"
TIMES = ("04:00", "06:00", "08:00", "10:00", "12:10",
         "14:00", "16:00", "18:00", "20:00", "22:00")
PHRASES = (
    ("Envelopes", "com a sua", "IDENTIDADE"),
    ("Sua igreja", "em cada", "DETALHE"),
    ("Personalização", "que faz a", "DIFERENÇA"),
    ("Feitos para", "a sua", "IGREJA"),
    ("Seu modelo,", "sua", "IDENTIDADE"),
    ("Envelopes que", "levam", "PROPÓSITO"),
    ("Cada detalhe", "comunica", "CUIDADO"),
    ("A marca", "da sua", "IGREJA"),
    ("Sua identidade", "merece", "DESTAQUE"),
    ("Pequenos detalhes,", "grande", "SIGNIFICADO"),
)


class PreviewError(ValueError):
    pass


def daily_selection(catalog: list[str], used_in_cycle: list[str]) -> tuple[list[str], list[str]]:
    """Escolhe 10 modelos únicos e só reinicia após consumir o catálogo."""
    ordered = list(dict.fromkeys(catalog))
    if len(ordered) < 10:
        raise PreviewError("O catálogo precisa ter pelo menos 10 modelos diferentes.")
    used = [item for item in dict.fromkeys(used_in_cycle) if item in ordered]
    remaining = [item for item in ordered if item not in used]
    selected = remaining[:10]
    if len(selected) == 10:
        return selected, used + selected
    # A seleção pode atravessar o fim de um ciclo, mas continua sem duplicar no dia.
    after_reset = [item for item in ordered if item not in selected]
    new_cycle = after_reset[:10 - len(selected)]
    return selected + new_cycle, new_cycle


def daily_phrase_indices(day_number: int) -> list[int]:
    if type(day_number) is not int or day_number < 0:
        raise PreviewError("O número do dia do ciclo precisa ser válido.")
    offset = day_number % len(PHRASES)
    return [(offset + index) % len(PHRASES) for index in range(10)]


def _spec() -> dict:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    records = spec.get("titles")
    if (spec.get("version") != "promotional-story-reference-titles-v4" or
            spec.get("size") != list(SIZE) or not isinstance(records, list) or
            len(records) != len(PHRASES)):
        raise PreviewError("O cenário comercial não corresponde à arte aprovada.")
    for index, (record, lines) in enumerate(zip(records, PHRASES)):
        path = TITLES / f"{index:02d}.jpg"
        if (record.get("filename") != path.name or record.get("lines") != list(lines) or
                record.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest()):
            raise PreviewError("Um dos títulos não corresponde à referência aprovada.")
    for name in ("back", "front"):
        points = spec.get(name)
        if (not isinstance(points, list) or len(points) != 4 or
                any(not isinstance(point, list) or len(point) != 2 for point in points)):
            raise PreviewError("A área do produto no cenário está inválida.")
    return spec


def _master(phrase_index: int) -> tuple[Image.Image, dict]:
    spec = _spec()
    with Image.open(TITLES / f"{phrase_index:02d}.jpg") as image:
        if image.size != SIZE:
            raise PreviewError("O cenário aprovado precisa estar em 1080 × 1920.")
        return image.convert("RGBA"), spec


def _ink_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    """Remove somente a margem branca externa, mantendo a arte completa."""
    rgb = image.convert("RGB")
    white = Image.new("RGB", rgb.size, "white")
    mask = ImageChops.difference(rgb, white).convert("L").point(
        lambda value: 255 if value > 18 else 0)
    bbox = mask.getbbox()
    if bbox is None:
        raise PreviewError("O modelo enviado está vazio.")
    left, top, right, bottom = bbox
    width, height = right - left, bottom - top
    if width * height < rgb.width * rgb.height * 0.18:
        raise PreviewError("Não foi possível identificar o modelo completo com segurança.")
    margin = max(8, round(min(width, height) * 0.018))
    return (max(0, left - margin), max(0, top - margin),
            min(rgb.width, right + margin), min(rgb.height, bottom + margin))


def upright_model(raw: bytes) -> Image.Image:
    image = decode(raw)
    model = image.crop(_ink_bbox(image))
    if model.height > model.width:
        model = model.transpose(Image.Transpose.ROTATE_90)
    return model


def render(raw: bytes, phrase_index: int = 0) -> tuple[Image.Image, dict]:
    """Substitui só as superfícies dos envelopes na cena aprovada."""
    if type(phrase_index) is not int or not 0 <= phrase_index < len(PHRASES):
        raise PreviewError("Escolha uma das 10 frases comerciais aprovadas.")
    canvas, spec = _master(phrase_index)
    model = upright_model(raw).convert("RGBA")
    canvas.alpha_composite(project(model, spec["back"], SIZE))
    canvas.alpha_composite(project(model, spec["front"], SIZE))
    lines = PHRASES[phrase_index]
    return canvas.convert("RGB"), {
        "version": "promotional-story-reference-titles-v4",
        "size": list(SIZE),
        "title": " ".join(lines),
        "title_lines": list(lines),
        "phrase_index": phrase_index,
        "cta": CTA,
        "phone": PHONE,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }


def save_preview(source: Path, output: Path, phrase_index: int = 0) -> dict:
    image, manifest = render(source.read_bytes(), phrase_index)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "JPEG", quality=95, subsampling=0, optimize=True)
    manifest["output_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def save_batch(sources: list[Path], output: Path, *, day: str, day_number: int = 0) -> dict:
    if len(sources) != len(TIMES):
        raise PreviewError("O lote diário precisa conter exatamente 10 modelos.")
    hashes = [hashlib.sha256(path.read_bytes()).hexdigest() for path in sources]
    if len(set(hashes)) != len(sources):
        raise PreviewError("O mesmo modelo não pode aparecer duas vezes no lote.")
    output.mkdir(parents=True, exist_ok=True)
    items = []
    phrase_indices = daily_phrase_indices(day_number)
    for index, (source, time, phrase_index) in enumerate(
            zip(sources, TIMES, phrase_indices), 1):
        target = output / f"{index:02d}-{time.replace(':', 'h')}.jpg"
        manifest = save_preview(source, target, phrase_index)
        items.append({"number": index, "day": day, "time": time,
                      "source": source.name, "filename": target.name,
                      "title": manifest["title"],
                      "title_lines": manifest["title_lines"],
                      "source_sha256": manifest["source_sha256"],
                      "output_sha256": manifest["output_sha256"]})
    batch = {"version": "promotional-story-batch-v1", "day": day,
             "publishing_enabled": False, "items": items}
    (output / "batch.json").write_text(
        json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return batch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--phrase", type=int, default=1, choices=range(1, 11))
    args = parser.parse_args()
    print(json.dumps(
        save_preview(args.source, args.output, args.phrase - 1), ensure_ascii=False))


if __name__ == "__main__":
    main()
