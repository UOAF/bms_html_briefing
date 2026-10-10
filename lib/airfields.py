"""Shared airport lookup for charts and briefing display names."""
from __future__ import annotations

import logging

from openchart import api as openchart_api

from lib.theater_paths import resolve_theater_data_root

logger = logging.getLogger("html_brief_log")


def _float_or_none(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def airfield_inputs(briefing, callsign):
    """Return names and DTC positions in departure, arrival, alternate order."""
    airbases = list(getattr(briefing, "airbases", []) or [])
    steerpoints = list(getattr(callsign, "steerpoints", []) or [])
    takeoffs = [point for point in steerpoints if str(getattr(point, "action", "")) == "1"]
    landings = [point for point in steerpoints if str(getattr(point, "action", "")) in {"7", "27"}]
    role_points = (
        takeoffs[0] if takeoffs else None,
        landings[0] if landings else None,
        landings[1] if len(landings) > 1 else None,
    )
    result = []
    for index, point in enumerate(role_points):
        name = getattr(airbases[index], "agency", "") if index < len(airbases) else ""
        x = _float_or_none(getattr(point, "coord_x", None))
        y = _float_or_none(getattr(point, "coord_y", None))
        position = (x, y) if x is not None and y is not None else None
        result.append((str(name).strip() or None, position))
    return result


def airfield_query(name, position, *, api=openchart_api):
    """Prefer route coordinates over potentially abbreviated ATC callsigns."""
    if position is not None:
        return api.AirfieldQuery(position_x=position[0], position_y=position[1])
    return api.AirfieldQuery(name=name)


def resolve_briefing_airbase_names(briefing, callsign, bms_cfg):
    """Enrich parsed names from installed theater data, preserving each fallback."""
    airbases = getattr(briefing, "airbases", []) or []
    inputs = airfield_inputs(briefing, callsign)
    if not airbases or not any(name or position is not None for name, position in inputs):
        return
    try:
        data_root = resolve_theater_data_root(
            getattr(bms_cfg, "base_dir", None), getattr(bms_cfg, "theater", None),
        )
        if data_root is None:
            return
        source = openchart_api.TheaterSource(data_root)
    except Exception as exc:
        logger.debug("Briefing airfield source unavailable: %s", exc)
        return

    for airbase, (name, position) in zip(airbases, inputs):
        if not name and position is None:
            continue
        try:
            resolved = source.resolve_airfield(airfield_query(name, position))
            if resolved.display_name:
                airbase.agency = resolved.display_name
        except Exception as exc:
            logger.debug("Briefing airfield lookup failed for %r: %s", name, exc)
