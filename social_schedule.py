"""Leitura segura das decisões de horário compartilhadas entre filas isoladas."""
import json
import os
from pathlib import Path
import tempfile


FILENAME = "social-schedule-decisions.json"


def save(directory, decisions, *, generated_at):
    directory = Path(directory)
    payload = {
        "version": 1,
        "generated_at": int(generated_at),
        "decisions": {
            name: {"hour": item["selected_hour"], "minute": 0}
            for name, item in decisions.items()
            if item.get("state") == "selected" and type(item.get("selected_hour")) is int
            and 0 <= item["selected_hour"] <= 23
        },
    }
    descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".social-schedule-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
        os.chmod(temporary, 0o600)
        os.replace(temporary, directory / FILENAME)
    finally:
        Path(temporary).unlink(missing_ok=True)


def selected(directory, format_, fallback):
    """Retorna (hora, minuto); arquivo ausente ou inválido preserva o horário aprovado atual."""
    try:
        path = Path(directory) / FILENAME
        if path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_size > 16384:
            return fallback
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("decisions", {}).get(format_, {})
        hour, minute = value.get("hour"), value.get("minute")
        if type(hour) is int and type(minute) is int and 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return fallback
