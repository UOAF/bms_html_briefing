from __future__ import annotations

import logging
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
    return str(d.hour) + ":" + str(d.minute) + "z"

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
) -> dict[str, Any]:
    empty_context = {
        "package_options": [],
        "support_package_rows": _blank_support_rows(),
        "main_package_l16": {},
        "bullseye": {"lat": None, "lng": None},
        "moon_data": _default_moon_data(),
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
    logger.debug(
        "Built brief render context: packages=%d selected_index=%r support_rows=%d l16_overrides=%d has_bullseye=%s moon_phase=%s theater_center=(%r,%r)",
        len(packages),
        selected_index,
        len(support_rows),
        len(main_package_l16),
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
            "lat": lat if isinstance(lat, (int, float)) else None,
            "lng": lng if isinstance(lng, (int, float)) else None,
        },
        "moon_data": moon_data,
    }


def build_brief_render_context(
    *,
    brief_summary: dict[str, Any] | None = None,
    selected_package_index: int | None = None,
    theater_center: dict[str, float | None] | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    context.update(_build_summary_render_context(brief_summary, selected_package_index, theater_center))
    return context


__all__ = [
    "build_brief_render_context",
]
