"""Typed convenience wrappers for parsed `.uni` unit records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .record_fields import FieldMap
from .support_files import SupportData, VehicleClassEntry, format_campaign_time_z
from .uni_parser import UnitRecord, VuId, Waypoint


UNIT_FLAG_HUMAN_CONTROLLED = 0x80
WAYPOINT_ACTION_PRECISION = -1
WAYPOINT_ACTION_TAKEOFF = 1
WAYPOINT_ACTION_PUSH = 2
WAYPOINT_ACTION_NAMES = {
    WAYPOINT_ACTION_PRECISION: "Precision",
    0: "Nav",
    WAYPOINT_ACTION_TAKEOFF: "TakeOff",
    WAYPOINT_ACTION_PUSH: "Push",
    3: "Split",
    4: "Refuel",
    5: "Rearm",
    6: "PickUp",
    7: "Land",
    8: "Holding",
    9: "CASCAP",
    10: "Escort",
    11: "Sweep",
    12: "CAP",
    13: "Intrcpt",
    14: "GNDStrk",
    15: "NAVStrk",
    16: "S&D",
    17: "Strike",
    18: "Bomb",
    19: "SEAD",
    20: "ELINT",
    21: "RECON",
    22: "Rescue",
    23: "ASW",
    24: "Tanker",
    25: "Airdrop",
    26: "JAM",
    27: "Land 2",
    28: "B5",
    29: "B6",
    30: "FAC",
}


class UnitWrapperError(RuntimeError):
    """Raised when a human-readable unit edit cannot be resolved deterministically."""


@dataclass
class Unit:
    """Base wrapper around a parsed unit record."""

    record: UnitRecord
    support: SupportData
    record_index: Mapping[VuId, UnitRecord] | None = None

    @property
    def fields(self) -> FieldMap:
        return self.record.fields

    def get(self, name: str) -> object:
        return self.record.get(name)

    def set(self, name: str, value: object) -> None:
        self.record.set(name, value)

    @property
    def unit_id(self) -> tuple[int, int]:
        return self.record.unit_id

    @property
    def kind(self) -> str:
        return self.record.kind

    @property
    def campaign_id(self) -> int:
        return int(self.get("camp_id"))

    @property
    def aircraft_name(self) -> str | None:
        vehicle = _vehicle_for_unit_record(self.record, self.support)
        return None if vehicle is None else vehicle.name

    def to_view(self) -> dict[str, object]:
        return {
            "unit_id": _vuid_dict(self.unit_id),
            "campaign_id": self.campaign_id,
            "unit_flags": self.record.unit_flags,
            "steerpoints": [
                _waypoint_view(index, waypoint)
                for index, waypoint in enumerate(self.record.waypoints)
            ],
            "aircraft": self.aircraft_view,
        }

    @property
    def aircraft_view(self) -> dict[str, object] | None:
        ct_entry = self.support.ct_by_number.get(self.record.ct_index)
        if ct_entry is None:
            return None
        unit_class = self.support.ucd_by_number.get(ct_entry.entity_idx)
        vehicle = _vehicle_for_unit_record(self.record, self.support)
        if unit_class is None or vehicle is None:
            return None
        return {
            "unit_class_index": unit_class.number,
            "unit_class_name": unit_class.name,
            "vehicle_ct_index": vehicle.ct_idx,
            "vehicle_name": vehicle.name,
            "callsign_idx": vehicle.callsign_idx,
            "callsign_slots": vehicle.callsign_slots,
        }


@dataclass
class FlightUnit(Unit):
    """Convenience API for flight unit records."""

    @property
    def mission_code(self) -> int:
        return int(self.get("mission"))

    @mission_code.setter
    def mission_code(self, value: int) -> None:
        if not 0 <= value <= 255:
            raise ValueError(f"mission_code must fit in uint8, got {value}")
        self.set("mission", value)

    @property
    def mission_name(self) -> str | None:
        return self.support.strings_by_id.get(300 + self.mission_code)

    def set_mission_by_string(self, name: str) -> None:
        self.mission_code = _mission_code_by_string(self.support, name)

    @property
    def flight_number(self) -> int:
        return self.campaign_id

    @property
    def package_id(self) -> VuId:
        value = self.get("package_id")
        if not isinstance(value, tuple) or len(value) != 2:
            raise UnitWrapperError("package_id value is malformed")
        return int(value[0]), int(value[1])

    @property
    def package_number(self) -> int | None:
        if self.record_index is None:
            return None
        package = self.record_index.get(self.package_id)
        if package is None or package.kind != "package":
            return None
        return int(package.get("camp_id"))

    @property
    def old_mission_code(self) -> int:
        return int(self.get("old_mission"))

    @old_mission_code.setter
    def old_mission_code(self, value: int) -> None:
        if not 0 <= value <= 255:
            raise ValueError(f"old_mission_code must fit in uint8, got {value}")
        self.set("old_mission", value)

    @property
    def callsign_id(self) -> int:
        return int(self.get("callsign_id"))

    @callsign_id.setter
    def callsign_id(self, value: int) -> None:
        if not 0 <= value <= 255:
            raise ValueError(f"callsign_id must fit in uint8, got {value}")
        self.set("callsign_id", value)

    @property
    def callsign_num(self) -> int:
        return int(self.get("callsign_num"))

    @callsign_num.setter
    def callsign_num(self, value: int) -> None:
        if not 0 <= value <= 255:
            raise ValueError(f"callsign_num must fit in uint8, got {value}")
        self.set("callsign_num", value)

    @property
    def callsign(self) -> str | None:
        root = self.support.strings_by_id.get(2000 + self.callsign_id)
        if root is None:
            return None
        return f"{root}{self.callsign_num}"

    def set_callsign_by_string(self, callsign: str) -> None:
        callsign_id, callsign_num = _callsign_parts_by_string(self.support, callsign)
        self.callsign_id = callsign_id
        self.callsign_num = callsign_num

    @property
    def time_on_target_ms(self) -> int:
        return int(self.get("time_on_target"))

    @property
    def time_on_target_z(self) -> str | None:
        return format_campaign_time_z(self.time_on_target_ms)

    @property
    def takeoff_time_ms(self) -> int | None:
        return _waypoint_depart_ms_by_action(
            self.record.waypoints,
            WAYPOINT_ACTION_TAKEOFF,
        )

    @property
    def takeoff_time_z(self) -> str | None:
        return format_campaign_time_z(self.takeoff_time_ms)

    @property
    def push_time_ms(self) -> int | None:
        return _waypoint_depart_ms_by_action(
            self.record.waypoints,
            WAYPOINT_ACTION_PUSH,
        )

    @property
    def push_time_z(self) -> str | None:
        return format_campaign_time_z(self.push_time_ms)

    def to_view(self) -> dict[str, object]:
        view = super().to_view()
        view["callsign"] = self.callsign_view
        view["flight"] = {
            "flight_number": self.flight_number,
            "package_number": self.package_number,
            "takeoff_time_ms": self.takeoff_time_ms,
            "takeoff_time_z": self.takeoff_time_z,
            "push_time_ms": self.push_time_ms,
            "push_time_z": self.push_time_z,
            "time_on_target_ms": self.time_on_target_ms,
            "time_on_target_z": self.time_on_target_z,
            "mission_over_time_ms": int(self.get("mission_over_time")),
            "mission_over_time_z": format_campaign_time_z(int(self.get("mission_over_time"))),
            "mission_code": self.mission_code,
            "mission_name": self.mission_name,
            "old_mission_code": self.old_mission_code,
            "old_mission_name": self.support.strings_by_id.get(300 + self.old_mission_code),
            "last_direction": self.get("last_direction"),
            "priority": self.get("priority"),
            "mission_id": self.get("mission_id"),
            "eval_flags": self.get("eval_flags"),
            "mission_context": self.get("mission_context"),
            "package_id": _vuid_dict(self.get("package_id")),
            "squadron_id": _vuid_dict(self.get("squadron_id")),
            "requester_id": _vuid_dict(self.get("requester_id")),
            "slots": list(self.get("slots")),
            "pilots": list(self.get("pilots")),
            "plane_stats": list(self.get("plane_stats")),
            "player_slots": list(self.get("player_slots")),
            "last_player_slot": self.get("last_player_slot"),
            "aircraft_count": _aircraft_count(
                tuple(int(value) for value in self.get("plane_stats"))
            ),
            "callsign": self.callsign_view,
        }
        return view

    @property
    def callsign_view(self) -> dict[str, object] | None:
        root = self.support.strings_by_id.get(2000 + self.callsign_id)
        if root is None or not 1 <= self.callsign_num <= 9:
            return None
        return {
            "strings_id": 2000 + self.callsign_id,
            "callsign_id": self.callsign_id,
            "callsign_num": self.callsign_num,
            "root": root,
            "name": f"{root}{self.callsign_num}",
        }


@dataclass
class SquadronUnit(Unit):
    """Convenience API for squadron unit records."""

    @property
    def human_controlled(self) -> bool:
        return bool(self.record.unit_flags & UNIT_FLAG_HUMAN_CONTROLLED)

    @human_controlled.setter
    def human_controlled(self, value: bool) -> None:
        flags = self.record.unit_flags
        if value:
            flags |= UNIT_FLAG_HUMAN_CONTROLLED
        else:
            flags &= ~UNIT_FLAG_HUMAN_CONTROLLED
        self.set("unit_flags", flags)

    @property
    def specialty_code(self) -> int:
        return int(self.get("specialty"))

    @specialty_code.setter
    def specialty_code(self, value: int) -> None:
        if not 0 <= value <= 255:
            raise ValueError(f"specialty_code must fit in uint8, got {value}")
        self.set("specialty", value)

    @property
    def specialty_string(self) -> str | None:
        if self.specialty_code == 0:
            return "Set by HQ"
        return self.support.strings_by_id.get(300 + self.specialty_code)

    def set_specialty_by_string(self, name: str) -> None:
        if _normalized(name) == _normalized("Set by HQ"):
            self.specialty_code = 0
            return
        self.specialty_code = _mission_code_by_string(self.support, name)

    def to_view(self) -> dict[str, object]:
        view = super().to_view()
        view["squadron"] = {
            "human_controlled": self.human_controlled,
            "specialty": {
                "code": self.specialty_code,
                "name": self.specialty_string,
                "set_by_hq": self.specialty_code == 0,
            }
        }
        return view


@dataclass
class PackageUnit(Unit):
    """Convenience API for package unit records."""

    @property
    def package_number(self) -> int:
        return self.campaign_id

    @property
    def element_ids(self) -> tuple[tuple[int, int], ...]:
        if "element_ids" not in self.fields:
            return ()
        return tuple(self.get("element_ids"))

    @property
    def support_ids(self) -> tuple[tuple[int, int], ...]:
        if "support_ids" not in self.fields:
            return ()
        return tuple(self.get("support_ids"))

    @property
    def tasking(self) -> "PackageTasking | None":
        return _package_tasking(self.fields, self.support)

    def to_view(self) -> dict[str, object]:
        view = super().to_view()
        tasking = self.tasking
        view["package"] = {
            "package_number": self.package_number,
            "elements": self.get("elements"),
            "element_ids": [_vuid_dict(unit_id) for unit_id in self.element_ids],
            "support_ids": [_vuid_dict(unit_id) for unit_id in self.support_ids],
            "tasking": None if tasking is None else tasking.to_view(),
        }
        return view


@dataclass(frozen=True)
class PackageTasking:
    """Conservative typed view of package mission-request tasking."""

    mission_code: int
    mission_name: str | None
    aircraft_code: int
    context_code: int
    roe_code: int
    action_type: int
    time_on_target_ms: int
    time_on_target_z: str | None
    priority: int
    tot_type: int | None = None
    target_x: int | None = None
    target_y: int | None = None
    flags: int | None = None

    def to_view(self) -> dict[str, int | str | None]:
        return {
            "mission_code": self.mission_code,
            "mission_name": self.mission_name,
            "aircraft_code": self.aircraft_code,
            "context_code": self.context_code,
            "roe_code": self.roe_code,
            "action_type": self.action_type,
            "time_on_target_ms": self.time_on_target_ms,
            "time_on_target_z": self.time_on_target_z,
            "priority": self.priority,
            "tot_type": self.tot_type,
            "target_x": self.target_x,
            "target_y": self.target_y,
            "flags": self.flags,
        }


def wrap_unit(
    record: UnitRecord,
    support: SupportData,
    record_index: Mapping[VuId, UnitRecord] | None = None,
) -> Unit:
    if record.kind == "flight":
        return FlightUnit(record, support, record_index)
    if record.kind == "squadron":
        return SquadronUnit(record, support, record_index)
    if record.kind == "package":
        return PackageUnit(record, support, record_index)
    return Unit(record, support, record_index)


def wrap_units(records: Sequence[UnitRecord], support: SupportData) -> tuple[Unit, ...]:
    record_index = {record.unit_id: record for record in records}
    return tuple(wrap_unit(record, support, record_index) for record in records)


def _vehicle_for_unit_record(
    record: UnitRecord,
    support: SupportData,
) -> VehicleClassEntry | None:
    ct_entry = support.ct_by_number.get(record.ct_index)
    if ct_entry is None:
        return None
    unit_class = support.ucd_by_number.get(ct_entry.entity_idx)
    if unit_class is None or not unit_class.vehicle_ct_indices:
        return None
    return support.vcd_by_ct_idx.get(unit_class.vehicle_ct_indices[0])


def _waypoint_view(index: int, waypoint: Waypoint) -> dict[str, int | str | None]:
    return {
        "index": index,
        "haves": waypoint.haves,
        "x": waypoint.x,
        "y": waypoint.y,
        "z": waypoint.z,
        "arrive_ms": waypoint.arrive_ms,
        "arrive_z": format_campaign_time_z(waypoint.arrive_ms),
        "depart_ms": waypoint.depart_ms,
        "depart_z": format_campaign_time_z(waypoint.depart_ms),
        "action": waypoint.action,
        "action_name": _waypoint_action_name(waypoint.action),
        "route_action": waypoint.route_action,
        "formation": waypoint.formation,
        "flags": waypoint.flags,
    }


def _waypoint_depart_ms_by_action(
    waypoints: tuple[Waypoint, ...],
    action: int,
) -> int | None:
    for waypoint in waypoints:
        if _waypoint_action_value(waypoint.action) == action:
            return waypoint.depart_ms
    return None


def _waypoint_action_name(action: int) -> str:
    action_value = _waypoint_action_value(action)
    return WAYPOINT_ACTION_NAMES.get(action_value, str(action_value))


def _waypoint_action_value(action: int) -> int:
    if action == 255:
        return WAYPOINT_ACTION_PRECISION
    return action


def _package_tasking(fields: FieldMap, support: SupportData) -> PackageTasking | None:
    if "package_final_mis_request_header_raw" in fields:
        header = fields["package_final_mis_request_header_raw"].value
        tail = fields["package_final_mis_request_tail_raw"].value
        if not isinstance(header, bytes) or not isinstance(tail, bytes):
            return None
        if len(header) != 4 or len(tail) != 7:
            return None
        mission_code = header[0]
        time_on_target_ms = _u32(tail, 0)
        return PackageTasking(
            mission_code=mission_code,
            mission_name=support.strings_by_id.get(300 + mission_code),
            aircraft_code=header[1],
            context_code=header[2],
            roe_code=header[3],
            action_type=tail[4],
            time_on_target_ms=time_on_target_ms,
            time_on_target_z=format_campaign_time_z(time_on_target_ms),
            priority=_i16(tail, 5),
        )

    if "package_mis_request_type_mission_raw" not in fields:
        return None
    type_mission = fields["package_mis_request_type_mission_raw"].value
    tot_xy_flags = fields["package_mis_request_tot_xy_flags_raw"].value
    caps_target = fields["package_mis_request_caps_target_raw"].value
    if (
        not isinstance(type_mission, bytes)
        or not isinstance(tot_xy_flags, bytes)
        or not isinstance(caps_target, bytes)
    ):
        return None
    if len(type_mission) != 6 or len(tot_xy_flags) != 12 or len(caps_target) != 10:
        return None

    mission_code = type_mission[2]
    time_on_target_ms = _u32(tot_xy_flags, 0)
    return PackageTasking(
        mission_code=mission_code,
        mission_name=support.strings_by_id.get(300 + mission_code),
        aircraft_code=type_mission[3],
        context_code=type_mission[4],
        roe_code=type_mission[5],
        action_type=type_mission[1],
        time_on_target_ms=time_on_target_ms,
        time_on_target_z=format_campaign_time_z(time_on_target_ms),
        priority=_i16(caps_target, 8),
        tot_type=type_mission[0],
        target_x=_i16(tot_xy_flags, 4),
        target_y=_i16(tot_xy_flags, 6),
        flags=_u32(tot_xy_flags, 8),
    )


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little")


def _i16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little", signed=True)


def _aircraft_count(plane_stats: tuple[int, ...]) -> int:
    for index in range(min(len(plane_stats), 4) - 1, 0, -1):
        if plane_stats[index] != 0:
            return index + 1
    return 1


def _vuid_dict(value) -> dict[str, int]:
    return {"num": int(value[0]), "creator": int(value[1])}


def _mission_code_by_string(support: SupportData, name: str) -> int:
    wanted = _normalized(name)
    matches = [
        string_id - 300
        for string_id, value in support.strings_by_id.items()
        if 300 <= string_id <= 341 and _normalized(value) == wanted
    ]
    if len(matches) != 1:
        raise UnitWrapperError(f"mission string {name!r} resolved to {len(matches)} matches")
    return matches[0]


def _callsign_parts_by_string(support: SupportData, callsign: str) -> tuple[int, int]:
    text = callsign.strip()
    if len(text) < 2 or not text[-1].isdigit():
        raise UnitWrapperError(f"callsign must end with a numeric flight number: {callsign!r}")
    callsign_num = int(text[-1])
    root = text[:-1]
    matches = [
        string_id - 2000
        for string_id, value in support.strings_by_id.items()
        if 2000 <= string_id <= 2255 and _normalized(value) == _normalized(root)
    ]
    if len(matches) != 1:
        raise UnitWrapperError(f"callsign root {root!r} resolved to {len(matches)} matches")
    return matches[0], callsign_num


def _normalized(value: str) -> str:
    return " ".join(value.strip().casefold().split())
