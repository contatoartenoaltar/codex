"""Leitura isolada de vídeos prontos para Reels em uma pasta do Google Drive."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import drive_source


VIDEO_MIMES = {"video/mp4": ".mp4", "video/quicktime": ".mov"}
CONFIG_FILE = "reels-drive-source.json"
MAX_VIDEO_BYTES = 1_000_000_000
CHUNK_BYTES = 1024 * 1024


class ReelDriveError(ValueError):
    """Erro seguro da origem de vídeos, sem incluir credenciais ou respostas brutas."""


def _video(item, *, limit=MAX_VIDEO_BYTES):
    if not isinstance(item, dict):
        raise ReelDriveError("Metadados de vídeo inválidos no catálogo do Drive.")
    try:
        ident = drive_source.identifier(item.get("id"))
    except drive_source.DriveError:
        raise ReelDriveError("Identificador de vídeo inválido no catálogo do Drive.") from None
    mime = item.get("mimeType")
    if mime not in VIDEO_MIMES:
        raise ReelDriveError("A pasta de Reels aceita somente arquivos MP4 ou MOV.")
    name = item.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 255:
        raise ReelDriveError("Nome de vídeo inválido no catálogo do Drive.")
    if Path(name).suffix.lower() != VIDEO_MIMES[mime]:
        raise ReelDriveError("A extensão do vídeo não corresponde ao formato informado pelo Drive.")
    try:
        size = int(item.get("size"))
    except (TypeError, ValueError):
        raise ReelDriveError("Tamanho de vídeo inválido no catálogo do Drive.") from None
    if isinstance(item.get("size"), bool) or size <= 0 or size > limit:
        raise ReelDriveError("O vídeo excede o limite seguro para processamento.")
    checksum = item.get("md5Checksum")
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{32}", checksum):
        raise ReelDriveError("O Drive não informou uma verificação válida para o vídeo.")
    path = item.get("path", [name])
    if (not isinstance(path, list) or not path or
            any(not isinstance(part, str) or not part for part in path)):
        raise ReelDriveError("Caminho de vídeo inválido no catálogo do Drive.")
    return {"id": ident, "name": name, "mimeType": mime, "size": size,
            "md5Checksum": checksum, "path": list(path),
            **({"modifiedTime": item["modifiedTime"]}
               if isinstance(item.get("modifiedTime"), str) else {})}


def configure(directory, source):
    """Configura somente a pasta de Reels; não altera a origem das imagens."""
    directory = Path(directory)
    try:
        ident = drive_source.folder_id(source)
        info = drive_source.account_info(directory)
        drive_source.write_private(directory / CONFIG_FILE, {
            "provider": "google_drive", "folder_id": ident,
            "role": "finished_reels", "access_verified": False,
        })
    except drive_source.DriveError as error:
        raise ReelDriveError(str(error)) from None
    return info["client_email"]


def catalog(directory, client=None):
    """Retorna somente MP4/MOV completos, sem baixar ou modificar arquivos do Drive."""
    directory = Path(directory)
    try:
        config = drive_source.read_json(directory / CONFIG_FILE)
        root = drive_source.identifier(config.get("folder_id"))
        client = client or drive_source.DriveClient(drive_source.credentials(directory))
        source = client.catalog(root)
    except drive_source.DriveError as error:
        raise ReelDriveError(str(error)) from None
    if (not isinstance(source, dict) or source.get("complete") is not True or
            source.get("folder_id") != root or not isinstance(source.get("files"), list)):
        raise ReelDriveError("O Drive não confirmou um catálogo completo de Reels.")
    videos = []
    invalid_videos = 0
    for item in source["files"]:
        if isinstance(item, dict) and item.get("mimeType") in VIDEO_MIMES:
            try:
                videos.append(_video(item))
            except ReelDriveError:
                invalid_videos += 1
    videos.sort(key=lambda item: (tuple(item["path"]), item["id"]))
    return {"provider": "google_drive", "folder_id": root,
            "folder_name": source.get("folder_name", ""),
            "checked_at": source.get("checked_at"), "complete": True,
            "total_videos": len(videos), "files": videos,
            "skipped_non_video": len(source["files"]) - len(videos) - invalid_videos,
            "skipped_invalid_video": invalid_videos}


class VideoDriveClient(drive_source.DriveClient):
    """Cliente de download limitado a um vídeo conhecido do catálogo."""

    def download_video(self, item, destination, *, limit=MAX_VIDEO_BYTES):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_VIDEO_BYTES:
            raise ReelDriveError("Limite de download de vídeo inválido.")
        metadata = _video(item, limit=limit)
        destination = Path(destination)
        parent = destination.parent
        if (not parent.is_dir() or parent.is_symlink() or destination.exists() or
                destination.is_symlink()):
            raise ReelDriveError("Use um novo arquivo local em um diretório seguro para o Reel.")

        params = urllib.parse.urlencode({"alt": "media", "supportsAllDrives": "true"})
        url = f"{drive_source.API}/{metadata['id']}?{params}"
        headers = {"Accept": metadata["mimeType"]}
        descriptor, temporary = tempfile.mkstemp(
            dir=parent, prefix=".reel-drive-", suffix=VIDEO_MIMES[metadata["mimeType"]])
        written = 0
        digest = hashlib.md5(usedforsecurity=False)
        head = b""
        try:
            self.credential.before_request(self.transport, "GET", url, headers)
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                response = self.opener.open(request, timeout=25)
            except urllib.error.HTTPError as error:
                if error.code in (401, 403, 404):
                    raise ReelDriveError(
                        "Acesso ao vídeo não confirmado. Confira o compartilhamento da pasta como Leitor.") from None
                raise ReelDriveError("Falha temporária ao baixar o vídeo do Drive.") from None
            with os.fdopen(descriptor, "wb") as stream, response:
                descriptor = -1
                while True:
                    chunk = response.read(min(CHUNK_BYTES, limit - written + 1))
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > limit or written > metadata["size"]:
                        raise ReelDriveError("O vídeo recebido excedeu o tamanho confirmado no catálogo.")
                    if len(head) < 12:
                        head += chunk[:12 - len(head)]
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if written != metadata["size"]:
                raise ReelDriveError("O vídeo recebido não corresponde ao tamanho confirmado no catálogo.")
            if len(head) < 12 or head[4:8] != b"ftyp":
                raise ReelDriveError("O arquivo recebido não contém uma estrutura MP4 válida.")
            if digest.hexdigest() != metadata["md5Checksum"]:
                raise ReelDriveError(
                    "O vídeo mudou desde a consulta. Atualize o catálogo antes de tentar novamente.")
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
            return {"path": str(destination), "bytes": written,
                    "md5": metadata["md5Checksum"], "drive_id": metadata["id"]}
        except ReelDriveError:
            raise
        except Exception:
            raise ReelDriveError(
                "Não foi possível baixar o vídeo do Drive. O arquivo de origem foi preservado.") from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            Path(temporary).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Configure or inspect the read-only Drive source for finished Reels.")
    commands = parser.add_subparsers(dest="command", required=True)
    configure_command = commands.add_parser(
        "configure", help="Save the dedicated Drive folder without enabling publishing.")
    configure_command.add_argument("--directory", required=True, type=Path)
    configure_command.add_argument("--folder", required=True)
    status_command = commands.add_parser(
        "status", help="Verify read-only access and list accepted MP4 counts.")
    status_command.add_argument("--directory", required=True, type=Path)
    arguments = parser.parse_args(argv)

    if arguments.command == "configure":
        email = configure(arguments.directory, arguments.folder)
        print(json.dumps({
            "configured": True,
            "publishing_enabled": False,
            "share_folder_with": email,
        }, sort_keys=True))
        return
    result = catalog(arguments.directory)
    print(json.dumps({
        "complete": result["complete"],
        "folder_name": result["folder_name"],
        "total_videos": result["total_videos"],
        "skipped_non_video": result["skipped_non_video"],
        "skipped_invalid_video": result["skipped_invalid_video"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
