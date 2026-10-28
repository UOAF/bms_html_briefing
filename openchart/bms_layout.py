"""Folder and file naming for BMS-style chart output: <team>/<airfield>/<airfield>_<chart>."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .source import AirportData

UNASSIGNED_GROUP = "Unassigned"
INVALID_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
GENERIC_SUFFIX = re.compile(r"\s+(airport|airbase)\s*(?=\(|$)", re.I)


@dataclass(frozen=True)
class ChartFolder:
    group: str
    folder: str


def resolve_chart_folder(
    airport: AirportData,
    teams: dict[int, str],
    taken: dict[tuple[str, str], int],
) -> ChartFolder:
    """Derive the team/airfield folder, disambiguating name clashes by campaign ID."""

    target = _derived_folder(airport, teams)
    key = (target.group.casefold(), target.folder.casefold())
    if taken.setdefault(key, airport.campaign_id) != airport.campaign_id:
        return ChartFolder(target.group, f"{target.folder} ({airport.campaign_id})")
    return target


def _derived_folder(airport: AirportData, teams: dict[int, str]) -> ChartFolder:
    group = _safe_name(teams.get(airport.campaign_id, "")) or UNASSIGNED_GROUP
    folder = _safe_name(GENERIC_SUFFIX.sub(" ", airport.name)) or f"Airfield {airport.campaign_id}"
    if airport.icao and f"({airport.icao})" not in folder:
        folder = f"{folder} ({airport.icao})"
    return ChartFolder(group, folder)


def _safe_name(name: str) -> str:
    # Windows drops trailing dots and spaces, so "U.S." would otherwise become "U.S".
    return re.sub(r"\s+", " ", INVALID_PATH_CHARS.sub("", name)).strip().rstrip(". ")


def chart_path(
    root: Path,
    target: ChartFolder,
    suffix: str,
    extension: str,
) -> Path:
    return root / target.group / target.folder / f"{target.folder}_{suffix}.{extension}"
