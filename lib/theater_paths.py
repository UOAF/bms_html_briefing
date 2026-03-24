from __future__ import annotations

import logging
import re
from pathlib import Path


logger = logging.getLogger("html_brief_log")

_CENTER_PATTERNS = {
    "center_latitude": re.compile(r"^\s*center\s+latitude\s*=\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE),
    "center_longitude": re.compile(r"^\s*center\s+longitude\s*=\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE),
}


def _definition_dir(base_dir: str | Path | None) -> Path | None:
    if not base_dir:
        return None
    return Path(base_dir).expanduser() / "Data" / "TerrData" / "TheaterDefinition"


def _split_rel_path(value: str) -> list[str]:
    return [part for part in re.split(r"[\\/]+", value.strip().strip("\"'")) if part]


def _resolve_case_insensitive(root: Path, rel_parts: list[str]) -> Path | None:
    current = root
    for part in rel_parts:
        candidate = current / part
        if candidate.exists():
            current = candidate
            continue
        try:
            current = next(child for child in current.iterdir() if child.name.lower() == part.lower())
        except (FileNotFoundError, NotADirectoryError, PermissionError, StopIteration):
            return None
    return current


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        logger.warning("Failed to read theater file %s: %s", path, exc)
        return []


def read_theater_list(base_dir: str | Path | None) -> tuple[list[str], Path | None]:
    definition_dir = _definition_dir(base_dir)
    if definition_dir is None:
        return [], None
    for filename in ("theater.lst", "Theater.lst"):
        path = definition_dir / filename
        if path.is_file():
            lines = _read_lines(path)
            logger.debug("Loaded theater list from %s entries=%d", path, len(lines))
            return lines, path
    logger.debug("Theater list not found under %s", definition_dir)
    return [], None


def resolve_theater_tdf_path(
    base_dir: str | Path | None,
    theater_name: str | None,
) -> Path | None:
    if not base_dir or not theater_name:
        return None
    list_lines, _ = read_theater_list(base_dir)
    wanted_suffix = f"{theater_name}.tdf".lower()
    data_root = Path(base_dir).expanduser() / "Data"
    for raw_line in list_lines:
        text = raw_line.strip()
        if not text or text.startswith(";"):
            continue
        rel_parts = _split_rel_path(text)
        if not rel_parts or rel_parts[-1].lower() != wanted_suffix:
            continue
        resolved = _resolve_case_insensitive(data_root, rel_parts)
        if resolved is not None and resolved.is_file():
            logger.debug("Resolved theater TDF for %s: %s", theater_name, resolved)
            return resolved
    logger.debug("Theater TDF not found for %s", theater_name)
    return None


def read_tdf_value(
    base_dir: str | Path | None,
    theater_name: str | None,
    key: str,
) -> tuple[str | None, Path | None]:
    tdf_path = resolve_theater_tdf_path(base_dir, theater_name)
    if tdf_path is None:
        return None, None
    key_l = key.lower()
    for raw_line in _read_lines(tdf_path):
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if not line.lower().startswith(key_l):
            continue
        parts = line.split(None, 1)
        value = parts[1] if len(parts) > 1 else ""
        value = value.lstrip("= ").strip().strip("\"'")
        logger.debug("Resolved %s from %s: %s", key, tdf_path, value)
        return value or None, tdf_path
    logger.debug("Key %s not found in %s", key, tdf_path)
    return None, tdf_path


def resolve_target_folder_from_theater(
    base_dir: str | Path | None,
    theater_name: str | None,
) -> Path | None:
    datadir, _ = read_tdf_value(base_dir, theater_name, "3ddatadir")
    if not datadir or not base_dir:
        return None
    resolved = _resolve_case_insensitive(
        Path(base_dir).expanduser() / "Data",
        _split_rel_path(datadir) + ["KoreaObj"],
    )
    if resolved is not None and resolved.exists():
        logger.debug("Resolved target folder for %s: %s", theater_name, resolved)
        return resolved
    logger.debug("Target folder not found for %s (3ddatadir=%s)", theater_name, datadir)
    return None


def resolve_theater_txt_path(
    base_dir: str | Path | None,
    theater_name: str | None,
) -> Path | None:
    terraindir, _ = read_tdf_value(base_dir, theater_name, "terraindir")
    if not terraindir or not base_dir:
        return None
    resolved = _resolve_case_insensitive(
        Path(base_dir).expanduser() / "Data",
        _split_rel_path(terraindir) + ["NewTerrain", "Theater.txt"],
    )
    if resolved is not None and resolved.is_file():
        logger.debug("Resolved Theater.txt for %s: %s", theater_name, resolved)
        return resolved
    logger.debug("Theater.txt not found for %s (terraindir=%s)", theater_name, terraindir)
    return None


def read_theater_center(
    base_dir: str | Path | None,
    theater_name: str | None,
) -> tuple[float | None, float | None, Path | None]:
    theater_txt_path = resolve_theater_txt_path(base_dir, theater_name)
    if theater_txt_path is None:
        return None, None, None

    center_latitude: float | None = None
    center_longitude: float | None = None
    for raw_line in _read_lines(theater_txt_path):
        if center_latitude is None:
            match = _CENTER_PATTERNS["center_latitude"].match(raw_line)
            if match:
                center_latitude = float(match.group(1))
        if center_longitude is None:
            match = _CENTER_PATTERNS["center_longitude"].match(raw_line)
            if match:
                center_longitude = float(match.group(1))
        if center_latitude is not None and center_longitude is not None:
            break

    logger.debug(
        "Parsed theater center for %s: lat=%r lng=%r file=%s",
        theater_name,
        center_latitude,
        center_longitude,
        theater_txt_path,
    )
    return center_latitude, center_longitude, theater_txt_path


__all__ = [
    "read_theater_center",
    "read_theater_list",
    "read_tdf_value",
    "resolve_target_folder_from_theater",
    "resolve_theater_tdf_path",
    "resolve_theater_txt_path",
]
