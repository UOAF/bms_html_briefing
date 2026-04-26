from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from lib.campaign_paths import infer_support_base_dir
from lib.parsers.parse_l16 import load_parsed_l16_for_save
from lib.parsers.parse_twx import load_parsed_twx_for_cam_path, load_parsed_twx_for_save

from .opencam.cam_container import CamContainer, DecodedEntry
from .opencam.cmp_parser import parse_cmp_record
from .opencam.cmp_wrappers import wrap_campaign
from .opencam.support_files import (
    BmsSupportError,
    BmsSupportPaths,
    detect_container_version,
    load_support_data,
)
from .opencam.uni_parser import parse_uni_records
from .opencam.uni_wrappers import FlightUnit, PackageUnit, Unit, wrap_units

logger = logging.getLogger("html_brief_log")


def extract_cam_brief_data(
    cam_file_path: str | Path,
    *,
    bms_base_dir: str | Path | None = None,
    theater_target_folder: str | Path | None = None,
    theater_name: str | None = None,
    save_stem: str | None = None,
) -> dict[str, Any]:
    """Parse a CAM-like save and return app summary JSON."""

    source_path = Path(cam_file_path).resolve()
    support_base_dir = infer_support_base_dir(
        bms_base_dir,
        theater_target_folder,
        theater_name=theater_name,
    )

    warnings: list[str] = []
    container = CamContainer.from_path(source_path)
    container_version = detect_container_version(container)
    cmp_entry = _entry_by_ext(container, ".cmp")
    uni_entry = _entry_by_ext(container, ".uni")

    twx_data = load_parsed_twx_for_cam_path(source_path)
    if not twx_data.current_date:
        twx_data = load_parsed_twx_for_save(
            bms_base_dir=bms_base_dir,
            theater_target_folder=theater_target_folder,
            save_stem=save_stem or source_path.stem,
        )
    l16_data = load_parsed_l16_for_save(
        bms_base_dir=bms_base_dir,
        theater_target_folder=theater_target_folder,
        save_stem=save_stem or source_path.stem,
    )

    cmp_summary = _cmp_summary(cmp_entry, container_version, warnings)
    packages: list[dict[str, Any]] = []
    support_paths: BmsSupportPaths | None = None

    if uni_entry is None:
        warnings.append(".uni entry not found in CAM container")
    else:
        try:
            support_paths = _support_paths_from_base(support_base_dir)
            support = load_support_data(support_paths)
            records = parse_uni_records(
                uni_entry,
                container_version=container_version or 0,
                support=support,
            )
            units = wrap_units(records, support)
            packages = _packages_from_units(units, l16_data.by_flight)
        except Exception as exc:
            logger.warning("opencam UNI summary projection failed for %s: %s", source_path, exc)
            warnings.append(f"opencam UNI summary projection failed: {exc}")

    warnings.extend(str(item) for item in cmp_summary.pop("warnings", []) if str(item).strip())
    warnings.extend(twx_data.warnings)
    warnings.extend(l16_data.warnings)

    bullseye_x = cmp_summary.get("bullseye_x")
    bullseye_y = cmp_summary.get("bullseye_y")
    map_lat: float | None = None
    map_lng: float | None = None
    if isinstance(bullseye_x, int) and isinstance(bullseye_y, int):
        map_lng = _map_coord_from_cmp(bullseye_x, "lng", 1024)
        map_lat = _map_coord_from_cmp(bullseye_y, "lat", 1024)

    player_squadron_id = cmp_summary.get("player_squadron_id")

    return {
        "source_path": str(source_path),
        "support_base_dir": str(support_base_dir) if support_base_dir is not None else "",
        "l16_source_path": str(l16_data.source_path) if l16_data.source_path is not None else "",
        "current_date": twx_data.current_date,
        "current_time_ms": cmp_summary.get("current_time_ms"),
        "player": {
            "squadron_id": _vuid_dict(player_squadron_id)
            if _is_vuid_tuple(player_squadron_id)
            else None,
            "package_match_method": "all_packages",
        },
        "bullseye": {
            "x": bullseye_x,
            "y": bullseye_y,
            "name_id": cmp_summary.get("bullseye_name_id"),
            "name": "",
            "map_lat": map_lat,
            "map_lng": map_lng,
            "map_grid_size_x": 1024,
            "map_grid_size_y": 1024,
        },
        "package_count": len(packages),
        "packages": packages,
        "warnings": warnings,
    }


def _entry_by_ext(container: CamContainer, ext: str) -> DecodedEntry | None:
    normalized = ext.lower()
    for entry in container.entries:
        if Path(entry.name).suffix.lower() == normalized:
            return entry
    return None


def _cmp_summary(
    entry: DecodedEntry | None,
    container_version: int | None,
    warnings: list[str],
) -> dict[str, Any]:
    if entry is None:
        warnings.append(".cmp entry not found in CAM container")
        return {}

    record = parse_cmp_record(entry, container_version=container_version)
    campaign = wrap_campaign(record)
    try:
        player_squadron_id: object = record.player_squadron_id
    except Exception:
        player_squadron_id = None
        warnings.append("player_squadron_id not found in .cmp")

    return {
        "current_time_ms": campaign.current_time_ms,
        "current_time_z": campaign.current_time_z,
        "bullseye_name_id": campaign.bullseye_name,
        "bullseye_x": campaign.bullseye_x,
        "bullseye_y": campaign.bullseye_y,
        "player_squadron_id": player_squadron_id,
    }


def _support_paths_from_base(support_base_dir: Path | None) -> BmsSupportPaths:
    if support_base_dir is None:
        raise BmsSupportError("support base directory could not be inferred")

    support_base_dir = support_base_dir.resolve()
    if support_base_dir.name.lower() == "objects":
        objects_dir = support_base_dir
        theater_dir = objects_dir.parent.parent
    else:
        theater_dir = support_base_dir
        objects_dir = theater_dir / "TerrData" / "Objects"

    paths = BmsSupportPaths(
        theater_dir=theater_dir,
        campaign_dir=theater_dir / "Campaign",
        objects_dir=objects_dir,
        strings_path=_case_insensitive_file(theater_dir / "Campaign", "Strings.txt"),
        ct_path=_case_insensitive_file(objects_dir, "Falcon4_CT.xml"),
        ucd_path=_case_insensitive_file(objects_dir, "Falcon4_UCD.xml"),
        vcd_path=_case_insensitive_file(objects_dir, "Falcon4_VCD.xml"),
    )

    missing = [
        path
        for path in (paths.strings_path, paths.ct_path, paths.ucd_path, paths.vcd_path)
        if not path.is_file()
    ]
    if missing:
        raise BmsSupportError(
            "missing required support files: " + ", ".join(str(path) for path in missing)
        )
    return paths


def _case_insensitive_file(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if candidate.is_file():
        return candidate
    wanted = filename.lower()
    try:
        for child in directory.iterdir():
            if child.is_file() and child.name.lower() == wanted:
                return child
    except Exception:
        pass
    return candidate


def _packages_from_units(
    units: tuple[Unit, ...],
    l16_by_flight: dict[int, dict[str, int]],
) -> list[dict[str, Any]]:
    by_id = {unit.unit_id: unit for unit in units}
    packages = [unit for unit in units if isinstance(unit, PackageUnit)]
    packages.sort(key=lambda unit: unit.package_number)

    out: list[dict[str, Any]] = []
    for package in packages:
        flights: list[dict[str, Any]] = []
        for element_id in package.element_ids:
            flight = by_id.get(element_id)
            if not isinstance(flight, FlightUnit):
                continue
            flight_row = _flight_row(flight, l16_by_flight)
            flights.append(flight_row)
        flights.sort(key=lambda item: item.get("flight_number") if isinstance(item.get("flight_number"), int) else 0)

        package_view = package.to_view()
        package_section = package_view.get("package") if isinstance(package_view.get("package"), dict) else {}
        tasking = package_section.get("tasking") if isinstance(package_section.get("tasking"), dict) else {}
        out.append(
            {
                "package_id": _vuid_dict(package.unit_id),
                "package_number": package.package_number,
                "tasking": _trim_tasking(tasking),
                "timing": _package_timing_from_flights(flights, tasking),
                "flights": flights,
                "notes": [],
            }
        )
    return out


def _flight_row(
    flight: FlightUnit,
    l16_by_flight: dict[int, dict[str, int]],
) -> dict[str, Any]:
    view = flight.to_view()
    flight_view = view.get("flight") if isinstance(view.get("flight"), dict) else {}
    aircraft_view = view.get("aircraft") if isinstance(view.get("aircraft"), dict) else {}
    callsign_view = view.get("callsign") if isinstance(view.get("callsign"), dict) else {}

    flight_number = flight_view.get("flight_number")
    timing = {
        "takeoff_time_ms": flight_view.get("takeoff_time_ms"),
        "push_time_ms": flight_view.get("push_time_ms"),
        "time_on_target_ms": flight_view.get("time_on_target_ms"),
    }
    tasking = {
        key: flight_view.get(key)
        for key in (
            "mission_code",
            "mission_name",
            "old_mission_code",
            "old_mission_name",
            "mission_id",
            "mission_context",
            "eval_flags",
            "time_on_target_ms",
            "time_on_target_z",
            "mission_over_time_ms",
            "mission_over_time_z",
        )
        if key in flight_view
    }
    tasking["aircraft_count"] = flight_view.get("aircraft_count")

    aircraft = aircraft_view.get("vehicle_name")
    callsign = callsign_view.get("name")

    return {
        "unit_id": _vuid_dict(flight.unit_id),
        "unit_kind": flight.kind,
        "flight_number": flight_number,
        "callsign": callsign if isinstance(callsign, str) else "",
        "aircraft": aircraft if isinstance(aircraft, str) else "",
        "aircraft_count": flight_view.get("aircraft_count"),
        "tasking": _trim_tasking(tasking),
        "timing": timing,
        "l16": l16_by_flight.get(flight_number) if isinstance(flight_number, int) else {},
    }


def _trim_tasking(tasking: dict[str, Any]) -> dict[str, Any]:
    return {
        key: tasking[key]
        for key in (
            "mission_code",
            "mission_name",
            "old_mission_code",
            "old_mission_name",
            "aircraft_count",
        )
        if key in tasking and tasking[key] is not None
    }


def _package_timing_from_flights(
    flights: list[dict[str, Any]],
    package_tasking: dict[str, Any],
) -> dict[str, Any]:
    timing: dict[str, Any] = {}
    for key in ("takeoff_time_ms", "push_time_ms", "time_on_target_ms"):
        values = [
            flight.get("timing", {}).get(key)
            for flight in flights
            if isinstance(flight.get("timing"), dict)
            and isinstance(flight.get("timing", {}).get(key), int)
        ]
        if values:
            timing[key] = min(values)
    if "time_on_target_ms" not in timing and isinstance(package_tasking.get("time_on_target_ms"), int):
        timing["time_on_target_ms"] = package_tasking["time_on_target_ms"]
    return timing


def _map_coord_from_cmp(value: int, axis: str, grid_size: int) -> float:
    if abs(value) <= grid_size * 2:
        map_scalar = (float(value) / float(grid_size)) * 4096.0
    else:
        map_scalar = (float(value) / 3359580.0) * 4096.0
    if axis == "lat":
        return map_scalar - 4096.0
    return map_scalar


def _is_vuid_tuple(value: object) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], int)
        and isinstance(value[1], int)
    )


def _vuid_dict(value: object) -> dict[str, int]:
    if not _is_vuid_tuple(value):
        raise TypeError(f"expected VU_ID tuple, got {value!r}")
    return {"num": int(value[0]), "creator": int(value[1])}


__all__ = ["extract_cam_brief_data"]
