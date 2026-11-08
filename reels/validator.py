"""Validação somente leitura de MP4 pronto para a fila de Reels."""
from __future__ import annotations

import json
import math
import mmap
from pathlib import Path
import shutil
import subprocess


MAX_PROBE_OUTPUT = 256 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024


class VideoValidationError(ValueError):
    pass


def _integer(data, offset, size):
    if offset < 0 or size not in (2, 4, 8) or offset + size > len(data):
        raise VideoValidationError("O MP4 possui metadados incompletos.")
    return int.from_bytes(data[offset:offset + size], "big")


def _boxes(data, start, end):
    """Yield bounded ISO-BMFF boxes without decoding media payloads."""
    position = start
    count = 0
    while position < end:
        count += 1
        if count > 10000 or end - position < 8:
            raise VideoValidationError("O MP4 possui uma estrutura inválida.")
        size = _integer(data, position, 4)
        kind = bytes(data[position + 4:position + 8])
        header = 8
        if size == 1:
            if end - position < 16:
                raise VideoValidationError("O MP4 possui uma estrutura inválida.")
            size = _integer(data, position + 8, 8)
            header = 16
        elif size == 0:
            size = end - position
        box_end = position + size
        if size < header or box_end > end or not kind.isascii():
            raise VideoValidationError("O MP4 possui uma estrutura inválida.")
        yield position, kind, position + header, box_end
        position = box_end
    if position != end:
        raise VideoValidationError("O MP4 possui uma estrutura inválida.")


def _children(data, start, end, kind):
    return [box for box in _boxes(data, start, end) if box[1] == kind]


def _one(data, start, end, kind):
    values = _children(data, start, end, kind)
    if len(values) != 1:
        raise VideoValidationError("O MP4 não informou as faixas esperadas.")
    return values[0]


def _media_time(data, box):
    _, _, payload, end = box
    if payload + 4 > end:
        raise VideoValidationError("O MP4 não informou duração válida.")
    version = data[payload]
    if version == 0:
        timescale_at, duration_at, duration_size = payload + 12, payload + 16, 4
    elif version == 1:
        timescale_at, duration_at, duration_size = payload + 20, payload + 24, 8
    else:
        raise VideoValidationError("O MP4 usa uma versão de metadados incompatível.")
    timescale = _integer(data, timescale_at, 4)
    duration = _integer(data, duration_at, duration_size)
    if timescale <= 0 or duration <= 0:
        raise VideoValidationError("O MP4 não informou duração válida.")
    return timescale, duration


def _sample_entry(data, stbl, handler):
    _, _, stbl_payload, stbl_end = stbl
    stsd = _one(data, stbl_payload, stbl_end, b"stsd")
    _, _, payload, end = stsd
    if payload + 8 > end:
        raise VideoValidationError("O MP4 não informou o formato das faixas.")
    declared = _integer(data, payload + 4, 4)
    entries = list(_boxes(data, payload + 8, end))
    if declared != len(entries) or not entries:
        raise VideoValidationError("O MP4 não informou o formato das faixas.")
    accepted = ({b"avc1", b"avc3"} if handler == b"vide" else {b"mp4a"})
    entry = next((value for value in entries if value[1] in accepted), entries[0])
    return entry


def _track(data, box):
    _, _, trak_payload, trak_end = box
    mdia = _one(data, trak_payload, trak_end, b"mdia")
    _, _, mdia_payload, mdia_end = mdia
    hdlr = _one(data, mdia_payload, mdia_end, b"hdlr")
    _, _, handler_payload, handler_end = hdlr
    if handler_payload + 12 > handler_end:
        raise VideoValidationError("O MP4 não identificou uma faixa.")
    handler = bytes(data[handler_payload + 8:handler_payload + 12])
    if handler not in (b"vide", b"soun"):
        return None
    timescale, media_duration = _media_time(
        data, _one(data, mdia_payload, mdia_end, b"mdhd"))
    minf = _one(data, mdia_payload, mdia_end, b"minf")
    _, _, minf_payload, minf_end = minf
    stbl = _one(data, minf_payload, minf_end, b"stbl")
    entry = _sample_entry(data, stbl, handler)
    entry_start, entry_type, _, entry_end = entry
    if handler == b"soun":
        return {"kind": "audio", "codec": "aac" if entry_type == b"mp4a" else "other"}
    if entry_start + 36 > entry_end:
        raise VideoValidationError("O MP4 não informou as dimensões do vídeo.")
    width = _integer(data, entry_start + 32, 2)
    height = _integer(data, entry_start + 34, 2)
    _, _, stbl_payload, stbl_end = stbl
    stts = _one(data, stbl_payload, stbl_end, b"stts")
    _, _, timing_payload, timing_end = stts
    if timing_payload + 8 > timing_end:
        raise VideoValidationError("O MP4 não informou a taxa de quadros.")
    declared = _integer(data, timing_payload + 4, 4)
    if declared <= 0 or declared > 10000 or timing_payload + 8 + declared * 8 != timing_end:
        raise VideoValidationError("O MP4 não informou a taxa de quadros.")
    samples = ticks = 0
    for offset in range(timing_payload + 8, timing_end, 8):
        count = _integer(data, offset, 4)
        delta = _integer(data, offset + 4, 4)
        if count <= 0 or delta <= 0:
            raise VideoValidationError("O MP4 não informou a taxa de quadros.")
        samples += count
        ticks += count * delta
    fps = samples * timescale / ticks if ticks else 0
    if media_duration <= 0:
        raise VideoValidationError("O MP4 não informou duração válida.")
    return {"kind": "video", "codec": "h264" if entry_type in (b"avc1", b"avc3") else "other",
            "width": width, "height": height, "fps": fps}


def _inspect_mp4(path):
    """Read standard MP4 container metadata when ffprobe is unavailable."""
    try:
        with path.open("rb") as stream, mmap.mmap(
                stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            top = list(_boxes(data, 0, len(data)))
            if not top or top[0][1] != b"ftyp":
                raise VideoValidationError("O arquivo não possui um contêiner MP4 válido.")
            moov = [box for box in top if box[1] == b"moov"]
            if len(moov) != 1:
                raise VideoValidationError("O MP4 não informou metadados de reprodução.")
            _, _, moov_payload, moov_end = moov[0]
            timescale, duration_value = _media_time(
                data, _one(data, moov_payload, moov_end, b"mvhd"))
            tracks = [value for value in (
                _track(data, box) for box in _children(
                    data, moov_payload, moov_end, b"trak")) if value]
    except VideoValidationError:
        raise
    except (OSError, ValueError, OverflowError):
        raise VideoValidationError("Não foi possível ler os metadados do MP4.") from None
    videos = [track for track in tracks if track["kind"] == "video"]
    audios = [track for track in tracks if track["kind"] == "audio"]
    duration = duration_value / timescale
    if len(videos) != 1 or not audios or not math.isfinite(duration):
        raise VideoValidationError("O Reel precisa conter uma faixa de vídeo e uma de áudio.")
    video = videos[0]
    return {"duration": duration, "width": video["width"], "height": video["height"],
            "fps": video["fps"], "video_codec": video["codec"],
            "audio_codec": audios[0]["codec"], "has_audio": True}


def inspect(path, *, executable=None, runner=subprocess.run):
    """Lê metadados sem recodificar nem alterar o vídeo."""
    path = Path(path)
    if (path.is_symlink() or not path.is_file() or path.stat().st_size <= 0 or
            path.stat().st_size > MAX_VIDEO_BYTES):
        raise VideoValidationError("O arquivo de Reel não é um MP4 local válido.")
    probe = executable or shutil.which("ffprobe")
    if not isinstance(probe, str) or not probe:
        return _inspect_mp4(path)
    try:
        result = runner([
            probe, "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate",
            "-of", "json", str(path),
        ], capture_output=True, check=False, timeout=20)
        if result.returncode != 0 or len(result.stdout) > MAX_PROBE_OUTPUT:
            raise VideoValidationError("O MP4 não passou pela validação técnica.")
        payload = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, TypeError):
        raise VideoValidationError("Não foi possível validar o MP4 no servidor.") from None
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list):
        raise VideoValidationError("O MP4 não informou faixas válidas.")
    videos = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"]
    audios = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"]
    if len(videos) != 1 or not audios:
        raise VideoValidationError("O Reel precisa conter uma faixa de vídeo e uma de áudio.")
    video = videos[0]
    audio = audios[0]
    try:
        numerator, denominator = str(video["avg_frame_rate"]).split("/", 1)
        fps = float(numerator) / float(denominator)
        duration = float(payload["format"]["duration"])
        width, height = int(video["width"]), int(video["height"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError):
        raise VideoValidationError("O MP4 não informou dimensões ou duração válidas.") from None
    return {
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "has_audio": True,
    }
