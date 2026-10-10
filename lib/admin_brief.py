"""Select the player's saved aircraft using the briefing's rank/pilot-name roster."""
from __future__ import annotations

import math
from typing import Any

from lib.fuel_brief import _attr, _matched_flight, _path


def _pilot_name(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _store_labels(stores: list[dict], category: str) -> list[str]:
    # Never combine different weapon IDs just because their short names coincide.
    grouped = {}
    for store in stores:
        if store["category"] == category or (store["category"] == "both" and category in ("aa", "ag")):
            if not store["name"]:
                return []
            key = store["weapon_id"]
            name, count = grouped.get(key, (store["name"], 0))
            grouped[key] = name, count + store["count"]
    return [f"{count}× {name}" if count > 1 else name for name, count in grouped.values()]


def _pounds(value: Any) -> str | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
        return f"{value:,.0f}"
    return None


def build_admin_data(*, summary: Any, briefing: Any, player_name: str,
                     bms_base_dir: str, theater: str) -> dict:
    if not isinstance(summary, dict) or not _pilot_name(player_name):
        return {}
    if (not bms_base_dir or not theater
            or _path(summary.get("source_bms_base_dir")) != _path(bms_base_dir)
            or str(summary.get("source_theater") or "").casefold() != theater.casefold()):
        return {}
    try:
        flight = _matched_flight(summary, briefing)
        roster = _attr(_attr(briefing, "own_flight"), "roster")
        matches = []
        for index, field in enumerate(("lead", "wing", "element", "four")):
            rank_and_name = str(_attr(roster, field, "") or "").split(maxsplit=1)
            if len(rank_and_name) == 2 and _pilot_name(rank_and_name[1]) == _pilot_name(player_name):
                matches.append(index)
        if len(matches) != 1:
            return {}
        members = [m for m in flight.get("aircraft_members", []) if m["index"] == matches[0]]
        if len(members) != 1:
            return {}
        member = members[0]
        stores = member["stores"]
        classified = all(s["category"] is not None for s in stores)
        # A missing classification may be a tank, so do not show partial lists.
        categories = {"aa": "aa", "ag": "ag", "misc": "other", "tanks": "tanks"}
        groups = {key: _store_labels(stores, category) if classified else []
                  for key, category in categories.items()}
        if member.get("loaded_cft"):
            groups["tanks"].append("CFT")
        return {
            **groups,
            "gross_weight": _pounds(member.get("gross_weight_lb")),
            "takeoff_fuel": _pounds(member.get("takeoff_fuel_lb")),
        }
    except (ValueError, TypeError, KeyError):
        return {}
