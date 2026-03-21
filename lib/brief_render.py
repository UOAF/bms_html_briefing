from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.cam.cam_content import _find_support_file, _load_strings_by_id


CAM_SUPPORT_CELL_IDS = [
    "package_1", "package_2", "package_3", "package_4", "package_5", "package_6", "package_7", "package_30",
    "package_8", "package_9", "package_10", "package_11", "package_12", "package_13", "package_14", "package_31",
    "package_15", "package_16", "package_17", "package_18", "package_19", "package_21", "package_22", "package_32",
    "package_23", "package_24", "package_25", "package_26", "package_27", "package_28", "package_29", "package_33",
    "package_34", "package_35", "package_36", "package_37", "package_38", "package_39", "package_40", "package_41",
]
CAM_SUPPORT_COLS = 8
CAM_SUPPORT_MAX_ROWS = len(CAM_SUPPORT_CELL_IDS) // CAM_SUPPORT_COLS


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
    for key in ("aircraft_count", "aircraft_num", "flight_size", "num_aircraft"):
        count = _as_int(flight.get(key))
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


def _load_strings(support_base_dir: Path | None) -> dict[int, str]:
    strings_path = _find_support_file("Strings.txt", support_base_dir=support_base_dir)
    if strings_path is None:
        strings_path = _find_support_file("strings.txt", support_base_dir=support_base_dir)
    if strings_path is None:
        return {}
    return _load_strings_by_id(strings_path)


def _blank_support_rows() -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = []
    for row_idx in range(CAM_SUPPORT_MAX_ROWS):
        row: list[dict[str, str]] = []
        for col_idx in range(CAM_SUPPORT_COLS):
            cell_index = row_idx * CAM_SUPPORT_COLS + col_idx
            row.append({"id": CAM_SUPPORT_CELL_IDS[cell_index], "value": ""})
        rows.append(row)
    return rows


def _build_cam_render_context(
    cam_summary: dict[str, Any] | None,
    selected_package_index: int | None,
) -> dict[str, Any]:
    support_base_dir_raw = cam_summary.get("support_base_dir") if isinstance(cam_summary, dict) else None
    support_base_dir = Path(support_base_dir_raw) if isinstance(support_base_dir_raw, str) and support_base_dir_raw else None
    strings_by_id = _load_strings(support_base_dir)
    empty_context = {
        "cam_package_options": [],
        "cam_support_package_rows": _blank_support_rows(),
        "cam_main_package_l16": {},
        "cam_bullseye": {"lat": None, "lng": None, "name": ""},
    }
    if not isinstance(cam_summary, dict):
        return empty_context

    packages_raw = cam_summary.get("packages")
    packages = [pkg for pkg in packages_raw if isinstance(pkg, dict)] if isinstance(packages_raw, list) else []

    selected_index = selected_package_index if isinstance(selected_package_index, int) else None
    if packages and (selected_index is None or selected_index < 0 or selected_index >= len(packages)):
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
            if flight_number is None:
                continue
            l16_text = _format_l16_code(l16)
            if l16_text:
                main_package_l16[str(flight_number)] = l16_text

    bullseye = cam_summary.get("bullseye") if isinstance(cam_summary.get("bullseye"), dict) else {}
    lat = bullseye.get("map_lat")
    lng = bullseye.get("map_lng")
    name_id = bullseye.get("name_id")
    bullseye_name = strings_by_id.get(name_id, "") if isinstance(name_id, int) else ""

    return {
        "cam_package_options": package_options,
        "cam_support_package_rows": support_rows,
        "cam_main_package_l16": main_package_l16,
        "cam_bullseye": {
            "lat": lat if isinstance(lat, (int, float)) else None,
            "lng": lng if isinstance(lng, (int, float)) else None,
            "name": bullseye_name if isinstance(bullseye_name, str) else "",
        },
    }


def build_brief_render_context(
    *,
    cam_summary: dict[str, Any] | None = None,
    cam_package_index: int | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    context.update(_build_cam_render_context(cam_summary, cam_package_index))
    return context


__all__ = [
    "build_brief_render_context",
]
