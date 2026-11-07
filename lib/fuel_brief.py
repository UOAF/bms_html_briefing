"""Attach MFOB cells using the planned route and the player's takeoff loadout."""
from __future__ import annotations

import logging
import math
import os
import re
from pathlib import Path
from typing import Any

from lib.fuel import ASSUMPTIONS, FuelModelError
from lib.route_fuel import RouteFuelError, RoutePerformance, RoutePoint, remaining_route_fuel

_LAND_ACTIONS = {7, 27}
logger = logging.getLogger("html_brief_log")


def _attr(value: Any, name: str, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _integer(value: Any) -> int | None:
    try:
        number = float(value)
        return int(number) if not isinstance(value, bool) and math.isfinite(number) and number.is_integer() else None
    except (TypeError, ValueError, OverflowError):
        return None


def _callsign(value: Any) -> str:
    return "".join(str(value or "").split()).casefold()


def _path(value: Any) -> str:
    return os.path.normcase(str(Path(value).expanduser().resolve())) if value else ""


def _coordinates(point: Any) -> tuple[float, float]:
    try:
        values = float(_attr(point, "coord_x")), float(_attr(point, "coord_y"))
    except (TypeError, ValueError):
        raise ValueError("DTC steerpoint coordinates are missing.") from None
    if not all(math.isfinite(v) for v in values):
        raise ValueError("DTC steerpoint coordinates are invalid.")
    return values


def _matched_flight(summary: dict, briefing: Any) -> dict:
    package_number = _integer(_attr(_attr(briefing, "overview"), "package_id"))
    packages = [p for p in summary.get("packages", []) if _integer(p.get("package_number")) == package_number]
    if package_number is None or len(packages) != 1:
        raise ValueError("The loaded save does not uniquely match this briefing package.")
    own = _attr(briefing, "own_flight")
    number, callsign = _integer(_attr(own, "flight")), _callsign(_attr(own, "callsign"))
    flights = packages[0].get("flights", [])
    if number is not None:
        matches = [f for f in flights if _integer(f.get("flight_number")) == number]
    else:
        matches = [f for f in flights if callsign and _callsign(f.get("callsign")) == callsign]
    if len(matches) != 1:
        raise ValueError("The loaded save does not uniquely match this briefing flight.")
    flight = matches[0]
    if callsign and _callsign(flight.get("callsign")) != callsign:
        raise ValueError("The briefing and saved flight callsigns differ.")
    return flight


def _matched_member(flight: dict, briefing: Any, player_name: str) -> dict:
    def normalized(value):
        return " ".join(str(value or "").split()).casefold()

    roster = _attr(_attr(briefing, "own_flight"), "roster")
    matches = []
    for index, field in enumerate(("lead", "wing", "element", "four")):
        rank_and_name = str(_attr(roster, field, "") or "").split(maxsplit=1)
        if len(rank_and_name) == 2 and normalized(rank_and_name[1]) == normalized(player_name):
            matches.append(index)
    if not player_name or len(matches) != 1:
        raise ValueError("Pilot / roster match")
    members = [m for m in flight.get("aircraft_members", []) if m["index"] == matches[0]]
    if len(members) != 1:
        raise ValueError("Saved aircraft member")
    return members[0]


def _planned_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(label)
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError(label) from None
    if not math.isfinite(number):
        raise ValueError(label)
    return number


def _altitude(row: Any, point: Any, airport: bool) -> float:
    if airport:
        # DTC world Z is negative feet MSL, including airfield elevation.
        return -_planned_number(_attr(point, "coord_z"), "Airfield elevation")
    text = str(_attr(row, "altitude", "")).strip().upper()
    if text.endswith("A"):
        raise ValueError("MSL altitude required")
    return _planned_number(text[:-1] if text.endswith("M") else text,
                           "Planned altitude") * (1000 if text.endswith("M") else 1)


def _hold_hours(row: Any) -> float:
    comment = str(_attr(row, "comment", ""))
    # Timed patrol/attack repetition can also carry a Departure annotation.
    # Approximate that dwell at this point's planned speed and altitude.
    if not re.search(r"\b(?:hold|departure)\b", comment, re.IGNORECASE):
        return 0.
    departure = re.search(r"Departure:\s*(\d{2}:\d{2}:\d{2})z?", comment, re.IGNORECASE)
    arrival = re.fullmatch(r"(\d{2}:\d{2}:\d{2})z?", str(_attr(row, "time", "")).strip(), re.IGNORECASE)
    if not departure or not arrival:
        raise ValueError("Hold timing")

    def seconds(text):
        h, m, s = map(int, text.split(":"))
        if h > 23 or m > 59 or s > 59:
            raise ValueError("Hold timing")
        return h * 3600 + m * 60 + s

    return ((seconds(departure[1]) - seconds(arrival[1])) % 86400) / 3600


def _route_points(rows: list, dtc: Any) -> tuple[list[RoutePoint], int]:
    displayed = {}
    for row in rows:
        number = _integer(_attr(row, "number"))
        if number is None or number < 1 or number in displayed:
            raise ValueError("Briefing steerpoint numbers are invalid or duplicated.")
        displayed[number] = row
    points = {}
    for point in _attr(dtc, "steerpoints", []) or []:
        number = _integer(_attr(point, "number"))
        if number is None or number < 1 or number in points:
            raise ValueError("DTC steerpoint numbers are invalid or duplicated.")
        points[number] = point
    landings = sorted(n for n, p in points.items() if _integer(_attr(p, "action")) in _LAND_ACTIONS)
    if not landings:
        raise ValueError("The DTC has no planned landing steerpoint.")
    landing = landings[0]
    if landing < 2:
        raise ValueError("Planned route")
    route = []
    for number in range(1, landing + 1):
        point, row = points.get(number), displayed.get(number)
        if point is None or (row is None and number != landing):
            raise ValueError("The briefing and DTC steerpoint numbers differ.")
        airport = number in (1, landing)
        speed_row = displayed.get(2) if number == 1 else row
        if number == landing and row is None:
            speed_row = displayed.get(number - 1)
        cas = _planned_number(_attr(speed_row, "cas"), "Planned CAS")
        if cas <= 0:
            raise ValueError("Planned CAS")
        north, east = _coordinates(point)
        route.append(RoutePoint(number, north, east, _altitude(row, point, airport), cas,
                                0. if airport else _hold_hours(row)))
    return route, landing


def _route_failure_tooltip(error: RouteFuelError) -> str:
    reason = str(error)
    if reason in {"MSL altitude range", "Subsonic CAS range"}:
        reason = "Speed or altitude outside model limits"
    elif reason == "Zero-length altitude transition":
        reason = "Altitude change over zero distance"
    elif reason != "Required thrust exceeds full AB":
        reason = "Aircraft performance data unavailable or out of range"
    location = (f"STPT {error.from_number} hold" if error.from_number == error.to_number
                else f"STPT {error.from_number}–{error.to_number}")
    return f"MFOB unavailable: {reason} ({location})"


def build_fuel_plan(*, summary: Any, briefing: Any, dtc: Any, bms_base_dir: str,
                    theater: str, player_name: str = "") -> dict:
    """Return non-editable values and tooltips keyed by displayed STPT number."""
    rows = list(_attr(briefing, "steerpoints", []) or [])
    cells = {str(_attr(row, "number")): {"value": None, "tooltip": ASSUMPTIONS} for row in rows}
    result = {"tooltip": ASSUMPTIONS, "steerpoints": cells}

    def unavailable(reason: str) -> dict:
        own = _attr(briefing, "own_flight")
        logger.debug("MFOB unavailable: package=%s flight=%s callsign=%s: %s",
                     _attr(_attr(briefing, "overview"), "package_id"),
                     _attr(own, "flight"), _attr(own, "callsign"), reason)
        for cell in cells.values():
            cell["tooltip"] = "MFOB unavailable: " + reason + " · " + ASSUMPTIONS
        return result

    if not isinstance(summary, dict):
        return unavailable("Load the matching campaign save.")
    if (_path(summary.get("source_bms_base_dir")) != _path(bms_base_dir)
            or str(summary.get("source_theater") or "").casefold() != str(theater or "").casefold()):
        return unavailable("Reload the save for the current BMS installation and theater.")
    try:
        flight = _matched_flight(summary, briefing)
        profile = flight.get("fuel_profile") or {}
        if not profile.get("route_performance"):
            return unavailable("Reload CAM")
        model = RoutePerformance.from_view(profile["route_performance"])
        member = _matched_member(flight, briefing, player_name)
        # Installed weapons/tanks and CFT dry mass stay attached for every leg.
        gross = _planned_number(member.get("gross_weight_lb"), "T/O gross weight")
        takeoff_fuel = _planned_number(member.get("takeoff_fuel_lb"), "T/O fuel")
        if takeoff_fuel < 0:
            raise ValueError("T/O fuel")
        route, landing_number = _route_points(rows, dtc)
        failure_tooltip = None
        try:
            values = remaining_route_fuel(model, route, gross - takeoff_fuel, member.get("drag_index"))
        except RouteFuelError as exc:
            values = exc.values
            failure_tooltip = _route_failure_tooltip(exc)
            logger.debug("MFOB unavailable: package=%s flight=%s callsign=%s from=%s to=%s: %s",
                         _attr(_attr(briefing, "overview"), "package_id"),
                         flight.get("flight_number"), flight.get("callsign"),
                         exc.from_number, exc.to_number, exc)
        for row in rows:
            number = _integer(_attr(row, "number"))
            cell = cells[str(_attr(row, "number"))]
            if number > landing_number:
                cell["tooltip"] = "Outside the planned route through landing."
                continue
            if failure_tooltip is not None and number not in values:
                cell["tooltip"] = failure_tooltip
            else:
                cell["value"] = values[number]
        return result
    except (ValueError, TypeError, KeyError, FuelModelError) as exc:
        # Never leave partly computed values when required inputs are invalid.
        for cell in cells.values():
            cell["value"] = None
        return unavailable(str(exc))
