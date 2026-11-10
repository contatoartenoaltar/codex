"""Gera cinco candidatos diários de envelopes sem tocar nos originais.

O fluxo nasce desativado. A IA cria somente a base visual; o título é composto
localmente para evitar letras deformadas. Cada resultado é validado e enviado
para a subpasta de revisão do tema no Google Drive.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import urllib.request
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, ImageStat

import drive_source


ZONE = ZoneInfo("America/Sao_Paulo")
DATABASE = "envelope-models.sqlite3"
CONFIG = "envelope-models.json"
APPLICATION_ID = 0x4141454D
OUTPUT_SIZE = (1492, 1054)
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
ENABLE_CONFIRMATION = "ENABLE-FIVE-ENVELOPE-MODELS-PER-DAY"
MAX_REFERENCE_BYTES = 20 * 1024 * 1024

THEMES = {
    "dizimos": {"title": "Dízimos", "phrase": "Deus ama quem dá com alegria",
                "citation": "2 CORÍNTIOS 9:7"},
    "ofertas": {"title": "Ofertas", "phrase": "Plantando hoje, colhemos amanhã",
                "citation": "2 CORÍNTIOS 9:6"},
    "primicias": {"title": "Primícias", "phrase": "Honra ao Senhor com os teus bens",
                  "citation": "PROVÉRBIOS 3:9"},
    "santa-ceia": {"title": "Santa Ceia", "phrase": "Fazei isto em memória de mim",
                   "citation": "1 CORÍNTIOS 11:24"},
    "missoes": {"title": "Missões", "phrase": "Ide por todo o mundo e pregai o evangelho",
                "citation": "MARCOS 16:15"},
}

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS policy(
        id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL,
        source_folder TEXT NOT NULL, configured_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS outputs(
        id TEXT PRIMARY KEY, creation_day TEXT NOT NULL, theme TEXT NOT NULL,
        reference_id TEXT NOT NULL, reference_md5 TEXT NOT NULL,
        filename TEXT NOT NULL, drive_id TEXT NOT NULL DEFAULT '',
        sha256 TEXT NOT NULL, state TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL, UNIQUE(creation_day,theme))""",
    "CREATE INDEX IF NOT EXISTS envelope_reference_rotation ON outputs(theme,reference_id,created_at)",
)


class EnvelopeError(ValueError):
    pass


def _identifier(value):
    try:
        return drive_source.identifier(value)
    except drive_source.DriveError as error:
        raise EnvelopeError(str(error)) from None


def _private_json(path, value):
    drive_source.write_private(path, value)


def _read_config(directory):
    try:
        value = drive_source.read_json(Path(directory) / CONFIG)
    except drive_source.DriveError as error:
        raise EnvelopeError(str(error)) from None
    folders = value.get("output_folders")
    if not isinstance(folders, dict) or set(folders) != set(THEMES):
        raise EnvelopeError("A configuração das cinco pastas de saída está incompleta.")
    return value | {"source_folder": _identifier(value.get("source_folder")),
                    "output_folders": {key: _identifier(folders[key]) for key in THEMES}}


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / DATABASE

    def initialize(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.directory.is_symlink() or self.path.is_symlink():
            raise EnvelopeError("O armazenamento dos modelos não aceita links simbólicos.")
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        with sqlite3.connect(self.path) as connection:
            identity = connection.execute("PRAGMA application_id").fetchone()[0]
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if identity not in (0, APPLICATION_ID) or (identity == 0 and tables):
                raise EnvelopeError("O banco existente não pertence aos modelos de envelopes.")
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            for statement in SCHEMA:
                connection.execute(statement)

    @contextmanager
    def connect(self):
        if not self.path.is_file() or self.path.is_symlink():
            raise EnvelopeError("Inicialize o armazenamento dos modelos.")
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise EnvelopeError("O banco existente não pertence aos modelos de envelopes.")
            with connection:
                yield connection
        finally:
            connection.close()


def configure(directory, source_folder, output_folders):
    directory = Path(directory)
    if set(output_folders) != set(THEMES):
        raise EnvelopeError("Informe exatamente uma pasta para cada um dos cinco temas.")
    source = _identifier(source_folder)
    outputs = {key: _identifier(output_folders[key]) for key in THEMES}
    if source in outputs.values() or len(set(outputs.values())) != len(THEMES):
        raise EnvelopeError("Origem e pastas de saída precisam ser distintas.")
    store = Store(directory)
    store.initialize()
    now = int(datetime.now(ZONE).timestamp())
    with store.connect() as connection:
        connection.execute("INSERT OR REPLACE INTO policy VALUES(1,0,?,?)", (source, now))
    _private_json(directory / CONFIG, {
        "source_folder": source, "output_folders": outputs,
        "timezone": str(ZONE), "daily_total": len(THEMES), "enabled": False,
    })
    return status(store)


def enable(store, confirmation):
    if confirmation != ENABLE_CONFIRMATION:
        raise EnvelopeError("Confirmação de ativação inválida.")
    _read_config(store.directory)
    with store.connect() as connection:
        connection.execute("UPDATE policy SET enabled=1 WHERE id=1")
    config = _read_config(store.directory)
    _private_json(store.directory / CONFIG, config | {"enabled": True})
    return status(store)


def status(store, now=None):
    with store.connect() as connection:
        policy = connection.execute("SELECT * FROM policy WHERE id=1").fetchone()
        counts = dict(connection.execute(
            "SELECT state,COUNT(*) FROM outputs GROUP BY state").fetchall())
        recent = [dict(row) for row in connection.execute(
            "SELECT creation_day,theme,filename,drive_id,state,error FROM outputs "
            "ORDER BY created_at DESC LIMIT 10")]
    return {"configured": policy is not None, "enabled": bool(policy and policy["enabled"]),
            "daily_total": len(THEMES), "counts": counts, "recent": recent}


def _reference_files(catalog):
    candidates = [item for item in catalog.get("files", [])
                  if item.get("mimeType") in ("image/png", "image/jpeg")]
    if not candidates:
        raise EnvelopeError("A pasta não contém referências PNG ou JPEG aprovadas.")
    return candidates


def choose_reference(connection, catalog, theme):
    if theme not in THEMES:
        raise EnvelopeError("Tema de envelope inválido.")
    candidates = _reference_files(catalog)
    usage = {row[0]: (row[1], row[2]) for row in connection.execute(
        "SELECT reference_id,COUNT(*),MAX(created_at) FROM outputs GROUP BY reference_id")}
    # Novos modelos primeiro; depois, menor uso e uso mais antigo.
    candidates.sort(key=lambda item: (*usage.get(item["id"], (0, 0)), item["id"]))
    return candidates[0]


def _palette(reference):
    """Extrai cores da referência sem copiar sua composição ou seus elementos."""
    try:
        with Image.open(io.BytesIO(reference)) as source:
            sample = source.convert("RGB").resize((96, 68), Image.Resampling.LANCZOS)
            colors = sample.quantize(colors=6).convert("RGB").getcolors(96 * 68)
    except (OSError, ValueError):
        raise EnvelopeError("A referência selecionada não é uma imagem válida.") from None
    ordered = [color for _, color in sorted(colors or [], reverse=True)]
    if len(ordered) < 3:
        return [(245, 238, 219), (176, 124, 48), (44, 71, 53)]
    return ordered


def _mix(first, second, amount):
    return tuple(round(a * (1 - amount) + b * amount) for a, b in zip(first, second))


def _symbol(draw, theme, color):
    """Símbolos vetoriais simples e originais, adequados a impressão."""
    width = 15
    if theme == "santa-ceia":
        draw.ellipse((1100, 280, 1370, 420), outline=color, width=width)
        draw.arc((1100, 335, 1370, 690), 0, 180, fill=color, width=width)
        draw.line((1235, 690, 1235, 800), fill=color, width=width)
        draw.line((1135, 800, 1335, 800), fill=color, width=width)
    elif theme == "missoes":
        draw.ellipse((1060, 220, 1400, 560), outline=color, width=width)
        draw.arc((1135, 220, 1325, 560), 85, 275, fill=color, width=width)
        draw.arc((1135, 220, 1325, 560), 265, 95, fill=color, width=width)
        draw.arc((1060, 315, 1400, 465), 0, 360, fill=color, width=width)
        draw.line((1230, 575, 1230, 815), fill=color, width=width)
        draw.line((1140, 650, 1320, 650), fill=color, width=width)
    elif theme == "primicias":
        draw.line((1230, 235, 1230, 820), fill=color, width=width)
        for y in range(290, 730, 75):
            draw.arc((1080, y - 45, 1235, y + 75), 260, 75, fill=color, width=width)
            draw.arc((1225, y - 45, 1380, y + 75), 105, 280, fill=color, width=width)
    elif theme == "ofertas":
        draw.arc((1050, 420, 1235, 785), 250, 80, fill=color, width=width)
        draw.arc((1225, 420, 1410, 785), 100, 290, fill=color, width=width)
        draw.line((1230, 745, 1230, 350), fill=color, width=width)
        draw.ellipse((1060, 255, 1235, 410), outline=color, width=width)
        draw.ellipse((1225, 210, 1410, 390), outline=color, width=width)
    else:
        draw.ellipse((1080, 315, 1380, 780), outline=color, width=width)
        draw.arc((1040, 220, 1240, 520), 300, 90, fill=color, width=width)
        draw.arc((1220, 220, 1420, 520), 90, 240, fill=color, width=width)
        draw.line((1230, 255, 1230, 650), fill=color, width=width)
        draw.line((1160, 355, 1300, 355), fill=color, width=width)


class LocalDesignGenerator:
    """Geração procedural sem API, assinatura, conta ou cobrança por imagem."""
    def generate(self, theme, reference, mime):
        if mime not in ("image/png", "image/jpeg"):
            raise EnvelopeError("A referência precisa ser PNG ou JPEG.")
        colors = _palette(reference)
        seed = int(hashlib.sha256(theme.encode() + reference[:4096]).hexdigest()[:8], 16)
        primary = colors[seed % len(colors)]
        secondary = colors[(seed // 7 + 1) % len(colors)]
        light = _mix(primary, (255, 253, 246), .78)
        dark = _mix(secondary, (20, 25, 24), .42)
        gradient = Image.new("RGB", (1, 1024), light)
        gradient.putdata([_mix(light, secondary, y / 1023 * .34) for y in range(1024)])
        image = gradient.resize((1536, 1024))
        draw = ImageDraw.Draw(image, "RGBA")
        # Curvas e formas variam deterministicamente conforme tema e referência.
        shift = 40 + seed % 180
        draw.ellipse((850 - shift, -260, 1740 - shift, 620), fill=(*dark, 38))
        draw.ellipse((940 + shift // 3, 430, 1670 + shift // 3, 1160), fill=(*primary, 48))
        draw.polygon(((0, 850), (650, 770 + shift // 5), (1040, 1024), (0, 1024)),
                     fill=(*dark, 215))
        draw.polygon(((0, 920), (720, 850 + shift // 7), (920, 1024), (0, 1024)),
                     fill=(*secondary, 210))
        _symbol(draw, theme, (*dark, 195))
        for x in range(55, 900, 95):
            draw.ellipse((x, 70, x + 6, 76), fill=(*dark, 90))
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()


def compose_title(raw, title, theme=None):
    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.verify()
        with Image.open(io.BytesIO(raw)) as source:
            image = source.convert("RGB").resize(OUTPUT_SIZE, Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        raise EnvelopeError("A IA não retornou uma imagem PNG válida.") from None
    if ImageStat.Stat(image.resize((32, 32))).stddev[0] < 8:
        raise EnvelopeError("A base visual criada não possui detalhes suficientes.")
    assets = Path(__file__).parents[1] / "design_assets/fonts"
    title_font = ImageFont.truetype(str(assets / "cormorantgaramond.ttf"), 174)
    label_font = ImageFont.truetype(str(assets / "manrope.ttf"), 27)
    phrase_font = ImageFont.truetype(str(assets / "cormorantgaramond.ttf"), 46)
    citation_font = ImageFont.truetype(str(assets / "manrope.ttf"), 21)
    x, y = 88, 315
    details = THEMES.get(theme, {})
    phrase = details.get("phrase", "")
    citation = details.get("citation", "")
    # Painel em degradê preserva a riqueza do fundo e garante leitura para impressão.
    overlay = Image.new("RGBA", OUTPUT_SIZE, (0, 0, 0, 0))
    strip = Image.new("RGBA", (940, OUTPUT_SIZE[1]), (255, 252, 244, 0))
    mask = Image.new("L", (940, 1))
    mask.putdata([max(0, 218 - round(position / 939 * 218)) for position in range(940)])
    strip.putalpha(mask.resize(strip.size))
    overlay.alpha_composite(strip, (0, 0))
    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image)
    draw.text((x, y - 66), "ENVELOPE PARA", font=label_font, fill=(67, 66, 61, 230))
    draw.text((x + 4, y + 7), title, font=title_font, fill=(0, 0, 0, 82), stroke_width=1)
    draw.text((x, y), title, font=title_font, fill=(117, 72, 21, 255), stroke_width=1,
              stroke_fill=(255, 246, 220, 255))
    title_box = draw.textbbox((x, y), title, font=title_font)
    line_y = title_box[3] + 24
    draw.rounded_rectangle((x, line_y, x + 125, line_y + 6), 3, fill=(178, 126, 47, 255))
    if phrase:
        draw.text((x, line_y + 28), phrase, font=phrase_font, fill=(42, 48, 43, 245))
    if citation:
        draw.text((x, line_y + 91), citation, font=citation_font, fill=(86, 84, 76, 235))
    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


def writable_credentials(directory):
    info = drive_source.account_info(Path(directory))
    try:
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_info(info, scopes=[DRIVE_SCOPE])
    except Exception:
        raise EnvelopeError("A credencial de saída do Drive não pôde ser validada.") from None


class DriveOutputClient:
    def __init__(self, credential, opener=None):
        self.credential = credential
        self.opener = opener or urllib.request.build_opener(drive_source.NoRedirect())
        self.transport = drive_source.TokenTransport()

    def upload_png(self, folder, filename, data):
        folder = _identifier(folder)
        metadata = json.dumps({"name": filename, "parents": [folder]}, ensure_ascii=False).encode()
        boundary = "ArteNoAltar" + secrets.token_hex(16)
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode() +
                metadata + f"\r\n--{boundary}\r\nContent-Type: image/png\r\n\r\n".encode() +
                data + f"\r\n--{boundary}--\r\n".encode())
        url = UPLOAD_API + "?uploadType=multipart&supportsAllDrives=true&fields=id,name,parents,md5Checksum"
        headers = {"Content-Type": f"multipart/related; boundary={boundary}", "Accept": "application/json"}
        try:
            self.credential.before_request(self.transport, "POST", url, headers)
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with self.opener.open(request, timeout=90) as response:
                result = json.loads(response.read(65537))
        except Exception:
            raise EnvelopeError("Não foi possível salvar o candidato na pasta de saída do Drive.") from None
        expected = hashlib.md5(data, usedforsecurity=False).hexdigest()
        if (not isinstance(result, dict) or result.get("name") != filename or
                result.get("parents") != [folder] or result.get("md5Checksum") != expected):
            raise EnvelopeError("O Drive não confirmou a integridade do candidato salvo.")
        return _identifier(result.get("id"))


def run(store, *, source_client=None, image_client=None, output_client=None, now=None):
    now = (now or datetime.now(ZONE)).astimezone(ZONE)
    day = now.date().isoformat()
    config = _read_config(store.directory)
    with store.connect() as connection:
        policy = connection.execute("SELECT * FROM policy WHERE id=1").fetchone()
        if policy is None or not policy["enabled"]:
            return {"status": "disabled", "created": 0, "day": day}
    source_client = source_client or drive_source.DriveClient(drive_source.credentials(store.directory))
    image_client = image_client or LocalDesignGenerator()
    output_client = output_client or DriveOutputClient(writable_credentials(store.directory))
    catalog = source_client.catalog(config["source_folder"])
    created, skipped = [], []
    for theme, definition in THEMES.items():
        with store.connect() as connection:
            existing = connection.execute(
                "SELECT state,drive_id FROM outputs WHERE creation_day=? AND theme=?", (day, theme)).fetchone()
            if existing and existing["state"] != "failed":
                skipped.append(theme)
                continue
            if existing:
                connection.execute("DELETE FROM outputs WHERE creation_day=? AND theme=?", (day, theme))
            reference = choose_reference(connection, catalog, theme)
            row_id = secrets.token_hex(16)
            timestamp = int(now.timestamp())
            connection.execute("""INSERT INTO outputs
                (id,creation_day,theme,reference_id,reference_md5,filename,drive_id,sha256,state,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (row_id, day, theme, reference["id"], reference.get("md5Checksum", ""),
                 "", "", "", "processing", timestamp))
        try:
            reference_data = source_client.download_image(reference, limit=MAX_REFERENCE_BYTES)
            generated = image_client.generate(theme, reference_data, reference["mimeType"])
            final = compose_title(generated, definition["title"], theme)
            digest = hashlib.sha256(final).hexdigest()
            filename = f"{day}-{theme}-{digest[:10]}.png"
            drive_id = output_client.upload_png(config["output_folders"][theme], filename, final)
            with store.connect() as connection:
                connection.execute("""UPDATE outputs SET filename=?,drive_id=?,sha256=?,state='review'
                    WHERE id=? AND state='processing'""", (filename, drive_id, digest, row_id))
        except Exception as error:
            with store.connect() as connection:
                connection.execute("UPDATE outputs SET state='failed',error=? WHERE id=?",
                                   (str(error)[:300], row_id))
            raise
        created.append({"theme": definition["title"], "filename": filename, "drive_id": drive_id})
    return {"status": "complete", "day": day, "created": created, "skipped": skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    configure_parser = sub.add_parser("configure")
    configure_parser.add_argument("--source", required=True)
    for theme in THEMES:
        configure_parser.add_argument("--" + theme, required=True)
    enable_parser = sub.add_parser("enable")
    enable_parser.add_argument("--confirm", required=True)
    sub.add_parser("status")
    sub.add_parser("run")
    args = parser.parse_args()
    import app
    store = Store(app.DB.parent / "envelope-models-live")
    store.initialize()
    try:
        if args.command == "configure":
            outputs = {theme: getattr(args, theme.replace("-", "_")) for theme in THEMES}
            result = configure(store.directory, args.source, outputs)
        elif args.command == "enable":
            result = enable(store, args.confirm)
        elif args.command == "run":
            result = run(store)
        else:
            result = status(store)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (EnvelopeError, drive_source.DriveError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
