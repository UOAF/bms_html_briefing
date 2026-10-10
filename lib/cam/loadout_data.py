"""Project saved member loadouts into admin data, independently of fuel planning."""
from __future__ import annotations

import logging
import math

from .opencam.loadout_weights import resolve_loadout_hardware
from .opencam.uni_wrappers import FlightUnit
from .types import SummaryAircraftMember, SummaryStore

logger = logging.getLogger("html_brief_log")


def _weight(value) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError("Missing weight or capacity")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("Invalid weight or capacity")
    return number


def _loadout_data(flight, loadout, aircraft):
    stores: list[SummaryStore] = []
    external_fuel = 0
    dry_weight = 0
    fuel_known = dry_known = True
    for station in loadout.nonempty_hardpoints:
        weapon = station.weapon
        valid = station.weapon_id > 0 and station.weapon_count > 0 and weapon is not None
        # The zero-weight internal gun/ammunition entry is already in clean
        # weight. External gun pods still follow normal store/hardware accounting.
        if (valid and station.hardpoint_index == 0
                and station.weapon_class == 3 and station.weapon_weight_lb == 0):
            continue
        category = None
        if valid:
            if weapon.is_fuel_tank:
                category = "tanks"
            elif station.weapon_class in (0, 8):
                category = "aa"
            elif station.weapon_class in (1, 2, 6, 7, 9):
                category = "ag"
            elif station.weapon_class == 3:
                category = {1: "aa", 2: "ag", 3: "both"}.get(station.weapon_domain)
            elif station.weapon_class in (4, 10):
                category = "other"
        stores.append({
            "weapon_id": station.weapon_id,
            "name": station.weapon_short_name or station.weapon_name or "",
            "count": station.weapon_count,
            "category": category,
        })
        if not valid:
            fuel_known = dry_known = False
            continue
        try:
            external_fuel += station.weapon_count * _weight(weapon.fuel_capacity_lb)
        except (ValueError, TypeError):
            fuel_known = False
        try:
            if aircraft is None:
                raise ValueError("Unresolved aircraft")
            hardware = resolve_loadout_hardware(
                flight.support, aircraft.vehicle.number, station.hardpoint_index,
                station.weapon_id, station.weapon_count,
            )
            dry_weight += (station.weapon_count * _weight(weapon.weight_lb)
                           + _weight(hardware.rack.weight_lb) + _weight(hardware.pylon.weight_lb))
        except Exception as exc:
            # Optional theater data must not discard otherwise usable stores/fuel.
            logger.debug("Admin hardware unavailable: %s", exc)
            dry_known = False
    return stores, external_fuel if fuel_known else None, dry_weight if dry_known else None


def build_aircraft_members(flight: FlightUnit) -> list[SummaryAircraftMember]:
    """Resolve shared/per-member loadouts and signed fuel offsets for active seats."""
    try:
        count = flight.aircraft_count
        loadouts = flight.loadouts
        if len(loadouts) not in (1, count):
            raise ValueError("Loadout count does not identify aircraft members")
    except Exception as exc:
        logger.debug("Admin loadouts unavailable: %s", exc)
        return []
    try:
        aircraft = flight.aircraft_data
    except Exception as exc:
        logger.debug("Admin aircraft data unavailable: %s", exc)
        aircraft = None
    decoded = [_loadout_data(flight, loadout, aircraft) for loadout in loadouts]
    members: list[SummaryAircraftMember] = []
    for index in range(count):
        stores, external_fuel, dry_weight = decoded[0 if len(decoded) == 1 else index]
        member: SummaryAircraftMember = {
            "index": index, "stores": stores, "loaded_cft": None,
            "takeoff_fuel_lb": None, "gross_weight_lb": None,
        }
        members.append(member)
        if aircraft is None:
            continue
        sim = aircraft.simulation_data
        try:
            loaded_cft = flight.loaded_cft[index] if sim.has_cft else 0
            if loaded_cft not in (0, 1):
                raise ValueError("Invalid CFT flag")
            member["loaded_cft"] = bool(loaded_cft)
            cft_fuel = _weight(sim.cft_fuel_lb) if loaded_cft else 0
            # BMS saves a signed offset, not a literal internal-fuel quantity.
            # At empty fuel this offset cancels fitted tank and CFT capacities.
            fuel = flight.initial_fuel_lb[index] + _weight(external_fuel) + cft_fuel
            capacity = _weight(sim.airframe.internal_fuel_lb) + _weight(external_fuel) + cft_fuel
            if not 0 <= fuel <= capacity:
                raise ValueError("Planned fuel is outside fitted capacity")
            member["takeoff_fuel_lb"] = fuel
        except Exception as exc:
            logger.debug("Admin takeoff fuel unavailable: %s", exc)
            continue
        try:
            cft_dry = _weight(sim.fuel_system.get("cft_empty_weight")) if loaded_cft else 0
            clean = _weight(sim.airframe.empty_weight_lb)
            if clean == 0:
                raise ValueError("Missing clean weight")
            member["gross_weight_lb"] = clean + _weight(dry_weight) + cft_dry + fuel
        except (ValueError, TypeError) as exc:
            logger.debug("Admin gross weight unavailable: %s", exc)
    return members
