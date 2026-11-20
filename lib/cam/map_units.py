"""Read-only map projection, restricted to the save owner's intelligence.

Category grouping and base-scenario loading follow frag_helper. Stored spotting
bits and country-to-team mapping follow OpenCAM's UNI and TEA records.
"""
from __future__ import annotations

from pathlib import Path

from .opencam.cam_container import CamContainer
from .opencam.obj_parser import ObjectiveRecord, parse_obj_records
from .opencam.obd_parser import ObjectiveDeltaRecord, parse_obd_records
from .opencam.support_files import SupportData, detect_container_version
from .opencam.tea_parser import TeamInfo, parse_tea_record
from .opencam.uni_wrappers import FlightUnit, Unit
from .types import ParsedCmpData, SavedMapUnit, SavedMapUnits


# Broad display categories from frag_helper; unknown classes retain a generic sign.
GROUND_SYMBOLS = {
    "aaa": "ad", "air defense": "ad", "shorad": "ad",
    "armored": "armor", "armored cavalry": "armor", "cavalry": "armor", "tank": "armor",
    "amphibian assault": "inf", "base defense": "inf", "infantry": "inf",
    "marine": "inf", "mech": "inf", "motor rifle": "inf",
    "engineer": "eng", "hq": "hq", "missile": "missile", "ss missile": "missile",
    "rocket": "art", "rocket artillery": "art", "sp guns": "art",
    "towed artillery": "art", "towed gun": "art",
}
UNIT_HIDDEN_FLAGS = 0x01 | 0x20000  # OpenCAM: dead, inactive.


def entry_by_extension(container: CamContainer, extension: str):
    return next((entry for entry in container.entries
                 if Path(entry.name).suffix.lower() == extension), None)


def load_map_units(
    container: CamContainer, *, source_path: Path, cmp: ParsedCmpData,
    units: tuple[Unit, ...], support: SupportData | None,
    campaign_directories: list[Path], warnings: list[str],
) -> SavedMapUnits:
    empty: SavedMapUnits = {"owner_team_id": None, "items": []}
    entry = entry_by_extension(container, ".tea")
    if entry is None or support is None:
        warnings.append("Map units unavailable: missing team or theater support data")
        return empty
    version = detect_container_version(container)
    try:
        teams = tuple(record.team for record in parse_tea_record(
            entry, container_version=version).team_records)
        result = project_map_units(units, (), (), teams, cmp, support)
    except Exception as exc:
        warnings.append(f"Map units unavailable: {exc}")
        return empty
    if result["owner_team_id"] is None:
        warnings.append("Map units unavailable: save owner team could not be resolved")
        return result
    try:
        objectives = load_objectives(container, source_path, cmp.scenario, campaign_directories)
        delta_entry = entry_by_extension(container, ".obd")
        deltas = parse_obd_records(delta_entry, container_version=version) if delta_entry else ()
        return project_map_units(units, objectives, deltas, teams, cmp, support)
    except Exception as exc:
        # Missing airfield context must not hide the valid mobile unit layer.
        warnings.append(f"Map airfields unavailable: {exc}")
        return result


def load_objectives(container: CamContainer, source_path: Path, scenario: str,
                    campaign_directories: list[Path]) -> tuple[ObjectiveRecord, ...]:
    entry = entry_by_extension(container, ".obj")
    if entry is not None:
        return parse_obj_records(entry, container_version=detect_container_version(container))
    filename = scenario.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename:
        raise ValueError("base scenario not recorded in save")
    if Path(filename).suffix.lower() not in {".cam", ".tac", ".trn"}:
        filename += ".tac" if source_path.suffix.lower() in {".tac", ".trn"} else ".cam"
    for directory in dict.fromkeys([source_path.parent, *campaign_directories]):
        if not directory.is_dir():
            continue
        path = next((p for p in directory.iterdir() if p.name.casefold() == filename.casefold()), None)
        if path is None or path.resolve() == source_path.resolve():
            continue
        base = CamContainer.from_path(path)
        entry = entry_by_extension(base, ".obj")
        if entry is None:
            raise ValueError(f"base scenario {path.name} has no objectives")
        return parse_obj_records(entry, container_version=detect_container_version(base))
    raise ValueError(f"base scenario {filename} not found in save or theater directory")


def project_map_units(
    units: tuple[Unit, ...], objectives: tuple[ObjectiveRecord, ...],
    deltas: tuple[ObjectiveDeltaRecord, ...], teams: tuple[TeamInfo, ...],
    cmp: ParsedCmpData, support: SupportData,
) -> SavedMapUnits:
    teams_by_id = {team.who: team for team in teams if 0 <= team.who < 8}

    def coalition(country: int) -> int | None:
        team = teams_by_id.get(country)
        return team.cteam if team is not None and team.cteam in teams_by_id else None

    squadron = next((unit for unit in units
                     if unit.kind == "squadron" and unit.unit_id == cmp.player_squadron_id), None)
    # The CMP active_team field is not a reliable owner-team index (real saves
    # contain 8). Only the recorded player squadron establishes this viewpoint.
    owner_team = coalition(int(squadron.get("owner"))) if squadron else None
    if owner_team not in teams_by_id:
        return {"owner_team_id": None, "items": []}
    owner = teams_by_id[owner_team]
    items: list[SavedMapUnit] = []

    def visible_side(country: int, spotted: int) -> str | None:
        team_id = coalition(country)
        if team_id is None:
            return None
        relation = owner.stance_name(team_id)
        side = "friend" if team_id == owner_team or relation in {"Allied", "Friendly"} else {
            "Hostile": "hostile", "At War": "hostile", "Neutral": "neutral",
        }.get(relation, "unknown")
        # Identification is the upper byte; it does not imply current spotting.
        return side if side == "friend" or spotted & (1 << owner_team) else None

    def append(record, identifier, category, country, side, symbol, label, heading_deg=None):
        x, y = int(record.get("x")), int(record.get("y"))
        if x < 0 or y < 0 or (x == 0 and y == 0):
            return
        team_id = coalition(country)
        team_name = cmp.team_names[team_id] if team_id < len(cmp.team_names) else ""
        item: SavedMapUnit = {"id": f"{category}:{identifier[0]}:{identifier[1]}",
                              "category": category, "position": [x, y], "symbol": symbol,
                              "side": side, "label": label, "team": team_name or f"Team {team_id}"}
        if heading_deg is not None:
            item["heading_deg"] = heading_deg
        items.append(item)

    for unit in units:
        if unit.kind not in {"battalion", "task_force", "flight"}:
            continue
        if unit.record.unit_flags & UNIT_HIDDEN_FLAGS:
            continue
        country = int(unit.get("owner"))
        side = visible_side(country, int(unit.get("spotted")))
        if side is None:
            continue
        class_entry = support.ct_by_number.get(unit.record.ct_index)
        unit_class = support.ucd_by_number.get(class_entry.entity_idx) if class_entry else None
        name = unit_class.name if unit_class else ""
        symbol = "generic"
        heading_deg = None
        label = f"{unit.get('name_id')} {name or unit.kind.replace('_', ' ')}".strip()
        if unit.kind == "battalion":
            symbol = GROUND_SYMBOLS.get(" ".join(name.replace("_", " ").lower().split()), "generic")
        elif isinstance(unit, FlightUnit):
            symbol = "flight"
            # Saved campaign direction: N, NE, E, ..., NW; 8 means "Here".
            direction = int(unit.get("last_direction"))
            if 0 <= direction < 8:
                heading_deg = direction * 45
            callsign = unit.callsign_view
            label = str(callsign["name"]) if callsign else f"Flight {unit.campaign_id}"
            if unit.aircraft_name:
                label += f" · {unit.aircraft_name}"
        append(unit, unit.unit_id, unit.kind, country, side, symbol, label, heading_deg)

    delta_by_id = {delta.objective_id: delta for delta in deltas}
    for objective in objectives:
        entry = support.ct_by_number.get(objective.objective_type - 100)
        if entry is None or (entry.domain, entry.class_) != (3, 4):
            continue
        if entry.type_ not in {1, 2} or (entry.type_ == 1 and entry.specific == 7):
            continue
        current = delta_by_id.get(objective.objective_id, objective)
        country = int(current.get("owner"))
        side = visible_side(country, int(objective.get("spotted")))
        if side is None:
            continue
        label = objective.objective_name_raw.split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()
        append(objective, objective.objective_id, "airfield", country, side, "ab",
               label or f"Airfield {objective.get('camp_id')}")
    return {"owner_team_id": owner_team, "items": items}
