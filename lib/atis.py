"""Departure weather from the loaded save's adjacent FMAP snapshot."""
from __future__ import annotations

import logging
import math
from pathlib import Path

from lib.cam.opencam.fmap_parser import parse_fmap_record
from lib.cam.opencam.fmap_wrappers import wrap_fmap
from lib.theater_paths import read_theater_map_info

logger = logging.getLogger("html_brief_log")
HPA_PER_INHG = 33.8638866667
# BMS's shipped presets and Interactive Maps manual use 1..4, despite the
# zero-based list on the FMAP format wiki. Keep unknown codes identifiable.
WEATHER_TYPES = {1: "Sunny", 2: "Fair", 3: "Poor", 4: "Inclement"}


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _departure_cell(weather, north_ft, east_ft, theater_size_km):
    """Use Frag Helper's stored-cell convention, without moving the map in time.

    DTC coordinates are north/east feet; FMAP columns run eastward and rows
    southward. The half-cell origin and edge wrapping match its FMAP lookup.
    Use the active theater extent rather than assuming a 1024 km theater.
    """
    north_km, east_km = north_ft * 0.0003048, east_ft * 0.0003048
    if not (0 <= north_km <= theater_size_km and 0 <= east_km <= theater_size_km):
        raise ValueError("Departure is outside the active theater")
    column = math.floor(east_km / theater_size_km * weather.width - 0.5) % weather.width
    row = math.ceil((1 - north_km / theater_size_km) * weather.height - 0.5) % weather.height
    return weather.cell(row, column)


def build_departure_atis(*, summary, briefing, dtc, bms_conf):
    """Build a compact readout; missing data never becomes standard atmosphere."""
    airbases = getattr(briefing, "airbases", []) or []
    result = {
        "departure": getattr(airbases[0], "agency", "") if airbases else "",
        "wind": "—", "temperature": "—", "qnh": "—",
        "weather_type": "—", "cloud_base": "—", "fog_boundary": "—",
        "snapshot_time": "", "status": "Load CAM + FMAP",
    }
    if not isinstance(summary, dict) or not summary.get("source_path"):
        return result
    result["status"] = "Weather unavailable"
    try:
        source_base = summary.get("source_bms_base_dir")
        if (not source_base or Path(source_base).expanduser().resolve() != Path(bms_conf.base_dir).expanduser().resolve()
                or str(summary.get("source_theater") or "").casefold() != str(bms_conf.theater).casefold()):
            result["status"] = "Theater mismatch"
            return result

        takeoffs = [p for p in dtc.steerpoints if str(p.action).strip() == "1"]
        if len(takeoffs) != 1:
            result["status"] = "Departure unavailable"
            return result
        departure = takeoffs[0]
        north, east = _finite(departure.coord_x), _finite(departure.coord_y)
        size = _finite(getattr(bms_conf, "theater_size_km", None))
        if size is None:
            size = _finite(read_theater_map_info(bms_conf.base_dir, bms_conf.theater)["theater_size_km"])
        if north is None or east is None or size is None or size <= 0:
            result["status"] = "Departure unavailable"
            return result

        # Never substitute another save, an update map, or another theater.
        source = Path(summary["source_path"]).expanduser().resolve()
        expected_name = source.with_suffix(".fmap").name.casefold()
        matches = [p for p in source.parent.iterdir() if p.is_file() and p.name.casefold() == expected_name]
        if len(matches) != 1:
            result["status"] = "FMAP missing" if not matches else "FMAP ambiguous"
            return result
        weather = wrap_fmap(parse_fmap_record(matches[0].read_bytes()))
        cell = _departure_cell(weather, north, east, size)

        result["weather_type"] = WEATHER_TYPES.get(cell.weather_type, f"Unknown ({cell.weather_type})")
        # The per-cell cloud-base field controls the low cloud layer (ft MSL).
        # Sunny disables that layer even when the FMAP retains a base value.
        cloud_base = _finite(cell.cumulus_base_ft)
        if cell.weather_type == 1:
            result["cloud_base"] = "None"
        elif cell.weather_type in (2, 3, 4) and cloud_base is not None and cloud_base >= 0:
            result["cloud_base"] = f"{cloud_base:,.0f} ft MSL"
        # Preserve the stored fog-end distance. Live ATIS visibility has not
        # been established as a direct conversion of this input to BMS's model.
        fog_boundary = _finite(cell.fog_end_km)
        if fog_boundary is not None and fog_boundary >= 0:
            result["fog_boundary"] = f"{fog_boundary:.1f} km"

        pressure, temperature = _finite(cell.pressure_hpa), _finite(cell.temperature_c)
        speed, direction = _finite(cell.wind_speeds_knots[0]), _finite(cell.wind_directions_deg[0])
        if speed is not None and speed >= 0 and direction is not None:
            result["wind"] = f"{math.floor(direction % 360 + 0.5) % 360:03d} deg / {speed:.0f} kt"
        if temperature is not None:
            result["temperature"] = f"{temperature:.0f} deg C"
        if pressure is not None and pressure > 0:
            result["qnh"] = f"{pressure / HPA_PER_INHG:.2f} inHg / {pressure:.0f} hPa"
        time_ms = summary.get("current_time_ms")
        if isinstance(time_ms, int) and time_ms >= 0:
            minutes = time_ms // 60000
            result["snapshot_time"] = f"{minutes // 60 % 24:02d}{minutes % 60:02d}z"
        result["status"] = ""
    except (OSError, TypeError, ValueError, IndexError) as exc:
        logger.warning("Departure ATIS: %s", exc)
    return result
