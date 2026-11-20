"""Deterministic `.tea` team-record parsing."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace as replace_dataclass

from .binary import BinaryParseError, BinaryReader, I16, U16, U32, U8, VUID, VuId
from .cam_container import DecodedEntry


TEAM_COUNT = 8
TEAM_HEADER_SIZE_CURRENT = 8 + 2 + 1 + 1 + 2 + TEAM_COUNT + (TEAM_COUNT * 2)
TEAM_BODY_SIZE_CURRENT = 748
TEAM_TAIL_SIZE_CURRENT = TEAM_BODY_SIZE_CURRENT - TEAM_HEADER_SIZE_CURRENT
ATM_BASE_SIZE_CURRENT = 8 + 2 + 2 + 1 + 2 + 2 + 2 + 1 + 1 + 1 + 2
TASKING_MANAGER_SIZE = 8 + 2 + 2 + 1 + 2
ATM_AIRBASE_SIZE = 8 + 32
MISSION_REQUEST_SIZE_CURRENT = 76
MISSION_REQUEST_SIZE_LEGACY = 64
MISSION_REQUEST_REFERENCE_FIELDS = (
    "requester_id",
    "target_id",
    "secondary_id",
    "pak_id",
)
TEAM_EDITABLE_FIELDS = {
    "unit_id",
    "entity_type",
    "who",
    "cteam",
    "flags",
    "reinforcement",
}
ATM_EDITABLE_FIELDS = {
    "manager_id",
    "entity_type",
    "manager_flags",
    "owner",
    "flags",
    "average_ca_strength",
    "average_ca_missions",
    "sample_cycles",
    "cycle",
}
TASKING_MANAGER_EDITABLE_FIELDS = {
    "manager_id",
    "entity_type",
    "manager_flags",
    "owner",
    "flags",
}
MISSION_REQUEST_EDITABLE_FIELDS = {
    "requester_id",
    "target_id",
    "secondary_id",
    "pak_id",
    "who",
    "vs",
    "tot",
    "tx",
    "ty",
    "flags",
    "caps",
    "target_num",
    "speed",
    "match_strength",
    "priority",
    "tot_type",
    "action_type",
    "mission",
    "aircraft",
    "context",
    "roe_check",
    "delayed",
    "start_block",
    "final_block",
    "slots",
    "min_to",
    "max_to",
}

STANCE_UNKNOWN = 0
STANCE_ALLIED = 1
STANCE_FRIENDLY = 2
STANCE_NEUTRAL = 3
STANCE_HOSTILE = 4
STANCE_AT_WAR = 5
STANCE_NAMES = {
    STANCE_UNKNOWN: "Unknown",
    STANCE_ALLIED: "Allied",
    STANCE_FRIENDLY: "Friendly",
    STANCE_NEUTRAL: "Neutral",
    STANCE_HOSTILE: "Hostile",
    STANCE_AT_WAR: "At War",
}


class TeaRecordError(RuntimeError):
    """Raised when a `.tea` record cannot be split deterministically."""


class TeaRequestEditError(TeaRecordError):
    """Raised before an invalid mission-request edit can mutate `.tea`."""


@dataclass(frozen=True)
class TeamInfo:
    start_offset: int
    unit_id: VuId
    entity_type: int
    who: int
    cteam: int
    flags: int
    member: tuple[int, ...]
    stance: tuple[int, ...]
    reinforcement_prefix_raw: bytes
    reinforcement: int
    reinforcement_suffix_raw: bytes

    @property
    def tail_raw(self) -> bytes:
        """Lossless compatibility view of the bytes after the stable header."""

        return (
            self.reinforcement_prefix_raw
            + I16.encode(self.reinforcement)
            + self.reinforcement_suffix_raw
        )

    def stance_name(self, team: int) -> str | None:
        if not 0 <= team < len(self.stance):
            return None
        return STANCE_NAMES.get(self.stance[team])


@dataclass(frozen=True)
class AtmAirbase:
    airbase_id: VuId
    schedule_raw: bytes


@dataclass(frozen=True)
class MissionRequest:
    start_offset: int
    requester_id: VuId
    target_id: VuId
    secondary_id: VuId
    pak_id: VuId
    who: int
    vs: int
    padding_raw: bytes
    tot: int
    tx: int
    ty: int
    flags: int
    caps: int
    target_num: int
    speed: int
    match_strength: int
    priority: int
    tot_type: int
    action_type: int
    mission: int
    aircraft: int
    context: int
    roe_check: int
    delayed: int
    start_block: int
    final_block: int
    slots: tuple[int, ...]
    min_to: int
    max_to: int
    morepadding_raw: bytes
    raw: bytes


@dataclass(frozen=True)
class TeaMissionRequestReference:
    """One exact VU_ID reference from one typed `.tea` mission request."""

    team_index: int
    request_index: int
    field_name: str
    referenced_id: VuId
    request: MissionRequest


@dataclass(frozen=True)
class AirTaskingManager:
    start_offset: int
    manager_id: VuId
    entity_type: int
    manager_flags: int
    owner: int
    flags: int
    average_ca_strength: int | None
    average_ca_missions: int | None
    sample_cycles: int | None
    airbases: tuple[AtmAirbase, ...]
    cycle: int
    mission_requests: tuple[MissionRequest, ...]
    mission_requests_raw: tuple[bytes, ...]


@dataclass(frozen=True)
class TaskingManager:
    start_offset: int
    manager_id: VuId
    entity_type: int
    manager_flags: int
    owner: int
    flags: int


@dataclass(frozen=True)
class TeamRecord:
    start_offset: int
    end_offset: int
    team: TeamInfo
    atm: AirTaskingManager
    gtm: TaskingManager
    ntm: TaskingManager


@dataclass(frozen=True)
class TeaRecord:
    num_teams_raw: int
    team_records: tuple[TeamRecord, ...]
    raw: bytes

    @property
    def num_teams(self) -> int:
        return min(max(self.num_teams_raw, 0), TEAM_COUNT)

    @property
    def team_headers(self) -> tuple[TeamInfo, ...]:
        return tuple(record.team for record in self.team_records)

    def to_bytes(self) -> bytes:
        return encode_tea_record(self)


class TeaMissionRequestCollection:
    """Entry-backed editor for all deterministically typed `.tea` fields."""

    def __init__(self, entry: DecodedEntry, record: TeaRecord) -> None:
        if not entry.name.lower().endswith(".tea"):
            raise ValueError(f"expected a .tea entry, got {entry.name!r}")
        encoded = encode_tea_record(record)
        if encoded != entry.decoded:
            raise TeaRequestEditError(
                f"{entry.name}: parsed record does not encode to the entry payload"
            )
        self.entry = entry
        self.record = record

    @property
    def mission_requests(self) -> tuple[MissionRequest, ...]:
        return tuple(
            request
            for team_record in self.record.team_records
            for request in team_record.atm.mission_requests
        )

    def set_team_field(
        self,
        team_index: int,
        field_name: str,
        value: object,
    ) -> TeamInfo:
        """Atomically set one existing fixed-width `TeamInfo` field."""

        if field_name not in TEAM_EDITABLE_FIELDS:
            raise TeaRequestEditError(f"unknown editable team field {field_name!r}")
        team_record = self._team_record(team_index)
        if field_name == "unit_id":
            value = _validated_vuid(value, name=field_name)
        else:
            _require_integer(field_name, value)
        team = replace_dataclass(team_record.team, **{field_name: value})
        self._replace_team_record(
            team_index,
            replace_dataclass(team_record, team=team),
        )
        return self.record.team_records[team_index].team

    def set_team_member(
        self,
        team_index: int,
        member_index: int,
        value: int,
    ) -> TeamInfo:
        team_record = self._team_record(team_index)
        members = list(team_record.team.member)
        _validate_index("team member", member_index, len(members))
        _validate_u8("team member", value)
        members[member_index] = value
        team = replace_dataclass(team_record.team, member=tuple(members))
        self._replace_team_record(
            team_index,
            replace_dataclass(team_record, team=team),
        )
        return self.record.team_records[team_index].team

    def set_team_stance(
        self,
        team_index: int,
        other_team: int,
        value: int,
    ) -> TeamInfo:
        team_record = self._team_record(team_index)
        stances = list(team_record.team.stance)
        _validate_index("team stance", other_team, len(stances))
        _validate_i16("team stance", value)
        stances[other_team] = value
        team = replace_dataclass(team_record.team, stance=tuple(stances))
        self._replace_team_record(
            team_index,
            replace_dataclass(team_record, team=team),
        )
        return self.record.team_records[team_index].team

    def set_atm_field(
        self,
        team_index: int,
        field_name: str,
        value: object,
    ) -> AirTaskingManager:
        """Atomically set one typed AirTaskingManager field."""

        if field_name not in ATM_EDITABLE_FIELDS:
            raise TeaRequestEditError(f"unknown editable ATM field {field_name!r}")
        team_record = self._team_record(team_index)
        if getattr(team_record.atm, field_name) is None:
            raise TeaRequestEditError(
                f"this .tea version has no serialized ATM {field_name} field"
            )
        if field_name == "manager_id":
            value = _validated_vuid(value, name=field_name)
        else:
            _require_integer(field_name, value)
        atm = replace_dataclass(team_record.atm, **{field_name: value})
        self._replace_team_record(
            team_index,
            replace_dataclass(team_record, atm=atm),
        )
        return self.record.team_records[team_index].atm

    def set_tasking_manager_field(
        self,
        team_index: int,
        manager_name: str,
        field_name: str,
        value: object,
    ) -> TaskingManager:
        """Atomically set one typed GTM or NTM manager field."""

        if manager_name not in {"gtm", "ntm"}:
            raise TeaRequestEditError("manager_name must be 'gtm' or 'ntm'")
        if field_name not in TASKING_MANAGER_EDITABLE_FIELDS:
            raise TeaRequestEditError(
                f"unknown editable tasking-manager field {field_name!r}"
            )
        team_record = self._team_record(team_index)
        manager = getattr(team_record, manager_name)
        if field_name == "manager_id":
            value = _validated_vuid(value, name=field_name)
        else:
            _require_integer(field_name, value)
        replacement = replace_dataclass(manager, **{field_name: value})
        self._replace_team_record(
            team_index,
            replace_dataclass(team_record, **{manager_name: replacement}),
        )
        return getattr(self.record.team_records[team_index], manager_name)

    def set_airbase_id(
        self,
        team_index: int,
        airbase_index: int,
        value: VuId,
    ) -> AtmAirbase:
        team_record = self._team_record(team_index)
        airbases = list(team_record.atm.airbases)
        _validate_index("ATM airbase", airbase_index, len(airbases))
        airbases[airbase_index] = replace_dataclass(
            airbases[airbase_index],
            airbase_id=_validated_vuid(value, name="airbase_id"),
        )
        atm = replace_dataclass(team_record.atm, airbases=tuple(airbases))
        self._replace_team_record(
            team_index,
            replace_dataclass(team_record, atm=atm),
        )
        return self.record.team_records[team_index].atm.airbases[airbase_index]

    def set_airbase_schedule_raw(
        self,
        team_index: int,
        airbase_index: int,
        value: bytes,
    ) -> AtmAirbase:
        """Replace the exact still-opaque 32-byte airbase schedule."""

        team_record = self._team_record(team_index)
        airbases = list(team_record.atm.airbases)
        _validate_index("ATM airbase", airbase_index, len(airbases))
        if not isinstance(value, bytes) or len(value) != 32:
            raise TeaRequestEditError("ATM airbase schedule_raw must be exactly 32 bytes")
        airbases[airbase_index] = replace_dataclass(
            airbases[airbase_index],
            schedule_raw=value,
        )
        atm = replace_dataclass(team_record.atm, airbases=tuple(airbases))
        self._replace_team_record(
            team_index,
            replace_dataclass(team_record, atm=atm),
        )
        return self.record.team_records[team_index].atm.airbases[airbase_index]

    def update_request(
        self,
        request: MissionRequest,
        **changes: object,
    ) -> MissionRequest:
        """Atomically replace typed fields on one exact modern request."""

        if not isinstance(request, MissionRequest):
            raise TypeError("request must be a MissionRequest")
        if not changes:
            return request
        unknown = set(changes) - MISSION_REQUEST_EDITABLE_FIELDS
        if unknown:
            raise TeaRequestEditError(
                f"unknown editable mission-request field {sorted(unknown)[0]!r}"
            )
        validated = dict(changes)
        for field_name in set(validated) & set(MISSION_REQUEST_REFERENCE_FIELDS):
            validated[field_name] = _validated_vuid(
                validated[field_name],
                name=field_name,
            )
        for field_name, value in validated.items():
            if field_name in MISSION_REQUEST_REFERENCE_FIELDS:
                continue
            if field_name == "slots":
                if not isinstance(value, tuple) or len(value) != 4:
                    raise TeaRequestEditError("mission-request slots must be four values")
                for index, item in enumerate(value):
                    _validate_u8(f"mission-request slots[{index}]", item)
            else:
                _require_integer(field_name, value)

        candidate_teams: list[TeamRecord] = []
        replacement: MissionRequest | None = None
        matches = 0
        for team_record in self.record.team_records:
            atm = team_record.atm
            if len(atm.mission_requests) != len(atm.mission_requests_raw):
                raise TeaRequestEditError("cannot edit opaque legacy mission requests")
            candidate_requests = list(atm.mission_requests)
            candidate_raw = list(atm.mission_requests_raw)
            for index, current in enumerate(atm.mission_requests):
                if current is not request:
                    continue
                matches += 1
                edited = replace_dataclass(current, **validated)
                encoded = _encode_mission_request(edited)
                replacement = replace_dataclass(edited, raw=encoded)
                candidate_requests[index] = replacement
                candidate_raw[index] = encoded
            candidate_teams.append(
                replace_dataclass(
                    team_record,
                    atm=replace_dataclass(
                        atm,
                        mission_requests=tuple(candidate_requests),
                        mission_requests_raw=tuple(candidate_raw),
                    ),
                )
            )
        if matches != 1 or replacement is None:
            raise KeyError(f"mission request object matches {matches} current requests")
        self._commit(
            replace_dataclass(self.record, team_records=tuple(candidate_teams))
        )
        return replacement

    def references_to(
        self,
        referenced_id: VuId,
        *,
        field_names: Sequence[str] = MISSION_REQUEST_REFERENCE_FIELDS,
    ) -> tuple[TeaMissionRequestReference, ...]:
        """Return typed mission-request references to one exact VU_ID."""

        return self.references_to_many((referenced_id,), field_names=field_names)

    def references_to_many(
        self,
        referenced_ids: Sequence[VuId],
        *,
        field_names: Sequence[str] = MISSION_REQUEST_REFERENCE_FIELDS,
    ) -> tuple[TeaMissionRequestReference, ...]:
        """Return typed request references to any supplied exact VU_ID."""

        wanted = tuple(
            _validated_vuid(value, name=f"referenced_ids[{index}]")
            for index, value in enumerate(referenced_ids)
        )
        if len(set(wanted)) != len(wanted):
            raise TeaRequestEditError("referenced_ids contains duplicate VU_IDs")
        checked_fields = _validated_request_field_names(field_names)
        wanted_set = set(wanted)
        references: list[TeaMissionRequestReference] = []

        for team_index, team_record in enumerate(self.record.team_records):
            atm = team_record.atm
            if len(atm.mission_requests) != len(atm.mission_requests_raw):
                raise TeaRequestEditError(
                    "cannot inspect VU_IDs in opaque legacy mission requests"
                )
            for request_index, request in enumerate(atm.mission_requests):
                for field_name in checked_fields:
                    value = getattr(request, field_name)
                    if value in wanted_set:
                        references.append(
                            TeaMissionRequestReference(
                                team_index=team_index,
                                request_index=request_index,
                                field_name=field_name,
                                referenced_id=value,
                                request=request,
                            )
                        )
        return tuple(references)

    def remove_request(self, request: MissionRequest) -> MissionRequest:
        """Remove one exact current typed request object."""

        return self.remove_requests((request,))[0]

    def set_reference_id(
        self,
        request: MissionRequest,
        field_name: str,
        value: VuId,
    ) -> MissionRequest:
        """Atomically set one VU_ID field on one exact current request."""

        checked_field = _validated_request_field_names((field_name,))[0]
        candidate_id = _validated_vuid(value, name=checked_field)
        return self.update_request(request, **{checked_field: candidate_id})

    def clear_reference_id(
        self,
        request: MissionRequest,
        field_name: str,
    ) -> MissionRequest:
        """Atomically store `(0, 0)` in one exact request VU_ID field."""

        return self.set_reference_id(request, field_name, (0, 0))

    def remove_requests(
        self,
        requests: Sequence[MissionRequest],
    ) -> tuple[MissionRequest, ...]:
        """Atomically remove exact current typed request objects."""

        if any(not isinstance(request, MissionRequest) for request in requests):
            raise TypeError("requests must contain MissionRequest objects")
        wanted_objects = {id(request) for request in requests}
        if len(wanted_objects) != len(requests):
            raise TeaRequestEditError("requests contains duplicate objects")
        if not requests:
            return ()

        removed: list[MissionRequest] = []
        candidate_teams: list[TeamRecord] = []
        for team_record in self.record.team_records:
            atm = team_record.atm
            if len(atm.mission_requests) != len(atm.mission_requests_raw):
                raise TeaRequestEditError(
                    "cannot edit opaque legacy mission requests"
                )
            kept_requests: list[MissionRequest] = []
            kept_raw: list[bytes] = []
            for current, raw in zip(
                atm.mission_requests,
                atm.mission_requests_raw,
                strict=True,
            ):
                if id(current) in wanted_objects:
                    removed.append(current)
                else:
                    kept_requests.append(current)
                    kept_raw.append(raw)
            candidate_teams.append(
                replace_dataclass(
                    team_record,
                    atm=replace_dataclass(
                        atm,
                        mission_requests=tuple(kept_requests),
                        mission_requests_raw=tuple(kept_raw),
                    ),
                )
            )

        found_objects = {id(request) for request in removed}
        missing = wanted_objects - found_objects
        if missing:
            raise KeyError(f"{len(missing)} mission request object(s) are not current")

        candidate = replace_dataclass(
            self.record,
            team_records=tuple(candidate_teams),
        )
        self._commit(candidate)
        return tuple(removed)

    def remove_referencing(
        self,
        referenced_ids: Sequence[VuId],
        *,
        field_names: Sequence[str] = MISSION_REQUEST_REFERENCE_FIELDS,
    ) -> tuple[MissionRequest, ...]:
        """Remove requests referencing any ID through selected VU_ID fields."""

        references = self.references_to_many(
            referenced_ids,
            field_names=field_names,
        )
        requests: list[MissionRequest] = []
        seen: set[int] = set()
        for reference in references:
            identity = id(reference.request)
            if identity not in seen:
                seen.add(identity)
                requests.append(reference.request)
        return self.remove_requests(tuple(requests))

    def _team_record(self, team_index: int) -> TeamRecord:
        _validate_index("team", team_index, len(self.record.team_records))
        return self.record.team_records[team_index]

    def _replace_team_record(self, team_index: int, team_record: TeamRecord) -> None:
        teams = list(self.record.team_records)
        teams[team_index] = team_record
        self._commit(replace_dataclass(self.record, team_records=tuple(teams)))

    def _commit(self, record: TeaRecord) -> None:
        try:
            payload = encode_tea_record(record)
        except TeaRequestEditError:
            raise
        except (TeaRecordError, TypeError, ValueError, OverflowError) as exc:
            raise TeaRequestEditError(
                f"candidate .tea record cannot be encoded: {exc}"
            ) from exc
        self.entry.set_decoded(payload)
        self.record = replace_dataclass(record, raw=payload)


# The original public name is retained for compatibility, but the collection
# now edits every deterministically typed field in the record rather than only
# mission-request references.
TeaRecordEditor = TeaMissionRequestCollection


def encode_tea_record(record: TeaRecord) -> bytes:
    """Encode parsed `.tea` fields while preserving opaque regions exactly."""

    if record.num_teams != len(record.team_records):
        raise TeaRecordError(
            f"header declares {record.num_teams} parsed teams, "
            f"got {len(record.team_records)} team records"
        )

    payload = bytearray(I16.encode(record.num_teams_raw))
    for team_record in record.team_records:
        payload.extend(_encode_team_info(team_record.team))
        payload.extend(_encode_air_tasking_manager(team_record.atm))
        payload.extend(_encode_tasking_manager(team_record.gtm))
        payload.extend(_encode_tasking_manager(team_record.ntm))
    return bytes(payload)


def _encode_team_info(team: TeamInfo) -> bytes:
    payload = bytearray()
    payload.extend(VUID.encode(team.unit_id))
    payload.extend(U16.encode(team.entity_type))
    payload.extend(U8.encode(team.who))
    payload.extend(U8.encode(team.cteam))
    payload.extend(I16.encode(team.flags))
    payload.extend(_encode_u8_values(team.member, name="team member"))
    payload.extend(_encode_i16_values(team.stance))
    payload.extend(team.reinforcement_prefix_raw)
    payload.extend(I16.encode(team.reinforcement))
    payload.extend(team.reinforcement_suffix_raw)
    return bytes(payload)


def _encode_air_tasking_manager(atm: AirTaskingManager) -> bytes:
    payload = bytearray()
    payload.extend(VUID.encode(atm.manager_id))
    payload.extend(U16.encode(atm.entity_type))
    payload.extend(I16.encode(atm.manager_flags))
    payload.extend(U8.encode(atm.owner))
    payload.extend(I16.encode(atm.flags))
    if atm.average_ca_strength is not None:
        payload.extend(I16.encode(atm.average_ca_strength))
    if atm.average_ca_missions is not None:
        payload.extend(I16.encode(atm.average_ca_missions))
    if atm.sample_cycles is not None:
        payload.extend(U8.encode(atm.sample_cycles))
    if len(atm.airbases) > 0xFF:
        raise TeaRecordError(f"ATM airbase count exceeds uint8: {len(atm.airbases)}")
    payload.extend(U8.encode(len(atm.airbases)))
    for airbase in atm.airbases:
        if len(airbase.schedule_raw) != 32:
            raise TeaRecordError(
                f"ATM airbase schedule expected 32 bytes, got {len(airbase.schedule_raw)}"
            )
        payload.extend(VUID.encode(airbase.airbase_id))
        payload.extend(airbase.schedule_raw)
    payload.extend(U8.encode(atm.cycle))

    request_count = len(atm.mission_requests_raw)
    if request_count > 0x7FFF:
        raise TeaRecordError(
            f"ATM mission-request count exceeds int16: {request_count}"
        )
    if atm.mission_requests:
        if len(atm.mission_requests) != request_count:
            raise TeaRecordError(
                "typed and raw ATM mission-request counts do not match"
            )
        for index, (request, raw) in enumerate(
            zip(atm.mission_requests, atm.mission_requests_raw, strict=True)
        ):
            if _encode_mission_request(request) != raw:
                raise TeaRecordError(
                    f"ATM mission request {index} typed fields do not match raw bytes"
                )
            if len(raw) != MISSION_REQUEST_SIZE_CURRENT:
                raise TeaRecordError(
                    f"ATM mission request {index} expected "
                    f"{MISSION_REQUEST_SIZE_CURRENT} bytes, got {len(raw)}"
                )
    else:
        for index, raw in enumerate(atm.mission_requests_raw):
            if len(raw) != MISSION_REQUEST_SIZE_LEGACY:
                raise TeaRecordError(
                    f"legacy ATM mission request {index} expected "
                    f"{MISSION_REQUEST_SIZE_LEGACY} bytes, got {len(raw)}"
                )

    payload.extend(I16.encode(request_count))
    for raw in atm.mission_requests_raw:
        payload.extend(raw)
    return bytes(payload)


def _encode_mission_request(request: MissionRequest) -> bytes:
    if len(request.padding_raw) != 2:
        raise TeaRecordError(
            f"mission-request padding expected 2 bytes, got {len(request.padding_raw)}"
        )
    if len(request.slots) != 4:
        raise TeaRecordError(
            f"mission-request slots expected 4 values, got {len(request.slots)}"
        )
    if len(request.morepadding_raw) != 3:
        raise TeaRecordError(
            "mission-request trailing padding expected 3 bytes, "
            f"got {len(request.morepadding_raw)}"
        )
    try:
        payload = bytearray()
        payload.extend(VUID.encode(request.requester_id))
        payload.extend(VUID.encode(request.target_id))
        payload.extend(VUID.encode(request.secondary_id))
        payload.extend(VUID.encode(request.pak_id))
        payload.extend(U8.encode(request.who))
        payload.extend(U8.encode(request.vs))
        payload.extend(request.padding_raw)
        payload.extend(U32.encode(request.tot))
        payload.extend(I16.encode(request.tx))
        payload.extend(I16.encode(request.ty))
        payload.extend(U32.encode(request.flags))
        payload.extend(I16.encode(request.caps))
        payload.extend(I16.encode(request.target_num))
        payload.extend(I16.encode(request.speed))
        payload.extend(I16.encode(request.match_strength))
        payload.extend(I16.encode(request.priority))
        payload.extend(U8.encode(request.tot_type))
        payload.extend(U8.encode(request.action_type))
        payload.extend(U8.encode(request.mission))
        payload.extend(U8.encode(request.aircraft))
        payload.extend(U8.encode(request.context))
        payload.extend(U8.encode(request.roe_check))
        payload.extend(U8.encode(request.delayed))
        payload.extend(U8.encode(request.start_block))
        payload.extend(U8.encode(request.final_block))
        payload.extend(_encode_u8_values(request.slots, name="mission-request slots"))
        payload.extend(U8.encode(request.min_to))
        payload.extend(U8.encode(request.max_to))
        payload.extend(request.morepadding_raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TeaRecordError(f"mission request cannot be encoded: {exc}") from exc
    if len(payload) != MISSION_REQUEST_SIZE_CURRENT:
        raise TeaRecordError(
            f"mission request encoded to {len(payload)} bytes, "
            f"expected {MISSION_REQUEST_SIZE_CURRENT}"
        )
    return bytes(payload)


def _encode_tasking_manager(manager: TaskingManager) -> bytes:
    payload = bytearray()
    payload.extend(VUID.encode(manager.manager_id))
    payload.extend(U16.encode(manager.entity_type))
    payload.extend(I16.encode(manager.manager_flags))
    payload.extend(U8.encode(manager.owner))
    payload.extend(I16.encode(manager.flags))
    return bytes(payload)


def _encode_u8_values(values: tuple[int, ...], *, name: str) -> bytes:
    try:
        return b"".join(U8.encode(value) for value in values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TeaRecordError(f"{name} values cannot be encoded: {exc}") from exc


def _encode_i16_values(values: tuple[int, ...]) -> bytes:
    try:
        return b"".join(I16.encode(value) for value in values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TeaRecordError(f"team stance values cannot be encoded: {exc}") from exc


def _validated_request_field_names(field_names: Sequence[str]) -> tuple[str, ...]:
    checked = tuple(field_names)
    if len(set(checked)) != len(checked):
        raise TeaRequestEditError("field_names contains duplicates")
    for field_name in checked:
        if field_name not in MISSION_REQUEST_REFERENCE_FIELDS:
            raise TeaRequestEditError(
                f"unknown mission-request VU_ID field {field_name!r}"
            )
    return checked


def _validated_vuid(value: object, *, name: str) -> VuId:
    if not isinstance(value, tuple) or len(value) != 2:
        raise TeaRequestEditError(f"{name} must be a (num, creator) tuple")
    num, creator = value
    if type(num) is not int or type(creator) is not int:
        raise TeaRequestEditError(f"{name} values must be integers")
    if not 0 <= num <= 0xFFFFFFFF or not 0 <= creator <= 0xFFFFFFFF:
        raise TeaRequestEditError(f"{name} values must fit in uint32")
    return num, creator


def _require_integer(name: str, value: object) -> None:
    if type(value) is not int:
        raise TeaRequestEditError(f"{name} must be an integer")


def _validate_index(name: str, index: object, count: int) -> None:
    if type(index) is not int or not 0 <= index < count:
        raise TeaRequestEditError(
            f"{name} index {index!r} is out of range for {count} values"
        )


def _validate_u8(name: str, value: object) -> None:
    if type(value) is not int or not 0 <= value <= 0xFF:
        raise TeaRequestEditError(f"{name} must fit in uint8, got {value!r}")


def _validate_i16(name: str, value: object) -> None:
    if type(value) is not int or not -0x8000 <= value <= 0x7FFF:
        raise TeaRequestEditError(f"{name} must fit in int16, got {value!r}")


def parse_tea_record(
    entry: DecodedEntry,
    *,
    container_version: int | None = None,
) -> TeaRecord:
    """Parse one decoded `.tea` entry into deterministic team records."""

    if not entry.name.lower().endswith(".tea"):
        raise ValueError(f"expected a .tea entry, got {entry.name!r}")
    return split_tea_record(entry.decoded, version=container_version)


def parse_tea_request_collection(
    entry: DecodedEntry,
    *,
    container_version: int | None = None,
) -> TeaMissionRequestCollection:
    """Parse an entry into a writable mission-request collection."""

    return TeaMissionRequestCollection(
        entry,
        parse_tea_record(entry, container_version=container_version),
    )


def parse_tea_record_editor(
    entry: DecodedEntry,
    *,
    container_version: int | None = None,
) -> TeaRecordEditor:
    """Parse an entry into a writer for all deterministically typed fields."""

    return TeaRecordEditor(
        entry,
        parse_tea_record(entry, container_version=container_version),
    )


def split_tea_record(data: bytes, *, version: int | None = None) -> TeaRecord:
    reader = BinaryReader(data)
    try:
        num_teams_raw = reader.i16()
    except BinaryParseError as exc:
        raise TeaRecordError(f"truncated .tea header: {exc}") from exc
    if num_teams_raw < 0:
        raise TeaRecordError(f"negative .tea team count {num_teams_raw}")

    team_count = min(num_teams_raw, TEAM_COUNT)
    records: list[TeamRecord] = []
    for _ in range(team_count):
        start = reader.tell()
        try:
            team = _read_team_info(reader, version=version)
            atm = _read_air_tasking_manager(reader, version=version)
            gtm = _read_tasking_manager(reader)
            ntm = _read_tasking_manager(reader)
        except BinaryParseError as exc:
            raise TeaRecordError(
                f"truncated .tea team record at offset {start}: {exc}"
            ) from exc
        records.append(
            TeamRecord(
                start_offset=start,
                end_offset=reader.tell(),
                team=team,
                atm=atm,
                gtm=gtm,
                ntm=ntm,
            )
        )

    if reader.tell() != len(data):
        raise TeaRecordError(
            f"record walk ended at {reader.tell()}, decoded payload has {len(data)} bytes"
        )

    return TeaRecord(
        num_teams_raw=num_teams_raw,
        team_records=tuple(records),
        raw=data,
    )


def stance_name(value: int) -> str | None:
    return STANCE_NAMES.get(value)


def _read_team_info(reader: BinaryReader, *, version: int | None) -> TeamInfo:
    start = reader.tell()
    member_count = TEAM_COUNT if _supports(version, 3) else 7
    stance_count = TEAM_COUNT if _supports(version, 3) else 7
    header_size = 8 + 2 + 1 + 1 + 2 + member_count + (stance_count * 2)
    body_size = _team_body_size(version)
    if body_size < header_size:
        raise TeaRecordError(
            f".tea team body size {body_size} is smaller than header size {header_size}"
        )
    tail_size = body_size - header_size
    reinforcement_prefix_size = _team_reinforcement_prefix_size(version)
    if reinforcement_prefix_size + 2 > tail_size:
        raise TeaRecordError(
            ".tea team body is too small for the reinforcement counter"
        )
    team = TeamInfo(
        start_offset=start,
        unit_id=reader.vu_id(),
        entity_type=reader.u16(),
        who=reader.u8(),
        cteam=reader.u8(),
        flags=reader.i16(),
        member=tuple(reader.u8() for _ in range(member_count)),
        stance=tuple(reader.i16() for _ in range(stance_count)),
        reinforcement_prefix_raw=reader.read_bytes(reinforcement_prefix_size),
        reinforcement=reader.i16(),
        reinforcement_suffix_raw=reader.read_bytes(
            tail_size - reinforcement_prefix_size - 2
        ),
    )
    if reader.tell() - start != body_size:
        raise TeaRecordError("internal .tea team body size mismatch")
    return team


def _read_air_tasking_manager(
    reader: BinaryReader,
    *,
    version: int | None,
) -> AirTaskingManager:
    start = reader.tell()
    manager_id = reader.vu_id()
    entity_type = reader.u16()
    manager_flags = reader.i16()
    owner = reader.u8()
    flags = reader.i16()
    average_ca_strength = reader.i16() if _supports(version, 63) else None
    average_ca_missions = reader.i16() if _supports(version, 28) else None
    sample_cycles = reader.u8() if _supports(version, 28) else None
    airbase_count = reader.u8()
    airbases = tuple(_read_atm_airbase(reader) for _ in range(airbase_count))
    cycle = reader.u8()
    mission_request_count = reader.i16()
    if mission_request_count < 0:
        raise TeaRecordError(
            f"negative .tea mission request count {mission_request_count} at offset {start}"
        )
    if _supports(version, 35):
        mission_requests = tuple(
            _read_mission_request(reader) for _ in range(mission_request_count)
        )
        mission_requests_raw = tuple(request.raw for request in mission_requests)
    else:
        mission_requests = ()
        mission_requests_raw = tuple(
            reader.read_bytes(MISSION_REQUEST_SIZE_LEGACY)
            for _ in range(mission_request_count)
        )

    return AirTaskingManager(
        start_offset=start,
        manager_id=manager_id,
        entity_type=entity_type,
        manager_flags=manager_flags,
        owner=owner,
        flags=flags,
        average_ca_strength=average_ca_strength,
        average_ca_missions=average_ca_missions,
        sample_cycles=sample_cycles,
        airbases=airbases,
        cycle=cycle,
        mission_requests=mission_requests,
        mission_requests_raw=mission_requests_raw,
    )


def _read_atm_airbase(reader: BinaryReader) -> AtmAirbase:
    return AtmAirbase(
        airbase_id=reader.vu_id(),
        schedule_raw=reader.read_bytes(32),
    )


def _read_mission_request(reader: BinaryReader) -> MissionRequest:
    start = reader.tell()
    request = MissionRequest(
        start_offset=start,
        requester_id=reader.vu_id(),
        target_id=reader.vu_id(),
        secondary_id=reader.vu_id(),
        pak_id=reader.vu_id(),
        who=reader.u8(),
        vs=reader.u8(),
        padding_raw=reader.read_bytes(2),
        tot=reader.u32(),
        tx=reader.i16(),
        ty=reader.i16(),
        flags=reader.u32(),
        caps=reader.i16(),
        target_num=reader.i16(),
        speed=reader.i16(),
        match_strength=reader.i16(),
        priority=reader.i16(),
        tot_type=reader.u8(),
        action_type=reader.u8(),
        mission=reader.u8(),
        aircraft=reader.u8(),
        context=reader.u8(),
        roe_check=reader.u8(),
        delayed=reader.u8(),
        start_block=reader.u8(),
        final_block=reader.u8(),
        slots=tuple(reader.u8() for _ in range(4)),
        min_to=reader.u8(),
        max_to=reader.u8(),
        morepadding_raw=reader.read_bytes(3),
        raw=reader.data[start:reader.tell()],
    )
    if reader.tell() - start != MISSION_REQUEST_SIZE_CURRENT:
        raise TeaRecordError("internal .tea mission request size mismatch")
    return request


def _read_tasking_manager(reader: BinaryReader) -> TaskingManager:
    start = reader.tell()
    return TaskingManager(
        start_offset=start,
        manager_id=reader.vu_id(),
        entity_type=reader.u16(),
        manager_flags=reader.i16(),
        owner=reader.u8(),
        flags=reader.i16(),
    )


def _team_body_size(version: int | None) -> int:
    if _supports(version, 54):
        return TEAM_BODY_SIZE_CURRENT

    size = 8 + 2 + 1 + 1 + 2
    size += TEAM_COUNT if _supports(version, 3) else 7
    size += (TEAM_COUNT if _supports(version, 3) else 7) * 2
    size += 2 + 2 + 2 + 2
    size += 4
    size += 2 + 2 + 2
    if _supports(version, 54):
        size += 2 + 4 + 4
    if not _supports(version, 40):
        size += 4
    size += 16 + 16
    size += 2
    size += 160 + 80
    size += 36 + 20
    size += 41 if _supports(version, 30) else 40
    if not _supports(version, 34):
        size += 4 + 1
    size += 4
    if _supports(version, 5):
        size += 1
    if _supports(version, 33):
        size += 1
    if _supports(version, 5):
        size += 1 + 20
    if _supports(version, 33):
        size += 200
    if _supports(version, 51):
        size += 19
    elif _supports(version, 42):
        size += 27
    elif _supports(version, 34):
        size += 23
    if _supports(version, 34):
        size += 28 + 28
    return size


def _team_reinforcement_prefix_size(version: int | None) -> int:
    """Return bytes from the stable team header to its signed counter."""

    size = 8  # firstColonel, firstCommander, firstWingman, lastWingman
    size += 4  # four experience values; legacy versions use two shorts
    size += 2 + 2 + 2  # initiative, supplyAvail, fuelAvail
    if _supports(version, 54):
        size += 2 + 4 + 4  # replacementsAvail, playerRating, lastPlayerMission
    if not _supports(version, 40):
        size += 2 + 2  # two obsolete ushort fields
    size += 16 + 16  # currentStats, startStats
    return size


def _supports(version: int | None, minimum: int) -> bool:
    return version is None or version >= minimum
