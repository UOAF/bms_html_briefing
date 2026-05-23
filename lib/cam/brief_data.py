from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from lib.cam.types import (
    ParsedCmpData,
    ParsedL16Data,
    ParsedTwxData,
    SummaryFlight,
    SummaryOutput,
    SummaryPackage,
    SummaryPackageTiming,
    SummaryTasking,
    UniFlightUnitView,
    UniPackageTaskingView,
    UniPackageUnitView,
    VuidDict,
)

from .opencam.uni_wrappers import FlightUnit, PackageUnit, Unit


def build_cam_brief_data(
    *,
    source_path: Path,
    support_base_dir: Path | None,
    twx_data: ParsedTwxData,
    l16_data: ParsedL16Data,
    cmp_data: ParsedCmpData,
    units: tuple[Unit, ...],
    warnings: list[str],
) -> SummaryOutput:
    """Build the app-facing CAM brief JSON from parsed source data."""

    packages = _packages_from_units(units, l16_data.by_flight)
    bullseye_x = cmp_data.bullseye_x
    bullseye_y = cmp_data.bullseye_y
    map_lat: float | None = None
    map_lng: float | None = None
    if bullseye_x is not None and bullseye_y is not None:
        map_lng = _map_coord_from_cmp(bullseye_x, "lng", 1024)
        map_lat = _map_coord_from_cmp(bullseye_y, "lat", 1024)

    player_squadron_id = cmp_data.player_squadron_id

    return {
        "source_path": str(source_path),
        "support_base_dir": str(support_base_dir) if support_base_dir is not None else None,
        "l16_source_path": str(l16_data.source_path) if l16_data.source_path is not None else None,
        "current_date": twx_data.current_date or None,
        "current_time_ms": cmp_data.current_time_ms,
        "player": {
            "squadron_id": _vuid_dict(player_squadron_id)
            if player_squadron_id is not None
            else None,
            "package_match_method": "all_packages",
        },
        "bullseye": {
            "x": bullseye_x,
            "y": bullseye_y,
            "name_id": cmp_data.bullseye_name_id,
            "name": "",
            "map_lat": map_lat,
            "map_lng": map_lng,
            "map_grid_size_x": 1024,
            "map_grid_size_y": 1024,
        },
        "package_count": len(packages),
        "packages": packages,
        "warnings": list(warnings),
    }


def _packages_from_units(
    units: tuple[Unit, ...],
    l16_by_flight: dict[int, dict[str, int]],
) -> list[SummaryPackage]:
    by_id = {unit.unit_id: unit for unit in units}
    packages = [unit for unit in units if isinstance(unit, PackageUnit)]
    packages.sort(key=lambda unit: unit.package_number)

    out: list[SummaryPackage] = []
    for package in packages:
        flights: list[SummaryFlight] = []
        for element_id in package.element_ids:
            flight = by_id.get(element_id)
            if not isinstance(flight, FlightUnit):
                continue
            flight_row = _flight_row(flight, l16_by_flight)
            flights.append(flight_row)
        flights.sort(
            key=lambda item: item.get("flight_number")
            if isinstance(item.get("flight_number"), int)
            else 0
        )

        package_view = cast(UniPackageUnitView, package.to_view())
        package_section = package_view.get("package", {})
        tasking = package_section.get("tasking") or {}
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
) -> SummaryFlight:
    view = cast(UniFlightUnitView, flight.to_view())
    flight_view = view.get("flight", {})
    aircraft_view = view.get("aircraft")
    callsign_view = view.get("callsign")

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

    aircraft = aircraft_view.get("vehicle_name") if aircraft_view is not None else None
    callsign = callsign_view.get("name") if callsign_view is not None else None

    return {
        "unit_id": _vuid_dict(flight.unit_id),
        "unit_kind": flight.kind,
        "flight_number": flight_number,
        "callsign": callsign or "",
        "aircraft": aircraft if aircraft is not None else "",
        "aircraft_count": flight_view.get("aircraft_count"),
        "tasking": _trim_tasking(tasking),
        "timing": timing,
        "steerpoints": list(view.get("steerpoints") or []),
        "l16": dict(l16_by_flight.get(flight_number, {}))
        if isinstance(flight_number, int)
        else {},
    }


def _trim_tasking(tasking: dict[str, Any]) -> SummaryTasking:
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
    flights: list[SummaryFlight],
    package_tasking: UniPackageTaskingView | dict[str, Any],
) -> SummaryPackageTiming:
    timing: SummaryPackageTiming = {
        "takeoff_time_ms": None,
        "push_time_ms": None,
        "time_on_target_ms": None,
    }
    for key in ("takeoff_time_ms", "push_time_ms", "time_on_target_ms"):
        values = [
            flight.get("timing", {}).get(key)
            for flight in flights
            if isinstance(flight.get("timing"), dict)
            and isinstance(flight.get("timing", {}).get(key), int)
        ]
        if values:
            timing[key] = min(values)
    if timing["time_on_target_ms"] is None and isinstance(package_tasking.get("time_on_target_ms"), int):
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


def _vuid_dict(value: object) -> VuidDict:
    if not _is_vuid_tuple(value):
        raise TypeError(f"expected VU_ID tuple, got {value!r}")
    return {"num": int(value[0]), "creator": int(value[1])}


__all__ = ["build_cam_brief_data"]
