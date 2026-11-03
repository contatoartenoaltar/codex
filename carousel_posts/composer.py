"""Compositor local dos carrosséis aprovados. Não agenda nem publica."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "design_assets" / "carousel"
CATALOG = ASSETS / "approved-faq.json"
REFERENCE = ASSETS / "reference"
BACKGROUNDS = ASSETS / "backgrounds"
LOGO = REFERENCE / "logo-header-approved.png"
SIZE = (1080, 1350)
VERSION = "carousel-faq-black-brand-v2"
FONT = ROOT / "design_assets" / "fonts" / "manrope.ttf"
WHITE, GOLD, CYAN, MAGENTA, MUTED = "#fffdf8", "#ffc52e", "#00cfee", "#ed168c", "#c5c5c1"
PHONE, WEBSITE = "35 9 8442-8442", "artenoaltar.com.br"

ACCENTS = {
    "formas-de-envio": "envio?", "localizacao": "localizados?",
    "valores-envelopes": "personalizados?", "personalizacao-envelopes": "personalizados?",
    "formas-de-pagamento": "pagamento?", "quantidade-minima": "mínima?",
    "outros-produtos": "envelopes?", "tamanho-e-fechamento": "fechados?",
    "simulacao-com-logo": "minha igreja?", "modelos-disponiveis": "escolher?",
    "outras-denominacoes": "denominações?", "projeto-de-vida": "Projeto de Vida?",
    "onde-comprar": "comprar?", "instagram": "gráfica?",
}


class ComposeError(ValueError):
    pass


def catalog() -> list[dict]:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    items = data.get("items")
    if (data.get("version") != 1 or not isinstance(items, list) or len(items) != 14 or
            {entry.get("id") for entry in items} != set(ACCENTS)):
        raise ComposeError("O catálogo aprovado de carrosséis mudou.")
    return items


def item(ident: str) -> dict:
    result = next((entry for entry in catalog() if entry["id"] == ident), None)
    if result is None:
        raise ComposeError("Pergunta de carrossel não aprovada.")
    return result


def _source_paths() -> list[Path]:
    paths = [CATALOG, LOGO, REFERENCE / "manifest.json"]
    paths.extend(sorted(REFERENCE.glob("shipping-*-approved.png")))
    paths.extend(sorted(BACKGROUNDS.glob("*.png")))
    expected = set(ACCENTS) - {"formas-de-envio"}
    if {path.stem for path in paths if path.parent == BACKGROUNDS} != expected:
        raise ComposeError("A biblioteca visual precisa conter os 13 temas complementares.")
    return paths


def rules_hash() -> str:
    digest = hashlib.sha256(VERSION.encode())
    for path in _source_paths():
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes())
    digest.update(json.dumps(ACCENTS, ensure_ascii=False, sort_keys=True).encode())
    return digest.hexdigest()


def _font(size: int, weight: int = 800) -> ImageFont.FreeTypeFont:
    face = ImageFont.truetype(str(FONT), size)
    try:
        axes = face.get_variation_axes()
        face.set_variation_by_axes([
            min(weight, axis["maximum"]) if axis["name"].lower().startswith(b"weight") else axis["default"]
            for axis in axes
        ])
    except (AttributeError, OSError, TypeError):
        pass
    return face


def _cover_image(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    ratio = max(SIZE[0] / image.width, SIZE[1] / image.height)
    resized = image.resize((round(image.width * ratio), round(image.height * ratio)), Image.Resampling.LANCZOS)
    left, top = (resized.width - SIZE[0]) // 2, (resized.height - SIZE[1]) // 2
    return resized.crop((left, top, left + SIZE[0], top + SIZE[1]))


def _master(ident: str, *, slide: int) -> Image.Image:
    image = _cover_image(BACKGROUNDS / f"{ident}.png")
    if slide == 2:
        image = ImageEnhance.Brightness(image).enhance(0.72).filter(ImageFilter.GaussianBlur(1.1))
    elif slide == 3:
        image = ImageEnhance.Brightness(image).enhance(0.58).filter(ImageFilter.GaussianBlur(1.7))
    return image.convert("RGBA")


def _logo(canvas: Image.Image) -> None:
    with Image.open(LOGO) as opened:
        logo = opened.convert("RGB").crop((0, 0, opened.width, min(194, opened.height)))
    logo.thumbnail((300, 145), Image.Resampling.LANCZOS)
    canvas.paste(logo, ((SIZE[0] - logo.width) // 2, 10))


def _wrapped(draw: ImageDraw.ImageDraw, text: str, *, max_width: int, max_lines: int,
             start: int, minimum: int, weight: int = 800) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in range(start, minimum - 1, -2):
        face = _font(size, weight)
        lines: list[str] = []
        for paragraph in text.splitlines() or [""]:
            current = ""
            for word in paragraph.split():
                candidate = f"{current} {word}".strip()
                if draw.textlength(candidate, font=face) <= max_width:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
        if len(lines) <= max_lines:
            return face, lines
    raise ComposeError("O texto aprovado não cabe na arte.")


def _center(draw: ImageDraw.ImageDraw, lines: list[str], face: ImageFont.FreeTypeFont,
            top: int, *, colors: list[str] | None = None, spacing: int = 7) -> int:
    step = face.size + spacing
    for index, line in enumerate(lines):
        fill = colors[index] if colors else WHITE
        draw.text((543, top + index * step + 5), line, font=face, fill="#000000",
                  anchor="ma", stroke_width=2, stroke_fill="#000000")
        draw.text((540, top + index * step), line, font=face, fill=fill,
                  anchor="ma", stroke_width=1, stroke_fill=fill)
    return top + len(lines) * step


def _footer(canvas: Image.Image, *, position: int, label: str) -> None:
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((190, 1232, 890, 1315), 42, fill="#080909", outline=GOLD, width=3)
    draw.line((204, 1235, 365, 1235), fill=CYAN, width=4)
    draw.line((715, 1312, 876, 1312), fill=MAGENTA, width=4)
    draw.text((540, 1273), label, font=_font(30, 750), fill=WHITE, anchor="mm")
    draw.text((946, 1273), f"{position}/3", font=_font(24, 650), fill=MUTED, anchor="mm")


def _panel(canvas: Image.Image, box: tuple[int, int, int, int], opacity: int = 205) -> None:
    overlay = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rounded_rectangle(box, 32, fill=(5, 6, 6, opacity),
                                              outline=(255, 197, 46, 125), width=2)
    canvas.alpha_composite(overlay)


def _cover(record: dict) -> Image.Image:
    canvas = _master(record["id"], slide=1)
    _logo(canvas)
    draw = ImageDraw.Draw(canvas)
    accent = ACCENTS[record["id"]]
    prefix = record["question"][:-len(accent)].strip() if record["question"].endswith(accent) else record["question"]
    face, lines = _wrapped(draw, prefix, max_width=940, max_lines=3, start=68, minimum=46)
    bottom = _center(draw, lines, face, 180)
    face2, lines2 = _wrapped(draw, accent, max_width=940, max_lines=2, start=94, minimum=58)
    bottom = _center(draw, lines2, face2, bottom - 4, colors=[GOLD] * len(lines2), spacing=0)
    draw.arc((250, bottom - 14, 830, bottom + 66), 194, 346, fill=GOLD, width=6)
    _footer(canvas, position=1, label="Deslize para descobrir  »")
    return canvas.convert("RGB")


def _answer(record: dict) -> Image.Image:
    canvas = _master(record["id"], slide=2)
    _logo(canvas)
    _panel(canvas, (62, 170, 1018, 610), 222)
    draw = ImageDraw.Draw(canvas)
    draw.text((540, 205), "RESPOSTA", font=_font(23, 700), fill=GOLD, anchor="ma")
    face, lines = _wrapped(draw, record["answer"], max_width=850, max_lines=7,
                           start=54, minimum=34, weight=750)
    total = len(lines) * (face.size + 9)
    _center(draw, lines, face, 400 - total // 2, spacing=9)
    _footer(canvas, position=2, label="Continue deslizando  »")
    return canvas.convert("RGB")


def _cta(record: dict) -> Image.Image:
    canvas = _master(record["id"], slide=3)
    _logo(canvas)
    _panel(canvas, (70, 178, 1010, 695), 224)
    draw = ImageDraw.Draw(canvas)
    _center(draw, ["Escolha seu modelo e", "fale com a gente"], _font(57), 210,
            colors=[WHITE, GOLD], spacing=5)
    draw.rounded_rectangle((145, 420, 935, 535), 25, fill="#090a0a", outline=CYAN, width=4)
    draw.text((540, 477), WEBSITE, font=_font(41, 750), fill=WHITE, anchor="mm")
    draw.rounded_rectangle((145, 560, 935, 675), 25, fill="#090a0a", outline=MAGENTA, width=4)
    draw.text((540, 617), "WhatsApp " + PHONE, font=_font(37, 750), fill=WHITE, anchor="mm")
    _footer(canvas, position=3, label="Peça seu orçamento  »")
    return canvas.convert("RGB")


def render(ident: str) -> list[Image.Image]:
    record = item(ident)
    if ident == "formas-de-envio":
        names = ("shipping-cover-approved.png", "shipping-answer-approved.png", "shipping-cta-approved.png")
        return [_cover_image(REFERENCE / name) for name in names]
    return [_cover(record), _answer(record), _cta(record)]


def save(ident: str, directory: Path) -> dict:
    directory = Path(directory)
    if directory.is_symlink():
        raise ComposeError("O destino do carrossel precisa ser local.")
    directory.mkdir(parents=True, exist_ok=True)
    outputs = []
    for position, image in enumerate(render(ident), 1):
        path = directory / f"{ident}-{position:02d}.jpg"
        image.save(path, "JPEG", quality=95, subsampling=0, optimize=True)
        outputs.append({"position": position, "filename": path.name,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {"version": VERSION, "rules_hash": rules_hash(), "faq_id": ident,
                "size": list(SIZE), "slides": outputs}
    (directory / f"{ident}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
