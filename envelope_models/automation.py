"""Gera cinco candidatos diários de envelopes sem tocar nos originais.

O fluxo nasce desativado. A IA cria somente a base visual; o título é composto
localmente para evitar letras deformadas. Cada resultado é validado e enviado
para a subpasta de revisão do tema no Google Drive.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, ImageStat

import drive_source


ZONE = ZoneInfo("America/Sao_Paulo")
DATABASE = "envelope-models.sqlite3"
CONFIG = "envelope-models.json"
APPLICATION_ID = 0x4141454D
OUTPUT_SIZE = (1492, 1054)
API = "https://api.openai.com/v1/images/edits"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
ENABLE_CONFIRMATION = "ENABLE-FIVE-ENVELOPE-MODELS-PER-DAY"
MAX_REFERENCE_BYTES = 20 * 1024 * 1024
MAX_GENERATED_BYTES = 25 * 1024 * 1024

THEMES = {
    "dizimos": {"title": "Dízimos", "terms": ("dízimo", "dizimo")},
    "ofertas": {"title": "Ofertas", "terms": ("oferta",)},
    "primicias": {"title": "Primícias", "terms": ("primícia", "primicia")},
    "santa-ceia": {"title": "Santa Ceia", "terms": ("santa ceia", "ceia")},
    "missoes": {"title": "Missões", "terms": ("missões", "missoes", "missão", "missao")},
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
    if not os.environ.get("ARTENOALTAR_IMAGE_AI_KEY"):
        raise EnvelopeError("Cadastre a chave específica da geração de imagens antes de ativar.")
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


def _theme_files(catalog, theme):
    terms = THEMES[theme]["terms"]
    candidates = []
    for item in catalog.get("files", []):
        name = item.get("name", "").casefold()
        if item.get("mimeType") in ("image/png", "image/jpeg") and any(term in name for term in terms):
            candidates.append(item)
    if not candidates:
        raise EnvelopeError(f"Nenhuma referência aprovada encontrada para {THEMES[theme]['title']}.")
    return candidates


def choose_reference(connection, catalog, theme):
    candidates = _theme_files(catalog, theme)
    usage = {row[0]: (row[1], row[2]) for row in connection.execute(
        "SELECT reference_id,COUNT(*),MAX(created_at) FROM outputs WHERE theme=? "
        "GROUP BY reference_id", (theme,))}
    # Novos modelos primeiro; depois, menor uso e uso mais antigo.
    candidates.sort(key=lambda item: (*usage.get(item["id"], (0, 0)), item["id"]))
    return candidates[0]


def _multipart(fields, files, boundary=None):
    boundary = boundary or "----ArteNoAltar" + secrets.token_hex(16)
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    for name, filename, mime, data in files:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{safe}\"\r\nContent-Type: {mime}\r\n\r\n".encode())
        body.extend(data)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _prompt(theme):
    title = THEMES[theme]["title"]
    return (
        "Crie a base visual de um novo envelope cristão brasileiro para o tema " + title + ". "
        "Use a imagem anexada somente como referência de qualidade, equilíbrio, riqueza visual e acabamento. "
        "Crie uma composição original, horizontal, elegante, própria para impressão, com imagens religiosas ou "
        "simbólicas coerentes com o tema. Varie cores e estilo sem copiar elementos específicos. Reserve uma área "
        "limpa e de alto contraste no terço esquerdo ou central para o título que será inserido depois. "
        "Não desenhe letras, palavras, números, logotipos, QR codes, marcas d'água, moldura de produto, mockup, "
        "envelope fotografado, mãos ou cenário externo. Entregue somente a arte plana frontal, preenchendo toda a imagem."
    )


class ImageClient:
    def __init__(self, key, opener=None, model=None):
        if not isinstance(key, str) or not key.strip():
            raise EnvelopeError("A geração de imagens ainda não foi configurada.")
        self.key = key.strip()
        self.model = model or os.environ.get("ARTENOALTAR_IMAGE_AI_MODEL", "gpt-image-1.5")
        self.opener = opener or urllib.request.build_opener(drive_source.NoRedirect())

    def generate(self, theme, reference, mime):
        body, content_type = _multipart({
            "model": self.model, "prompt": _prompt(theme), "size": "1536x1024",
            "quality": "high", "output_format": "png",
        }, [("image[]", "reference.png" if mime == "image/png" else "reference.jpg", mime, reference)])
        request = urllib.request.Request(API, data=body, method="POST", headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": content_type,
            "Accept": "application/json",
        })
        try:
            with self.opener.open(request, timeout=180) as response:
                raw = response.read(MAX_GENERATED_BYTES * 2)
            payload = json.loads(raw)
            encoded = payload["data"][0]["b64_json"]
            result = base64.b64decode(encoded, validate=True)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError,
                ValueError, TypeError, json.JSONDecodeError):
            raise EnvelopeError("A IA não conseguiu criar a base visual deste modelo.") from None
        if len(result) > MAX_GENERATED_BYTES:
            raise EnvelopeError("A imagem criada excedeu o limite seguro.")
        return result


def compose_title(raw, title):
    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.verify()
        with Image.open(io.BytesIO(raw)) as source:
            image = source.convert("RGB").resize(OUTPUT_SIZE, Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        raise EnvelopeError("A IA não retornou uma imagem PNG válida.") from None
    if ImageStat.Stat(image.resize((32, 32))).stddev[0] < 8:
        raise EnvelopeError("A base visual criada não possui detalhes suficientes.")
    font_path = Path(__file__).parents[1] / "design_assets/fonts/cormorantgaramond.ttf"
    font = ImageFont.truetype(str(font_path), 142)
    draw = ImageDraw.Draw(image)
    box = draw.textbbox((0, 0), title, font=font, stroke_width=2)
    width, height = box[2] - box[0], box[3] - box[1]
    x, y = 92, (OUTPUT_SIZE[1] - height) // 2
    # Sombra e placa translúcida clara tornam o título legível sem depender do fundo criado.
    overlay = Image.new("RGBA", OUTPUT_SIZE, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.rounded_rectangle((45, y - 65, min(x + width + 55, 950), y + height + 65),
                            radius=34, fill=(255, 252, 244, 205))
    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image)
    draw.text((x + 3, y + 5), title, font=font, fill=(0, 0, 0, 90), stroke_width=1)
    draw.text((x, y), title, font=font, fill=(117, 72, 21, 255), stroke_width=1,
              stroke_fill=(255, 246, 220, 255))
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
    image_client = image_client or ImageClient(os.environ.get("ARTENOALTAR_IMAGE_AI_KEY", ""))
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
            final = compose_title(generated, definition["title"])
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
