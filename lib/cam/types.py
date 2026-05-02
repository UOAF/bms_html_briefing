from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict

Vuid = tuple[int, int]


@dataclass(frozen=True)
class ParsedTwxData:
    current_date: str = ""
    source_path: Path | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedL16Data:
    by_flight: dict[int, dict[str, int]] = field(default_factory=dict)
    source_path: Path | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedCmpData:
    current_time_ms: int | None = None
    current_time_z: str | None = None
    bullseye_name_id: int | None = None
    bullseye_x: int | None = None
    bullseye_y: int | None = None
    player_squadron_id: Vuid | None = None


class VuidDict(TypedDict):
    num: int
    creator: int


class UniWaypointView(TypedDict, total=False):
    index: int
    haves: int
    x: int
    y: int
    z: int
    arrive_ms: int
    arrive_z: str | None
    depart_ms: int
    depart_z: str | None
    action: int
    action_name: str
    route_action: int
    formation: int
    flags: int


class UniAircraftView(TypedDict):
    unit_class_index: int
    unit_class_name: str
    vehicle_ct_index: int
    vehicle_name: str
    callsign_idx: int
    callsign_slots: int


class UniCallsignView(TypedDict):
    strings_id: int
    callsign_id: int
    callsign_num: int
    root: str
    name: str


class UniUnitView(TypedDict, total=False):
    unit_id: VuidDict
    campaign_id: int
    unit_flags: int
    steerpoints: list[UniWaypointView]
    aircraft: UniAircraftView | None


class UniPackageTaskingView(TypedDict, total=False):
    mission_code: int
    mission_name: str | None
    aircraft_code: int
    context_code: int
    roe_code: int
    action_type: int
    time_on_target_ms: int
    time_on_target_z: str | None
    priority: int
    tot_type: int | None
    target_x: int | None
    target_y: int | None
    flags: int | None


class UniPackageSectionView(TypedDict, total=False):
    package_number: int
    elements: object
    element_ids: list[VuidDict]
    support_ids: list[VuidDict]
    tasking: UniPackageTaskingView | None


class UniPackageUnitView(UniUnitView, total=False):
    package: UniPackageSectionView


class UniFlightView(TypedDict, total=False):
    flight_number: int
    package_number: int | None
    takeoff_time_ms: int | None
    takeoff_time_z: str | None
    push_time_ms: int | None
    push_time_z: str | None
    time_on_target_ms: int
    time_on_target_z: str | None
    mission_over_time_ms: int
    mission_over_time_z: str | None
    mission_code: int
    mission_name: str | None
    old_mission_code: int
    old_mission_name: str | None
    last_direction: object
    priority: object
    mission_id: object
    eval_flags: object
    mission_context: object
    package_id: VuidDict
    squadron_id: VuidDict
    requester_id: VuidDict
    slots: list[object]
    pilots: list[object]
    plane_stats: list[object]
    player_slots: list[object]
    last_player_slot: object
    aircraft_count: int
    callsign: UniCallsignView | None


class UniFlightUnitView(UniUnitView, total=False):
    callsign: UniCallsignView | None
    flight: UniFlightView


class SummaryL16Record(TypedDict, total=False):
    stn_number: int
    f2f_channel: int
    mission_channel: int
    ew_channel: int
    team: int


class SummaryTasking(TypedDict, total=False):
    mission_code: int
    mission_name: str
    old_mission_code: int
    old_mission_name: str
    aircraft_count: int


class SummaryPackageTiming(TypedDict):
    takeoff_time_ms: int | None
    push_time_ms: int | None
    time_on_target_ms: int | None


class SummaryFlightTiming(TypedDict):
    takeoff_time_ms: int | None
    push_time_ms: int | None
    time_on_target_ms: int | None


class SummaryFlight(TypedDict):
    unit_id: VuidDict
    unit_kind: str
    flight_number: int | None
    callsign: str
    aircraft: str
    aircraft_count: int | None
    tasking: SummaryTasking
    timing: SummaryFlightTiming
    l16: SummaryL16Record | dict[str, int]


class SummaryPackage(TypedDict):
    package_id: VuidDict
    package_number: int
    tasking: SummaryTasking
    timing: SummaryPackageTiming
    flights: list[SummaryFlight]
    notes: list[str]


class SummaryPlayer(TypedDict):
    squadron_id: VuidDict | None
    package_match_method: Literal["all_packages"]


class SummaryBullseye(TypedDict):
    x: int | None
    y: int | None
    name_id: int | None
    name: str
    map_lat: float | None
    map_lng: float | None
    map_grid_size_x: int
    map_grid_size_y: int


class SummaryOutput(TypedDict):
    source_path: str
    support_base_dir: str | None
    l16_source_path: str | None
    current_date: str | None
    current_time_ms: int | None
    player: SummaryPlayer
    bullseye: SummaryBullseye
    package_count: int
    packages: list[SummaryPackage]
    warnings: list[str]
