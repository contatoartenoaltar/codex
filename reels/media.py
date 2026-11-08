"""Temporary, capability-based MP4 delivery for Instagram processing.

This module has no knowledge of the Reels queue schema.  The queue supplies a
resolver that maps an opaque token to a short-lived :class:`MediaGrant`.  Raw
Drive files and local filenames are never accepted in the URL.
"""
from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
import os
from pathlib import Path
import re
import secrets
import stat
import time
from typing import Callable, Iterable


PATH_PREFIX = "/reels-media/"
TOKEN = re.compile(r"[A-Za-z0-9_-]{43,128}")
FILENAME = re.compile(r"(?:[a-f0-9]{32}|[a-f0-9]{64})\.mp4")
MAX_VIDEO = 50 * 1024 * 1024
CHUNK = 256 * 1024


@dataclass(frozen=True)
class MediaGrant:
    """One revocable capability. ``filename`` is relative to ``media/``."""

    filename: str
    expires_at: int
    revoked: bool = False


Resolver = Callable[[str], MediaGrant | None]


def issue_token() -> str:
    """Create a queue-compatible opaque capability with 256 bits of entropy."""

    return secrets.token_hex(32)


def url_path(token: str) -> str:
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise ValueError("Token temporário de vídeo inválido.")
    return PATH_PREFIX + token + ".mp4"


def _response(start_response, status: int, body: bytes = b"", headers=()) -> list[bytes]:
    values = [
        ("Content-Type", "text/plain; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store, max-age=0"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
        ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"),
    ]
    values.extend(headers)
    start_response(f"{status} {HTTPStatus(status).phrase}", values)
    return [body]


def _range(value: str | None, size: int) -> tuple[int, int] | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.startswith("bytes="):
        raise ValueError("range")
    spec = value[6:]
    if "," in spec or not re.fullmatch(r"(?:\d+-\d*|-\d+)", spec):
        raise ValueError("range")
    left, right = spec.split("-", 1)
    if left:
        start = int(left)
        end = int(right) if right else size - 1
        if start >= size or end < start:
            raise ValueError("range")
        return start, min(end, size - 1)
    suffix = int(right)
    if suffix <= 0:
        raise ValueError("range")
    suffix = min(suffix, size)
    return size - suffix, size - 1


class _FileBody:
    def __init__(self, descriptor: int, start: int, length: int):
        self.descriptor = descriptor
        self.start = start
        self.length = length

    def __iter__(self):
        remaining = self.length
        try:
            os.lseek(self.descriptor, self.start, os.SEEK_SET)
            while remaining:
                data = os.read(self.descriptor, min(CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data
        finally:
            if self.descriptor is not None:
                descriptor, self.descriptor = self.descriptor, None
                os.close(descriptor)

    def close(self):
        if self.descriptor is not None:
            descriptor, self.descriptor = self.descriptor, None
            os.close(descriptor)


def serve(environ: dict, start_response, directory: Path, resolver: Resolver,
          *, now: int | None = None) -> Iterable[bytes]:
    """Serve one granted MP4 with HEAD and single-range GET support.

    Unknown, expired, revoked and malformed capabilities all return the same
    404 response so callers cannot use this endpoint to enumerate queue data.
    """

    if environ.get("QUERY_STRING"):
        return _response(start_response, 400, b"Bad request")
    if "HTTP_ORIGIN" in environ:
        return _response(start_response, 403, b"Forbidden")
    method = environ.get("REQUEST_METHOD", "")
    if method not in ("GET", "HEAD"):
        return _response(start_response, 405, b"Method not allowed", (("Allow", "GET, HEAD"),))
    path = environ.get("PATH_INFO", "")
    match = re.fullmatch(re.escape(PATH_PREFIX) + r"([A-Za-z0-9_-]{43,128})\.mp4", path)
    if not match:
        return _response(start_response, 404, b"Not found")
    token = match.group(1)
    try:
        grant = resolver(token)
    except Exception:
        grant = None
    current = int(time.time()) if now is None else now
    if (not isinstance(grant, MediaGrant) or grant.revoked or
            type(grant.expires_at) is not int or grant.expires_at <= current or
            not isinstance(grant.filename, str) or not FILENAME.fullmatch(grant.filename)):
        return _response(start_response, 404, b"Not found")

    directory = Path(directory)
    media = directory / "media"
    target = media / grant.filename
    try:
        if (not directory.is_absolute() or directory.is_symlink() or media.is_symlink() or
                target.parent != media):
            raise OSError("unsafe")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or
                info.st_size > MAX_VIDEO or info.st_nlink != 1):
            raise OSError("unsafe")
        head = os.pread(descriptor, min(12, info.st_size), 0)
        if len(head) < 8 or head[4:8] != b"ftyp":
            raise OSError("invalid mp4")
    except OSError:
        if "descriptor" in locals():
            os.close(descriptor)
        return _response(start_response, 404, b"Not found")

    try:
        selected = _range(environ.get("HTTP_RANGE"), info.st_size)
    except ValueError:
        os.close(descriptor)
        return _response(start_response, 416, b"", (("Content-Range", f"bytes */{info.st_size}"),
                                                      ("Accept-Ranges", "bytes")))
    start, end = selected if selected is not None else (0, info.st_size - 1)
    length = end - start + 1
    status = 206 if selected is not None else 200
    headers = [
        ("Content-Type", "video/mp4"),
        ("Content-Length", str(length)),
        ("Accept-Ranges", "bytes"),
        ("Cache-Control", "no-store, max-age=0"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "no-referrer"),
        ("Content-Disposition", "inline"),
    ]
    if selected is not None:
        headers.append(("Content-Range", f"bytes {start}-{end}/{info.st_size}"))
    start_response(f"{status} {HTTPStatus(status).phrase}", headers)
    if method == "HEAD":
        os.close(descriptor)
        return []
    return _FileBody(descriptor, start, length)
