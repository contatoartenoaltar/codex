"""Validação somente leitura de MP4 pronto para a fila de Reels."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess


MAX_PROBE_OUTPUT = 256 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024


class VideoValidationError(ValueError):
    pass


def inspect(path, *, executable=None, runner=subprocess.run):
    """Lê metadados com ffprobe sem recodificar nem alterar o vídeo."""
    path = Path(path)
    if (path.is_symlink() or not path.is_file() or path.stat().st_size <= 0 or
            path.stat().st_size > MAX_VIDEO_BYTES):
        raise VideoValidationError("O arquivo de Reel não é um MP4 local válido.")
    probe = executable or shutil.which("ffprobe")
    if not isinstance(probe, str) or not probe:
        raise VideoValidationError("O servidor não possui o validador de vídeo necessário.")
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
