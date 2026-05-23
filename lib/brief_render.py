from __future__ import annotations

import logging
import re
from typing import Any

import datetime as dt
from lib.moon import moon_rise_set_times, moonphase_crude

CAM_SUPPORT_CELL_IDS = [
    "package_1", "package_2", "package_3", "package_4", "package_5", "package_6", "package_7", "package_30",
    "package_8", "package_9", "package_10", "package_11", "package_12", "package_13", "package_14", "package_31",
    "package_15", "package_16", "package_17", "package_18", "package_19", "package_21", "package_22", "package_32",
    "package_23", "package_24", "package_25", "package_26", "package_27", "package_28", "package_29", "package_33",
    "package_34", "package_35", "package_36", "package_37", "package_38", "package_39", "package_40", "package_41",
]
CAM_SUPPORT_COLS = 8
CAM_SUPPORT_MAX_ROWS = len(CAM_SUPPORT_CELL_IDS) // CAM_SUPPORT_COLS
CAM_MAP_COLORS = [
    "#00a6ff",
    "#ff6b35",
    "#7bd88f",
    "#ff4f81",
    "#b18cff",
    "#ffd166",
    "#2ec4b6",
    "#f15bb5",
    "#8ac926",
    "#f77f00",
]

logger = logging.getLogger("html_brief_log")


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _cam_mission_name(entity: Any) -> str:
    if not isinstance(entity, dict):
        return ""
    tasking = entity.get("tasking")
    if not isinstance(tasking, dict):
        return ""
    for key in ("mission_name", "old_mission_name"):
        value = tasking.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text and text.upper() != "NONE":
                return text
    return ""


def _format_cam_time(value_ms: Any) -> str:
    if not isinstance(value_ms, int) or value_ms < 0:
        return ""
    total_seconds = value_ms // 1000
    hours = (total_seconds // 3600) % 24
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}z"


def _format_cam_aircraft(flight: Any) -> str:
    if not isinstance(flight, dict):
        return ""
    aircraft = flight.get("aircraft")
    if not isinstance(aircraft, str):
        return ""
    aircraft = aircraft.strip()
    if not aircraft:
        return ""
    if aircraft[:1].isdigit():
        return aircraft
    sources = [flight]
    tasking = flight.get("tasking")
    if isinstance(tasking, dict):
        sources.append(tasking)
    for source in sources:
        for key in ("aircraft_count", "aircraft_num", "flight_size", "num_aircraft"):
            count = _as_int(source.get(key))
            if isinstance(count, int) and count > 0:
                return f"{count} {aircraft}"
    return aircraft


def _format_l16_code(record: Any) -> str:
    if not isinstance(record, dict):
        return ""
    stn = record.get("stn_number")
    if not isinstance(stn, int) or stn < 0:
        return ""
    return str(stn)


def _normalize_callsign(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(value.split()).lower()


def _object_attr(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _package_index_by_number(packages: list[dict[str, Any]], package_number: Any) -> int | None:
    wanted = _as_int(package_number)
    if wanted is None:
        return None
    for idx, pkg in enumerate(packages):
        if _as_int(pkg.get("package_number")) == wanted:
            return idx
    return None


def _flight_route_points(flight: dict[str, Any]) -> list[list[int]]:
    steerpoints = flight.get("steerpoints")
    if not isinstance(steerpoints, list):
        return []
    route_steerpoints = _trim_after_first_landing_steerpoint(steerpoints)
    points: list[list[int]] = []
    for steerpoint in route_steerpoints:
        if not isinstance(steerpoint, dict):
            continue
        x = _as_int(steerpoint.get("x"))
        y = _as_int(steerpoint.get("y"))
        if x is None or y is None:
            continue
        points.append([x, y])
    return points


def _is_landing_steerpoint(steerpoint: Any) -> bool:
    if not isinstance(steerpoint, dict):
        return False
    action = _as_int(steerpoint.get("action"))
    action_name = str(steerpoint.get("action_name") or "").casefold()
    return action == 7 or action_name == "land"


def _trim_after_first_landing_steerpoint(steerpoints: list[Any]) -> list[Any]:
    for index, steerpoint in enumerate(steerpoints):
        if _is_landing_steerpoint(steerpoint):
            return steerpoints[: index + 1]
    return steerpoints


def _flight_dedupe_key(flight: dict[str, Any]) -> str:
    unit_id = flight.get("unit_id")
    if isinstance(unit_id, dict):
        num = _as_int(unit_id.get("num"))
        creator = _as_int(unit_id.get("creator"))
        if num is not None and creator is not None:
            return f"unit:{num}:{creator}"
    flight_number = _as_int(flight.get("flight_number"))
    if flight_number is not None:
        return f"flight:{flight_number}"
    return f"callsign:{_normalize_callsign(flight.get('callsign'))}"


def _is_own_flight(flight: dict[str, Any], own_flight: Any) -> bool:
    own_callsign = _normalize_callsign(_object_attr(own_flight, "callsign"))
    own_flight_number = _as_int(_object_attr(own_flight, "flight"))
    flight_callsign = _normalize_callsign(flight.get("callsign"))
    flight_number = _as_int(flight.get("flight_number"))
    return bool(
        (own_callsign and flight_callsign and own_callsign == flight_callsign)
        or (
            own_flight_number is not None
            and flight_number is not None
            and own_flight_number == flight_number
        )
    )


def _map_flight_label(flight: dict[str, Any], source: str) -> str:
    parts = []
    callsign = flight.get("callsign")
    if isinstance(callsign, str) and callsign.strip():
        parts.append(callsign.strip())
    flight_number = _as_int(flight.get("flight_number"))
    if flight_number is not None:
        parts.append(str(flight_number))
    role = _cam_mission_name(flight)
    aircraft = _format_cam_aircraft(flight)
    detail = " / ".join(part for part in (role, aircraft) if part)
    label = " ".join(parts) if parts else "Flight"
    if detail:
        label = f"{label} - {detail}"
    return f"{label} ({source})"


def _map_flight_overlay(
    *,
    flight: dict[str, Any],
    package: dict[str, Any],
    source: str,
    color: str,
) -> dict[str, Any] | None:
    points = _flight_route_points(flight)
    if len(points) < 2:
        return None
    flight_number = _as_int(flight.get("flight_number"))
    package_number = _as_int(package.get("package_number"))
    overlay_id = f"cam-flight-{package_number or 'pkg'}-{flight_number or _flight_dedupe_key(flight)}"
    return {
        "id": overlay_id,
        "label": _map_flight_label(flight, source),
        "callsign": flight.get("callsign") if isinstance(flight.get("callsign"), str) else "",
        "flight_number": flight_number,
        "package_number": package_number,
        "source": source,
        "color": color,
        "points": points,
    }


def _build_map_flight_overlays(
    packages: list[dict[str, Any]],
    *,
    selected_index: int | None,
    briefing_package_number: Any,
    own_flight: Any,
) -> list[dict[str, Any]]:
    package_sources: list[tuple[int, str]] = []
    player_index = _package_index_by_number(packages, briefing_package_number)
    if player_index is not None:
        package_sources.append((player_index, "Player package"))
    if selected_index is not None and 0 <= selected_index < len(packages):
        package_sources.append((selected_index, "Supporting package"))

    seen_packages: set[tuple[int, str]] = set()
    seen_flights: set[str] = set()
    overlays: list[dict[str, Any]] = []
    for package_index, source in package_sources:
        package_key = (package_index, source)
        if package_key in seen_packages:
            continue
        seen_packages.add(package_key)
        package = packages[package_index]
        flights = package.get("flights")
        if not isinstance(flights, list):
            continue
        for flight in flights:
            if not isinstance(flight, dict) or _is_own_flight(flight, own_flight):
                continue
            dedupe_key = _flight_dedupe_key(flight)
            if dedupe_key in seen_flights:
                continue
            color = CAM_MAP_COLORS[len(overlays) % len(CAM_MAP_COLORS)]
            overlay = _map_flight_overlay(
                flight=flight,
                package=package,
                source=source,
                color=color,
            )
            if overlay is None:
                continue
            seen_flights.add(dedupe_key)
            overlays.append(overlay)
    return overlays


def _support_row_mentions_tanker(row: Any) -> bool:
    support_type = str(_object_attr(row, "type") or "").casefold()
    comment = str(_object_attr(row, "comment") or "").casefold()
    return any(token in support_type or token in comment for token in ("tanker", "refuel"))


def _briefed_tanker_callsigns(support_rows: Any) -> set[str]:
    if not isinstance(support_rows, list):
        return set()
    callsigns: set[str] = set()
    for row in support_rows:
        if not _support_row_mentions_tanker(row):
            continue
        callsign = _normalize_support_callsign(_object_attr(row, "callsign"))
        if callsign:
            callsigns.add(callsign)
    return callsigns


def _normalize_support_callsign(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_-]*\d)\b", value)
    if match:
        return _normalize_callsign(match.group(1))
    return _normalize_callsign(value)


def _is_refueling_waypoint(steerpoint: Any) -> bool:
    if not isinstance(steerpoint, dict):
        return False
    action = _as_int(steerpoint.get("action"))
    action_name = str(steerpoint.get("action_name") or "").casefold()
    return action in {4, 24} or "refuel" in action_name or "tanker" in action_name


def _tanker_refueling_points(flight: dict[str, Any]) -> list[list[int]]:
    steerpoints = flight.get("steerpoints")
    if not isinstance(steerpoints, list):
        return []
    points: list[list[int]] = []
    for steerpoint in steerpoints:
        if not _is_refueling_waypoint(steerpoint):
            continue
        x = _as_int(steerpoint.get("x"))
        y = _as_int(steerpoint.get("y"))
        if x is not None and y is not None:
            points.append([x, y])
    if len(points) < 2:
        return []
    return [points[0], points[-1]]


def _build_map_tanker_overlay(
    packages: list[dict[str, Any]],
    *,
    support_rows: Any,
) -> dict[str, Any] | None:
    tanker_callsigns = _briefed_tanker_callsigns(support_rows)
    if not tanker_callsigns:
        return None
    for package in packages:
        flights = package.get("flights")
        if not isinstance(flights, list):
            continue
        for flight in flights:
            if not isinstance(flight, dict):
                continue
            callsign = _normalize_callsign(flight.get("callsign"))
            if not callsign or callsign not in tanker_callsigns:
                continue
            points = _tanker_refueling_points(flight)
            if len(points) < 2:
                continue
            return {
                "id": "cam-briefed-tanker-track",
                "label": _map_flight_label(flight, "Briefed tanker"),
                "callsign": flight.get("callsign") if isinstance(flight.get("callsign"), str) else "",
                "flight_number": _as_int(flight.get("flight_number")),
                "package_number": _as_int(package.get("package_number")),
                "color": "#ffffff",
                "points": points,
            }
    return None


def _blank_support_rows() -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = []
    for row_idx in range(CAM_SUPPORT_MAX_ROWS):
        row: list[dict[str, str]] = []
        for col_idx in range(CAM_SUPPORT_COLS):
            cell_index = row_idx * CAM_SUPPORT_COLS + col_idx
            row.append({"id": CAM_SUPPORT_CELL_IDS[cell_index], "value": ""})
        rows.append(row)
    return rows

def _format_datetime(d):
    return f"{d.hour:02d}:{d.minute:02d}z"

def _default_moon_data() -> dict[str, str]:
    return {"rise": "", "set": "", "phase": ""}


def _get_moon_data_from_date(
    date_string: Any,
    *,
    latitude: float | None,
    longitude: float | None,
) -> dict[str, str]:
    try:
        date_day = dt.date(year = int(date_string.split('-')[0]), month = int(date_string.split('-')[1]), day = int(date_string.split('-')[2])) 
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            logger.debug(
                "Moon data using fallback coordinates for date %r: lat=%r lng=%r",
                date_string,
                latitude,
                longitude,
            )
            latitude = 50.0
            longitude = -50.0
        rise_set = moon_rise_set_times(date_day, latitude, -longitude, accuracy = 5)
        rise_string = ", ".join([_format_datetime(x) for x in rise_set[0]])
        set_string = ", ".join([_format_datetime(x) for x in rise_set[1]])
        moon_phase = moonphase_crude(date_day)
        return {"rise" : rise_string, "set" : set_string, "phase": moon_phase}
    except Exception as exc:
        logger.debug("Moon data lookup failed for date %r: %s", date_string, exc)
        return _default_moon_data()

def _build_summary_render_context(
    brief_summary: dict[str, Any] | None,
    selected_package_index: int | None,
    theater_center: dict[str, float | None] | None,
    briefing_package_number: Any = None,
    own_flight: Any = None,
    support_rows_source: Any = None,
) -> dict[str, Any]:
    empty_context = {
        "package_options": [],
        "support_package_rows": _blank_support_rows(),
        "main_package_l16": {},
        "bullseye": {"lat": None, "lng": None},
        "moon_data": _default_moon_data(),
        "map_flight_overlays": [],
        "map_tanker_overlay": None,
    }
    if not isinstance(brief_summary, dict):
        logger.debug("Brief render context requested without summary data; using empty defaults.")
        return empty_context

    packages_raw = brief_summary.get("packages")
    packages = [pkg for pkg in packages_raw if isinstance(pkg, dict)] if isinstance(packages_raw, list) else []

    selected_index = selected_package_index if isinstance(selected_package_index, int) else None
    if packages and (selected_index is None or selected_index < 0 or selected_index >= len(packages)):
        logger.debug(
            "Brief render selection reset to first package: requested=%r package_count=%d",
            selected_package_index,
            len(packages),
        )
        selected_index = 0

    package_options: list[dict[str, Any]] = []
    for idx, pkg in enumerate(packages):
        package_number = _as_int(pkg.get("package_number"))
        label = f"#{idx + 1}" if package_number is None else str(package_number)
        mission_name = _cam_mission_name(pkg)
        if mission_name:
            label = f"{label} ({mission_name})"
        search_parts = [label]
        if package_number is not None:
            search_parts.append(str(package_number))
        flights = pkg.get("flights")
        if isinstance(flights, list):
            for flight in flights:
                mission_text = _cam_mission_name(flight)
                if mission_text:
                    search_parts.append(mission_text)
        package_options.append(
            {
                "index": idx,
                "label": label,
                "search_text": " ".join(
                    part.strip().lower()
                    for part in search_parts
                    if isinstance(part, str) and part.strip()
                ),
                "selected": idx == selected_index,
            }
        )

    support_rows = _blank_support_rows()
    if selected_index is not None and 0 <= selected_index < len(packages):
        selected_package = packages[selected_index]
        flights = selected_package.get("flights")
        row_values: list[list[str]] = []
        if isinstance(flights, list):
            for flight in flights[:CAM_SUPPORT_MAX_ROWS]:
                timing = flight.get("timing") if isinstance(flight.get("timing"), dict) else {}
                row_values.append(
                    [
                        flight.get("callsign").strip() if isinstance(flight.get("callsign"), str) else "",
                        str(flight["flight_number"]) if isinstance(flight.get("flight_number"), int) else "",
                        _cam_mission_name(flight),
                        _format_cam_aircraft(flight),
                        _format_cam_time(timing.get("takeoff_time_ms")),
                        _format_cam_time(timing.get("push_time_ms")),
                        _format_cam_time(timing.get("time_on_target_ms")),
                        _format_l16_code(flight.get("l16")),
                    ]
                )
        if not row_values:
            logger.debug(
                "Brief render using package-level timing fallback for selected package index %d",
                selected_index,
            )
            timing = selected_package.get("timing") if isinstance(selected_package.get("timing"), dict) else {}
            row_values.append(
                [
                    "",
                    str(selected_package["package_number"]) if isinstance(selected_package.get("package_number"), int) else "",
                    _cam_mission_name(selected_package),
                    "",
                    _format_cam_time(timing.get("takeoff_time_ms")),
                    _format_cam_time(timing.get("push_time_ms")),
                    _format_cam_time(timing.get("time_on_target_ms")),
                    "",
                ]
            )
        while len(row_values) < CAM_SUPPORT_MAX_ROWS:
            row_values.append([""] * CAM_SUPPORT_COLS)
        support_rows = []
        for row_idx, values in enumerate(row_values[:CAM_SUPPORT_MAX_ROWS]):
            row: list[dict[str, str]] = []
            for col_idx in range(CAM_SUPPORT_COLS):
                cell_index = row_idx * CAM_SUPPORT_COLS + col_idx
                row.append(
                    {
                        "id": CAM_SUPPORT_CELL_IDS[cell_index],
                        "value": values[col_idx] if col_idx < len(values) and isinstance(values[col_idx], str) else "",
                    }
                )
            support_rows.append(row)

    main_package_l16: dict[str, str] = {}
    for pkg in packages:
        flights = pkg.get("flights")
        if not isinstance(flights, list):
            continue
        for flight in flights:
            if not isinstance(flight, dict):
                continue
            flight_number = _as_int(flight.get("flight_number"))
            l16 = flight.get("l16")
            l16_text = _format_l16_code(l16)
            if not l16_text:
                continue
            if flight_number is not None:
                main_package_l16[str(flight_number)] = l16_text
            callsign = _normalize_callsign(flight.get("callsign"))
            if callsign:
                main_package_l16[callsign] = l16_text

    bullseye = brief_summary.get("bullseye") if isinstance(brief_summary.get("bullseye"), dict) else {}
    lat = bullseye.get("map_lat")
    lng = bullseye.get("map_lng")

    center_latitude = None
    center_longitude = None
    if isinstance(theater_center, dict):
        center_latitude = theater_center.get("lat")
        center_longitude = theater_center.get("lng")

    moon_data = _get_moon_data_from_date(
        brief_summary.get("current_date"),
        latitude=center_latitude,
        longitude=center_longitude,
    )
    map_flight_overlays = _build_map_flight_overlays(
        packages,
        selected_index=selected_index,
        briefing_package_number=briefing_package_number,
        own_flight=own_flight,
    )
    map_tanker_overlay = _build_map_tanker_overlay(
        packages,
        support_rows=support_rows_source,
    )
    logger.debug(
        "Built brief render context: packages=%d selected_index=%r support_rows=%d l16_overrides=%d map_overlays=%d has_tanker=%s has_bullseye=%s moon_phase=%s theater_center=(%r,%r)",
        len(packages),
        selected_index,
        len(support_rows),
        len(main_package_l16),
        len(map_flight_overlays),
        map_tanker_overlay is not None,
        isinstance(lat, (int, float)) and isinstance(lng, (int, float)),
        moon_data.get("phase", ""),
        center_latitude,
        center_longitude,
    )

    return {
        "package_options": package_options,
        "support_package_rows": support_rows,
        "main_package_l16": main_package_l16,
        "bullseye": {
            "x": bullseye.get("x") if isinstance(bullseye.get("x"), (int, float)) else None,
            "y": bullseye.get("y") if isinstance(bullseye.get("y"), (int, float)) else None,
            "map_grid_size_x": bullseye.get("map_grid_size_x") if isinstance(bullseye.get("map_grid_size_x"), (int, float)) else None,
            "map_grid_size_y": bullseye.get("map_grid_size_y") if isinstance(bullseye.get("map_grid_size_y"), (int, float)) else None,
            "lat": lat if isinstance(lat, (int, float)) else None,
            "lng": lng if isinstance(lng, (int, float)) else None,
        },
        "moon_data": moon_data,
        "map_flight_overlays": map_flight_overlays,
        "map_tanker_overlay": map_tanker_overlay,
    }


def build_brief_render_context(
    *,
    brief_summary: dict[str, Any] | None = None,
    selected_package_index: int | None = None,
    theater_center: dict[str, float | None] | None = None,
    briefing_package_number: Any = None,
    own_flight: Any = None,
    support_rows: Any = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    context.update(
        _build_summary_render_context(
            brief_summary,
            selected_package_index,
            theater_center,
            briefing_package_number=briefing_package_number,
            own_flight=own_flight,
            support_rows_source=support_rows,
        )
    )
    return context


__all__ = [
    "build_brief_render_context",
]
