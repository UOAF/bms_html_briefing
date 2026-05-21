from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_existing_case_path(path: Path) -> Path:
    """Return an existing path even when some components differ only by case."""
    path = Path(path)
    if path.exists():
        return path

    if path.is_absolute():
        current = Path(path.anchor)
        parts = path.parts[1:]
    else:
        current = Path(".")
        parts = path.parts

    for part in parts:
        candidate = current / part
        if candidate.exists():
            current = candidate
            continue
        try:
            match = next(
                child for child in current.iterdir()
                if child.name.casefold() == part.casefold()
            )
        except (OSError, StopIteration):
            return path
        current = match
    return current


def callsign_ini_path(bms_conf: Any) -> Path:
    return resolve_existing_case_path(
        Path(bms_conf.base_dir) / "User" / "Config" / f"{bms_conf.callsign}.ini"
    )
