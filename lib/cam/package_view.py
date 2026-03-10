"""Human-readable package model builder."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from . import cam_parser

from .cam_content import ParsedCamData

logger = logging.getLogger("html_brief_log")


@dataclass(frozen=True)
class VUId:
    num: int
    creator: int


@dataclass(frozen=True)
class BullseyeInfo:
    x: int | None
    y: int | None
    name_id: int | None
    name: str | None


@dataclass(frozen=True)
class Steerpoint:
    index: int
    x: int
    y: int
    action: int
    route_action: int
    arrive_z: str | None
    depart_z: str | None


@dataclass(frozen=True)
class HumanFlight:
    unit_id: VUId
    unit_kind: str | None
    flight_number: int | None
    callsign: str | None
    aircraft: str | None
    mission: str | None
    takeoff_z: str | None
    push_z: str | None
    tot_z: str | None
    steerpoints: list[Steerpoint]


@dataclass(frozen=True)
class HumanPackage:
    package_id: VUId | None
    package_number: int | None
    mission: str | None
    takeoff_z: str | None
    push_z: str | None
    tot_z: str | None
    bullseye: BullseyeInfo
    flights: list[HumanFlight]


@dataclass(frozen=True)
class LegacySteerpoint:
    number: str
    description: str | None
    time: str | None
    distance: str | None
    heading: str | None
    cas: str | None
    altitude: str | None
    action: str | None
    form: str | None
    comment: str | None
    coord_x: int | None
    coord_y: int | None


@dataclass(frozen=True)
class LegacyPackageElement:
    callsign: str | None
    flight: str | None
    role: str | None
    aircraft: str | None
    task: str | None
    takeoff: str | None
    push: str | None
    tot: str | None
    iff: str | None
    primary: bool
    steerpoints: list[LegacySteerpoint]
    unit_id: VUId


@dataclass(frozen=True)
class LegacyOverview:
    callsign: str | None
    mission_type: str | None
    package_id: str | None
    package_description: str | None
    package_mission: str | None
    target_area: str | None
    time_on_target: str | None
    sunrise: str | None
    sunset: str | None
    bullseye: BullseyeInfo


@dataclass(frozen=True)
class LegacyBriefingPackage:
    overview: LegacyOverview
    package: list[LegacyPackageElement]


def _to_vuid(value: Any) -> VUId | None:
    if not isinstance(value, dict):
        return None
    num = value.get("num")
    creator = value.get("creator")
    if not isinstance(num, int) or not isinstance(creator, int):
        return None
    return VUId(num=num, creator=creator)


def _load_strings(bms_base_dir: Path | None) -> dict[int, str]:
    strings_path = cam_parser._find_support_file(
        "Strings.txt",
        support_base_dir=bms_base_dir,
    )
    if strings_path is None:
        strings_path = cam_parser._find_support_file(
            "strings.txt",
            support_base_dir=bms_base_dir,
        )
    if strings_path is None:
        return {}
    return cam_parser._load_strings_by_id(strings_path)


def _collect_package_numbers(uni_parsed: dict[str, Any]) -> list[int]:
    packages = uni_parsed.get("packages")
    if not isinstance(packages, list):
        return []
    numbers: set[int] = set()
    for package in packages:
        if not isinstance(package, dict):
            continue
        number = package.get("package_number")
        if isinstance(number, int):
            numbers.add(number)
    return sorted(numbers)


def _steerpoints_from_record(record: dict[str, Any] | None) -> list[Steerpoint]:
    if not isinstance(record, dict):
        return []
    waypoints = record.get("waypoints")
    if not isinstance(waypoints, list):
        return []
    out: list[Steerpoint] = []
    for waypoint in waypoints:
        if not isinstance(waypoint, dict):
            continue
        index = waypoint.get("index")
        x = waypoint.get("x")
        y = waypoint.get("y")
        action = waypoint.get("action")
        route_action = waypoint.get("route_action")
        if not all(isinstance(v, int) for v in [index, x, y, action, route_action]):
            continue
        out.append(
            Steerpoint(
                index=index,
                x=x,
                y=y,
                action=action,
                route_action=route_action,
                arrive_z=waypoint.get("arrive_z")
                if isinstance(waypoint.get("arrive_z"), str)
                else None,
                depart_z=waypoint.get("depart_z")
                if isinstance(waypoint.get("depart_z"), str)
                else None,
            )
        )
    return out


def build_human_packages(
    parsed_cam: ParsedCamData,
    *,
    package_numbers: list[int] | None = None,
) -> list[HumanPackage]:
    logger.debug(
        "build_human_packages start: source=%s package_numbers=%s",
        parsed_cam.source_path,
        package_numbers,
    )
    uni_parsed = parsed_cam.get_parsed_by_ext(".uni")
    cmp_parsed = parsed_cam.get_parsed_by_ext(".cmp")
    if not isinstance(uni_parsed, dict):
        logger.error("build_human_packages failed: parsed .uni entry is missing")
        raise ValueError("Parsed CAM data does not contain parsed .uni entry")
    if not isinstance(cmp_parsed, dict):
        logger.error("build_human_packages failed: parsed .cmp entry is missing")
        raise ValueError("Parsed CAM data does not contain parsed .cmp entry")

    selected_numbers = package_numbers or _collect_package_numbers(uni_parsed)
    generated = cam_parser.list_package_generated_flights(uni_parsed, selected_numbers)

    strings_by_id = _load_strings(parsed_cam.bms_base_dir)
    bullseye_name_id = (
        cmp_parsed.get("bullseye_name_id")
        if isinstance(cmp_parsed.get("bullseye_name_id"), int)
        else None
    )
    bullseye = BullseyeInfo(
        x=cmp_parsed.get("bullseye_x")
        if isinstance(cmp_parsed.get("bullseye_x"), int)
        else None,
        y=cmp_parsed.get("bullseye_y")
        if isinstance(cmp_parsed.get("bullseye_y"), int)
        else None,
        name_id=bullseye_name_id,
        name=strings_by_id.get(bullseye_name_id) if bullseye_name_id is not None else None,
    )

    records = uni_parsed.get("records")
    record_by_id: dict[tuple[int, int], dict[str, Any]] = {}
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            record_id = _to_vuid(record.get("id"))
            if record_id is None:
                continue
            record_by_id[(record_id.num, record_id.creator)] = record

    out: list[HumanPackage] = []
    for query in generated:
        if not isinstance(query, dict):
            continue
        matches = query.get("matches")
        if not isinstance(matches, list):
            continue
        for match in matches:
            if not isinstance(match, dict):
                continue

            package_id = _to_vuid(match.get("package_id"))
            package_mission = match.get("package_mission")
            package_timing = match.get("timing")

            flights_raw = match.get("generated_flights")
            flights: list[HumanFlight] = []
            if isinstance(flights_raw, list):
                for flight_raw in flights_raw:
                    if not isinstance(flight_raw, dict):
                        continue
                    unit_id = _to_vuid(flight_raw.get("unit_id"))
                    if unit_id is None:
                        continue
                    timing = flight_raw.get("timing")
                    if not isinstance(timing, dict):
                        timing = {}
                    squadron_callsign = flight_raw.get("squadron_callsign")
                    flight_mission = flight_raw.get("flight_mission")
                    callsign_profile = flight_raw.get("callsign_profile")
                    callsign = None
                    if isinstance(squadron_callsign, dict):
                        value = squadron_callsign.get("callsign")
                        if isinstance(value, str):
                            callsign = value
                    aircraft = None
                    if isinstance(callsign_profile, dict):
                        value = callsign_profile.get("vehicle_name")
                        if isinstance(value, str):
                            aircraft = value
                    mission = None
                    if isinstance(flight_mission, dict):
                        value = flight_mission.get("mission_name")
                        if isinstance(value, str):
                            mission = value

                    record = record_by_id.get((unit_id.num, unit_id.creator))
                    flights.append(
                        HumanFlight(
                            unit_id=unit_id,
                            unit_kind=flight_raw.get("unit_kind")
                            if isinstance(flight_raw.get("unit_kind"), str)
                            else None,
                            flight_number=flight_raw.get("air_task_number")
                            if isinstance(flight_raw.get("air_task_number"), int)
                            else None,
                            callsign=callsign,
                            aircraft=aircraft,
                            mission=mission,
                            takeoff_z=timing.get("takeoff_time_z")
                            if isinstance(timing.get("takeoff_time_z"), str)
                            else None,
                            push_z=timing.get("push_time_z")
                            if isinstance(timing.get("push_time_z"), str)
                            else None,
                            tot_z=timing.get("time_on_target_z")
                            if isinstance(timing.get("time_on_target_z"), str)
                            else None,
                            steerpoints=_steerpoints_from_record(record),
                        )
                    )

            out.append(
                HumanPackage(
                    package_id=package_id,
                    package_number=match.get("package_number")
                    if isinstance(match.get("package_number"), int)
                    else None,
                    mission=package_mission.get("mission_name")
                    if isinstance(package_mission, dict)
                    and isinstance(package_mission.get("mission_name"), str)
                    else None,
                    takeoff_z=package_timing.get("takeoff_time_z")
                    if isinstance(package_timing, dict)
                    and isinstance(package_timing.get("takeoff_time_z"), str)
                    else None,
                    push_z=package_timing.get("push_time_z")
                    if isinstance(package_timing, dict)
                    and isinstance(package_timing.get("push_time_z"), str)
                    else None,
                    tot_z=package_mission.get("time_on_target_z")
                    if isinstance(package_mission, dict)
                    and isinstance(package_mission.get("time_on_target_z"), str)
                    else None,
                    bullseye=bullseye,
                    flights=flights,
                )
            )

    logger.debug("build_human_packages done: packages=%d", len(out))
    return out


def _to_legacy_steerpoint(steerpoint: Steerpoint) -> LegacySteerpoint:
    return LegacySteerpoint(
        number=str(steerpoint.index),
        description=f"WP {steerpoint.index}",
        time=steerpoint.arrive_z,
        distance=None,
        heading=None,
        cas=None,
        altitude=None,
        action=str(steerpoint.action),
        form=None,
        comment=None,
        coord_x=steerpoint.x,
        coord_y=steerpoint.y,
    )


def build_legacy_briefing_packages(
    parsed_cam: ParsedCamData,
    *,
    package_numbers: list[int] | None = None,
) -> list[LegacyBriefingPackage]:
    logger.debug(
        "build_legacy_briefing_packages start: source=%s package_numbers=%s",
        parsed_cam.source_path,
        package_numbers,
    )
    human_packages = build_human_packages(parsed_cam, package_numbers=package_numbers)
    out: list[LegacyBriefingPackage] = []

    for human_package in human_packages:
        overview = LegacyOverview(
            callsign=human_package.flights[0].callsign if human_package.flights else None,
            mission_type=human_package.mission,
            package_id=str(human_package.package_number)
            if human_package.package_number is not None
            else None,
            package_description=None,
            package_mission=human_package.mission,
            target_area=f"{human_package.bullseye.x}, {human_package.bullseye.y}"
            if human_package.bullseye.x is not None and human_package.bullseye.y is not None
            else None,
            time_on_target=human_package.tot_z,
            sunrise=None,
            sunset=None,
            bullseye=human_package.bullseye,
        )

        package_elements: list[LegacyPackageElement] = []
        for index, flight in enumerate(human_package.flights):
            package_elements.append(
                LegacyPackageElement(
                    callsign=flight.callsign,
                    flight=str(flight.flight_number)
                    if flight.flight_number is not None
                    else None,
                    role=flight.unit_kind,
                    aircraft=flight.aircraft,
                    task=flight.mission,
                    takeoff=flight.takeoff_z,
                    push=flight.push_z,
                    tot=flight.tot_z,
                    iff=None,
                    primary=index == 0,
                    steerpoints=[_to_legacy_steerpoint(sp) for sp in flight.steerpoints],
                    unit_id=flight.unit_id,
                )
            )

        out.append(LegacyBriefingPackage(overview=overview, package=package_elements))

    logger.debug("build_legacy_briefing_packages done: packages=%d", len(out))
    return out
