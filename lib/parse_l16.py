from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any


_FIELD_RE_TEMPLATE = r"{name}\s*:\s*(-?\d+)"
logger = logging.getLogger("html_brief_log")


def _extract_int(block: str, field_name: str) -> int | None:
    match = re.search(_FIELD_RE_TEMPLATE.format(name=re.escape(field_name)), block)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def parse_l16_text(text: str) -> dict[int, dict[str, int]]:
    """Parse textproto-like Link16 blocks and return flight-number keyed records."""

    by_flight: dict[int, dict[str, int]] = {}
    for block in re.findall(r"flights\s*\{([^{}]*)\}", text, flags=re.DOTALL):
        flight_number = _extract_int(block, "flight_number")
        if flight_number is None:
            continue
        record: dict[str, int] = {}
        for field in ("stn_number", "f2f_channel", "mission_channel", "ew_channel", "team"):
            value = _extract_int(block, field)
            if value is not None:
                record[field] = value
        by_flight[flight_number] = record
    logger.debug("Parsed Link16 text: flights=%d", len(by_flight))
    return by_flight


def parse_l16_file(path: Path) -> dict[int, dict[str, int]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Failed to read Link16 file %s: %s", path, exc)
        return {}
    logger.debug("Loaded Link16 file: %s", path)
    return parse_l16_text(text)


def format_l16_code(record: dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return ""

    stn = record.get("stn_number")
    if not isinstance(stn, int):
        return ""
    if stn < 0:
        return ""
    return str(stn)

def _campaign_dirs(
    *,
    bms_base_dir: str | Path | None,
    theater_target_folder: str | Path | None = None,
) -> list[Path]:
    dirs: list[Path] = []
    if not bms_base_dir:
        return dirs
    base = Path(bms_base_dir).expanduser()
    data_dir = base / "Data"

    # Primary default campaign folder.
    dirs.append(data_dir / "Campaign")

    # If target folder is in an add-on, use that campaign first.
    if theater_target_folder:
        target = Path(theater_target_folder).expanduser()
        if not target.is_absolute():
            target = (base / target).resolve()
        try:
            resolved = target.resolve()
        except Exception:
            resolved = target
        for idx, part in enumerate(resolved.parts):
            if part.lower().startswith("add-on"):
                addon_root = Path(*resolved.parts[: idx + 1])
                dirs.insert(0, addon_root / "Campaign")
                break

    # Fallback add-on campaign directories.
    if data_dir.is_dir():
        try:
            for add_on in data_dir.iterdir():
                if add_on.is_dir() and add_on.name.lower().startswith("add-on"):
                    dirs.append(add_on / "Campaign")
        except Exception:
            pass

    deduped: list[Path] = []
    seen: set[Path] = set()
    for item in dirs:
        try:
            resolved = item.resolve()
        except Exception:
            resolved = item
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_dir():
            deduped.append(resolved)
    return deduped


def load_l16_for_save(
    *,
    bms_base_dir: str | Path | None,
    theater_target_folder: str | Path | None = None,
    save_stem: str | None = None,
) -> tuple[dict[int, dict[str, int]], Path | None]:
    """Load Link16 data for exact save stem (`<save_stem>.l16.txtpb`) if present."""

    campaign_dirs = _campaign_dirs(
        bms_base_dir=bms_base_dir,
        theater_target_folder=theater_target_folder,
    )
    if not campaign_dirs:
        logger.debug("Link16 lookup skipped: no campaign dirs resolved.")
        return {}, None

    stem = (save_stem or "").strip()
    if not stem:
        logger.debug("Link16 lookup skipped: save stem is empty.")
        return {}, None

    filename = f"{stem}.l16.txtpb"
    for directory in campaign_dirs:
        candidate = directory / filename
        if candidate.is_file():
            parsed = parse_l16_file(candidate)
            logger.debug(
                "Link16 matched for save stem '%s': file=%s flights=%d",
                stem,
                candidate,
                len(parsed),
            )
            return parsed, candidate
    logger.debug(
        "Link16 file not found for save stem '%s' in %d campaign dirs.",
        stem,
        len(campaign_dirs),
    )
    return {}, None
