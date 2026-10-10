"""Hardware resolution ported from OpenCAM 528b4be; no performance policy."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .support_files import BmsSupportError, SupportData


@dataclass(frozen=True)
class HardwareReference:
    status: str
    ct_index: int | None = None
    weapon_number: int | None = None
    weight_lb: int | None = None
    source_path: Path | None = None
    reason: str | None = None

    def to_view(self) -> dict[str, object]:
        return {
            "status": self.status, "ct_index": self.ct_index,
            "weapon_number": self.weapon_number, "weight_lb": self.weight_lb,
            "source_path": None if self.source_path is None else str(self.source_path),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LoadoutHardware:
    vehicle_number: int
    hardpoint_index: int
    weapon_number: int
    quantity: int
    status: str
    rack: HardwareReference
    pylon: HardwareReference
    group_name: str | None = None
    pylon_index: int | None = None
    rack_index: int | None = None
    rack_name: str | None = None
    source_path: Path | None = None
    aircraft_source_path: Path | None = None
    issues: tuple[str, ...] = ()

    def to_view(self) -> dict[str, object]:
        return {
            "vehicle_number": self.vehicle_number,
            "hardpoint_index": self.hardpoint_index,
            "weapon_number": self.weapon_number, "quantity": self.quantity,
            "status": self.status, "rack": self.rack.to_view(),
            "pylon": self.pylon.to_view(), "group_name": self.group_name,
            "pylon_index": self.pylon_index, "rack_index": self.rack_index,
            "rack_name": self.rack_name,
            "source_path": None if self.source_path is None else str(self.source_path),
            "aircraft_source_path": (
                None if self.aircraft_source_path is None else str(self.aircraft_source_path)
            ),
            "issues": list(self.issues),
        }


def _hardware_reference(support: SupportData, ct_index: int | None) -> HardwareReference:
    if ct_index == 0:
        return HardwareReference("no_hardware", ct_index=0, weight_lb=0,
                                 reason="authored CT reference 0")
    if ct_index is None or ct_index < 0:
        return HardwareReference("unresolved", ct_index=ct_index,
                                 reason="missing or invalid hardware CT reference")
    # Do not let a lossy CT-index dictionary silently choose a duplicate WCD row.
    matches = [w for w in support.wcd_by_number.values() if w.ct_idx == ct_index]
    if len(matches) != 1:
        return HardwareReference(
            "unresolved", ct_index=ct_index,
            reason=f"{support.paths.wcd_path}: hardware CT {ct_index} selects {len(matches)} WCD rows",
        )
    weapon = matches[0]
    if weapon.weight_lb < 0:
        return HardwareReference("unresolved", ct_index, weapon.number,
                                 source_path=weapon.source_path, reason="negative hardware weight")
    return HardwareReference("resolved", ct_index, weapon.number, weapon.weight_lb,
                             weapon.source_path)


def resolve_loadout_hardware(
    support: SupportData, vehicle_number: int, hardpoint_index: int,
    weapon_number: int, quantity: int,
) -> LoadoutHardware:
    for label, value, maximum in (
        ("vehicle number", vehicle_number, 0x7fffffff),
        ("hardpoint index", hardpoint_index, 15),
        ("weapon number", weapon_number, 0x7fff),
        ("quantity", quantity, 255),
    ):
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError(f"invalid {label} {value!r}")
    if (weapon_number == 0) != (quantity == 0):
        raise ValueError("empty station must be exactly weapon number 0 and quantity 0")
    common = dict(vehicle_number=vehicle_number, hardpoint_index=hardpoint_index,
                  weapon_number=weapon_number, quantity=quantity)
    if weapon_number == 0:
        absent = HardwareReference("no_hardware", weight_lb=0, reason="empty serialized station")
        return LoadoutHardware(**common, status="no_hardware", rack=absent, pylon=absent)
    group_name = None
    aircraft_path = None
    catalog = support.aircraft_rack_catalog
    try:
        aircraft = support.resolve_aircraft_for_vehicle(vehicle_number)
        data = aircraft.simulation_data
        aircraft_path = data.source_path
        if hardpoint_index >= len(data.hardpoint_groups):
            raise BmsSupportError(f"{aircraft_path}: missing group for hardpoint {hardpoint_index}")
        group_name = data.hardpoint_groups[hardpoint_index]
        if catalog is None:
            raise BmsSupportError(f"{support.paths.theater_dir}: BmsRack.dat is unavailable")
        weapon = support.resolve_weapon_for_number(weapon_number).simulation_data
        pylon_index, rack_index, pylon, rack = catalog.select(
            group_name, weapon_number, weapon.number, weapon.weapon_class, quantity
        )
    except (BmsSupportError, ValueError) as exc:
        reason = str(exc)
        unknown = HardwareReference("unresolved", reason=reason)
        return LoadoutHardware(
            **common, status="unresolved", rack=unknown, pylon=unknown,
            group_name=group_name, source_path=None if catalog is None else catalog.source_path,
            aircraft_source_path=aircraft_path, issues=(reason,),
        )
    rack_ref = _hardware_reference(support, rack.ct_index)
    pylon_ref = _hardware_reference(support, pylon.ct_index)
    issues = tuple(ref.reason for ref in (rack_ref, pylon_ref) if ref.status == "unresolved")
    status = "unresolved" if issues else (
        "no_hardware" if rack_ref.status == pylon_ref.status == "no_hardware" else "resolved"
    )
    return LoadoutHardware(
        **common, status=status, rack=rack_ref, pylon=pylon_ref,
        group_name=group_name, pylon_index=pylon_index, rack_index=rack_index,
        rack_name=rack.name, source_path=catalog.source_path,
        aircraft_source_path=aircraft_path, issues=issues,
    )


