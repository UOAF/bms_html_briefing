from __future__ import annotations

from datetime import date
import logging
from pathlib import Path
import struct

from lib.parse_l16 import _campaign_dirs

logger = logging.getLogger("html_brief_log")


def _find_case_insensitive_file(directory: Path, filename: str) -> Path | None:
    candidate = directory / filename
    if candidate.is_file():
        return candidate
    wanted = filename.lower()
    try:
        for child in directory.iterdir():
            if child.is_file() and child.name.lower() == wanted:
                return child
    except Exception:
        return None
    return None


def parse_twx_date_blob(blob: bytes) -> str | None:
    if len(blob) < 16:
        return None
    _, year, month, day = struct.unpack_from("<4I", blob, 0)
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def parse_twx_date_file(path: Path) -> str | None:
    try:
        blob = path.read_bytes()
    except Exception as exc:
        logger.debug("Failed to read TWX file %s: %s", path, exc)
        return None
    return parse_twx_date_blob(blob)


def load_twx_date_for_cam_path(cam_path: str | Path) -> tuple[str | None, Path | None]:
    source = Path(cam_path).resolve()
    twx_path = _find_case_insensitive_file(source.parent, f"{source.stem}.twx")
    if twx_path is None:
        return None, None
    current_date = parse_twx_date_file(twx_path)
    if current_date is None:
        return None, twx_path
    return current_date, twx_path


def load_twx_date_for_save(
    *,
    bms_base_dir: str | Path | None,
    theater_target_folder: str | Path | None = None,
    save_stem: str | None = None,
) -> tuple[str | None, Path | None]:
    campaign_dirs = _campaign_dirs(
        bms_base_dir=bms_base_dir,
        theater_target_folder=theater_target_folder,
    )
    stem = (save_stem or "").strip()
    if not stem:
        return None, None

    filename = f"{stem}.twx"
    for directory in campaign_dirs:
        twx_path = _find_case_insensitive_file(directory, filename)
        if twx_path is None:
            continue
        current_date = parse_twx_date_file(twx_path)
        if current_date is None:
            return None, twx_path
        return current_date, twx_path
    return None, None


__all__ = [
    "parse_twx_date_blob",
    "parse_twx_date_file",
    "load_twx_date_for_cam_path",
    "load_twx_date_for_save",
]
