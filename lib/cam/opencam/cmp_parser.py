"""Deterministic `.cmp` campaign-record parsing."""

from __future__ import annotations

from dataclasses import dataclass

from .binary import (
    BinaryParseError,
    BinaryReader,
    BytesCodec,
    Codec,
    F32,
    I16,
    I32,
    U16,
    U32,
    U8,
    VUID,
    VuId,
    as_tuple_value,
)
from .cam_container import DecodedEntry
from .record_fields import Field, FieldMap


MAX_EVENTS = 10000
MAX_CAMP_MAP_SIZE = 1_000_000
MAX_SQUADRONS = 10000
TEAM_COUNT = 8
TEAM_NAME_SIZE = 20
TEAM_MOTTO_SIZE = 200
FIXED_STRING_SIZE = 40
LEGACY_AIRBASE_NAME_SIZE = 80


class CmpRecordError(RuntimeError):
    """Raised when a `.cmp` campaign record cannot be split deterministically."""


@dataclass(frozen=True)
class TeamBasicInfo:
    team_flag: int
    team_color: int
    team_name_raw: bytes
    team_motto_raw: bytes


@dataclass(frozen=True)
class EventNode:
    x: int
    y: int
    time: int
    flags: int
    team: int
    padding_raw: bytes
    event_text_pointer: int
    ui_event_node_pointer: int
    event_text_size: int
    event_text_raw: bytes


@dataclass(frozen=True)
class SquadInfo:
    x: float
    y: float
    squadron_id: VuId
    description_index: int
    name_id: int
    airbase_icon: int
    squadron_path: int
    specialty: int
    current_strength: int
    country: int
    airbase_name_raw: bytes
    padding_raw: bytes = b""


@dataclass(frozen=True)
class I32TupleCodec(Codec):
    size: int

    def encode(self, value: object) -> bytes:
        items = as_tuple_value(value)
        if len(items) != self.size:
            raise ValueError(f"expected {self.size} i32 values, got {len(items)}")
        return b"".join(I32.encode(int(item)) for item in items)


@dataclass(frozen=True)
class TeamBasicInfoListCodec(Codec):
    size: int

    def encode(self, value: object) -> bytes:
        items = as_tuple_value(value)
        if len(items) != self.size:
            raise ValueError(f"expected {self.size} team records, got {len(items)}")
        return b"".join(_encode_team_basic_info(item) for item in items)


@dataclass(frozen=True)
class EventNodeListCodec(Codec):
    def encode(self, value: object) -> bytes:
        return b"".join(_encode_event_node(item) for item in as_tuple_value(value))


@dataclass(frozen=True)
class SquadInfoListCodec(Codec):
    include_airbase_icon_path: bool
    airbase_name_size: int

    def encode(self, value: object) -> bytes:
        return b"".join(
            _encode_squad_info(
                item,
                include_airbase_icon_path=self.include_airbase_icon_path,
                airbase_name_size=self.airbase_name_size,
            )
            for item in as_tuple_value(value)
        )


I32_TEAM_SLOTS = I32TupleCodec(TEAM_COUNT)
TEAM_BASIC_INFOS = TeamBasicInfoListCodec(TEAM_COUNT)
EVENT_NODES = EventNodeListCodec()


@dataclass(frozen=True)
class CmpRecord:
    start_offset: int
    end_offset: int
    fields: FieldMap
    raw: bytes

    @property
    def size(self) -> int:
        return self.end_offset - self.start_offset

    @property
    def current_time(self) -> int:
        return int(self.get("current_time"))

    @property
    def player_squadron_id(self) -> VuId:
        value = self.get("player_squadron_id")
        if not isinstance(value, tuple) or len(value) != 2:
            raise CmpRecordError("player_squadron_id value is malformed")
        return int(value[0]), int(value[1])

    def get(self, name: str) -> object:
        return self.fields[name].value

    def set(self, name: str, value: object) -> None:
        self.fields[name].value = value

    def to_bytes(self) -> bytes:
        return b"".join(field.codec.encode(field.value) for field in self.fields.values())


def parse_cmp_record(
    entry: DecodedEntry,
    *,
    container_version: int | None,
) -> CmpRecord:
    """Parse one decoded `.cmp` entry into a campaign record."""

    if not entry.name.lower().endswith(".cmp"):
        raise ValueError(f"expected a .cmp entry, got {entry.name!r}")

    return split_cmp_record(entry.decoded, version=container_version)


def encode_cmp_record(record: CmpRecord) -> bytes:
    """Encode a parsed record back into a decoded `.cmp` byte payload."""

    return record.to_bytes()


def split_cmp_record(data: bytes, *, version: int | None) -> CmpRecord:
    """Split decoded `.cmp` bytes into one campaign record.

    The version gates follow the documented `.cmp` field availability. A missing
    version is treated as latest-shape data because some containers omit `.ver`.
    """

    reader = BinaryReader(data)
    fields: FieldMap = {}

    try:
        _read_campaign_record(fields, reader, version=version)
    except BinaryParseError as exc:
        raise CmpRecordError(f"truncated .cmp record at offset {reader.tell()}: {exc}") from exc

    if reader.tell() != len(data):
        raise CmpRecordError(
            f"record walk ended at {reader.tell()}, decoded payload has {len(data)} bytes"
        )

    return CmpRecord(
        start_offset=0,
        end_offset=reader.tell(),
        fields=fields,
        raw=data,
    )


def _read_campaign_record(fields: FieldMap, reader: BinaryReader, *, version: int | None) -> None:
    _set(fields, "current_time", reader.u32(), U32)

    if _supports(version, 48):
        _set(fields, "te_start_time", reader.u32(), U32)
        _set(fields, "te_time_limit", reader.u32(), U32)
    if _supports(version, 49):
        _set(fields, "te_victory_points", reader.i32(), I32)
    if _supports(version, 52):
        _set(fields, "te_type", reader.i32(), I32)
        _set(fields, "te_number_teams", reader.i32(), I32)
        _set(fields, "te_number_aircraft", _read_i32_tuple(reader, TEAM_COUNT), I32_TEAM_SLOTS)
        _set(fields, "te_number_f16s", _read_i32_tuple(reader, TEAM_COUNT), I32_TEAM_SLOTS)
        _set(fields, "te_team", reader.i32(), I32)
        _set(fields, "te_team_pts", _read_i32_tuple(reader, TEAM_COUNT), I32_TEAM_SLOTS)
        _set(fields, "te_flags", reader.i32(), I32)
        _set(
            fields,
            "team_info",
            tuple(_read_team_basic_info(reader) for _ in range(TEAM_COUNT)),
            TEAM_BASIC_INFOS,
        )

    if _supports(version, 19):
        _set(fields, "last_major_event", reader.u32(), U32)

    _set(fields, "last_resupply", reader.u32(), U32)
    _set(fields, "last_repair", reader.u32(), U32)
    _set(fields, "last_reinforcement", reader.u32(), U32)
    _set(fields, "time_stamp", reader.i16(), I16)
    _set(fields, "group", reader.i16(), I16)
    _set(fields, "ground_ratio", reader.i16(), I16)
    _set(fields, "air_ratio", reader.i16(), I16)
    _set(fields, "air_defense_ratio", reader.i16(), I16)
    _set(fields, "naval_ratio", reader.i16(), I16)
    _set(fields, "brief", reader.i16(), I16)
    _set(fields, "theater_size_x", reader.i16(), I16)
    _set(fields, "theater_size_y", reader.i16(), I16)
    _set(fields, "current_day", reader.u8(), U8)
    _set(fields, "active_team", reader.u8(), U8)
    _set(fields, "day_zero", reader.u8(), U8)
    _set(fields, "endgame_result", reader.u8(), U8)
    _set(fields, "situation", reader.u8(), U8)
    _set(fields, "enemy_air_exp", reader.u8(), U8)
    _set(fields, "enemy_ad_exp", reader.u8(), U8)
    _set(fields, "bullseye_name", reader.u8(), U8)
    _set(fields, "bullseye_x", reader.i16(), I16)
    _set(fields, "bullseye_y", reader.i16(), I16)
    _opaque(fields, reader, "theater_name_raw", FIXED_STRING_SIZE)
    _opaque(fields, reader, "scenario_raw", FIXED_STRING_SIZE)
    _opaque(fields, reader, "save_file_raw", FIXED_STRING_SIZE)
    _opaque(fields, reader, "ui_name_raw", FIXED_STRING_SIZE)
    _set(fields, "player_squadron_id", reader.vu_id(), VUID)

    recent_count = _read_nonnegative_i16(reader, "num_recent_event_entries", MAX_EVENTS)
    _set(fields, "num_recent_event_entries", recent_count, I16)
    _set(
        fields,
        "recent_event_entries",
        tuple(_read_event_node(reader) for _ in range(recent_count)),
        EVENT_NODES,
    )

    priority_count = _read_nonnegative_i16(reader, "num_priority_event_entries", MAX_EVENTS)
    _set(fields, "num_priority_event_entries", priority_count, I16)
    _set(
        fields,
        "priority_event_entries",
        tuple(_read_event_node(reader) for _ in range(priority_count)),
        EVENT_NODES,
    )

    camp_map_size = _read_nonnegative_i16(reader, "camp_map_size", MAX_CAMP_MAP_SIZE)
    _set(fields, "camp_map_size", camp_map_size, I16)
    _opaque(fields, reader, "camp_map", camp_map_size)
    _set(fields, "last_index_num", reader.i16(), I16)

    squadron_count = _read_nonnegative_i16(reader, "num_available_squadrons", MAX_SQUADRONS)
    _set(fields, "num_available_squadrons", squadron_count, I16)
    include_airbase_icon_path = _supports(version, 42)
    airbase_name_size = FIXED_STRING_SIZE if include_airbase_icon_path else LEGACY_AIRBASE_NAME_SIZE
    _set(
        fields,
        "squad_info",
        tuple(
            _read_squad_info(
                reader,
                include_airbase_icon_path=include_airbase_icon_path,
                airbase_name_size=airbase_name_size,
            )
            for _ in range(squadron_count)
        ),
        SquadInfoListCodec(include_airbase_icon_path, airbase_name_size),
    )

    if _supports(version, 31):
        _set(fields, "tempo", reader.u8(), U8)
    if _supports(version, 43):
        _set(fields, "creator_ip", reader.i32(), I32)
        _set(fields, "creation_time", reader.i32(), I32)
        _set(fields, "creation_rand", reader.i32(), I32)
    if reader.remaining():
        _opaque(fields, reader, "tail_raw", reader.remaining())


def _read_team_basic_info(reader: BinaryReader) -> TeamBasicInfo:
    return TeamBasicInfo(
        team_flag=reader.u8(),
        team_color=reader.u8(),
        team_name_raw=reader.read_bytes(TEAM_NAME_SIZE),
        team_motto_raw=reader.read_bytes(TEAM_MOTTO_SIZE),
    )


def _read_event_node(reader: BinaryReader) -> EventNode:
    x = reader.i16()
    y = reader.i16()
    time = reader.u32()
    flags = reader.u8()
    team = reader.u8()
    padding_raw = reader.read_bytes(2)
    event_text_pointer = reader.i32()
    ui_event_node_pointer = reader.i32()
    event_text_size = reader.u16()
    return EventNode(
        x=x,
        y=y,
        time=time,
        flags=flags,
        team=team,
        padding_raw=padding_raw,
        event_text_pointer=event_text_pointer,
        ui_event_node_pointer=ui_event_node_pointer,
        event_text_size=event_text_size,
        event_text_raw=reader.read_bytes(event_text_size),
    )


def _read_squad_info(
    reader: BinaryReader,
    *,
    include_airbase_icon_path: bool,
    airbase_name_size: int,
) -> SquadInfo:
    x = reader.f32()
    y = reader.f32()
    squadron_id = reader.vu_id()
    description_index = reader.i16()
    name_id = reader.i16()
    airbase_icon = 0
    squadron_path = 0
    if include_airbase_icon_path:
        airbase_icon = reader.i16()
        squadron_path = reader.i16()
    return SquadInfo(
        x=x,
        y=y,
        squadron_id=squadron_id,
        description_index=description_index,
        name_id=name_id,
        airbase_icon=airbase_icon,
        squadron_path=squadron_path,
        specialty=reader.u8(),
        current_strength=reader.u8(),
        country=reader.u8(),
        airbase_name_raw=reader.read_bytes(airbase_name_size),
        padding_raw=reader.read_bytes(1),
    )


def _set(fields: FieldMap, name: str, value: object, codec: Codec) -> None:
    fields[name] = Field(name=name, value=value, codec=codec)


def _opaque(fields: FieldMap, reader: BinaryReader, name: str, size: int) -> None:
    _set(fields, name, reader.read_bytes(size), BytesCodec(size))


def _read_i32_tuple(reader: BinaryReader, count: int) -> tuple[int, ...]:
    return tuple(reader.i32() for _ in range(count))


def _read_nonnegative_i16(reader: BinaryReader, name: str, maximum: int) -> int:
    value = reader.i16()
    if value < 0:
        raise CmpRecordError(f"{name} is negative: {value}")
    if value > maximum:
        raise CmpRecordError(f"{name} is suspiciously large: {value}")
    return value


def _encode_team_basic_info(value: object) -> bytes:
    if not isinstance(value, TeamBasicInfo):
        raise TypeError("team_info values must be TeamBasicInfo instances")
    _require_bytes_size("team_name_raw", value.team_name_raw, TEAM_NAME_SIZE)
    _require_bytes_size("team_motto_raw", value.team_motto_raw, TEAM_MOTTO_SIZE)
    return b"".join(
        (
            U8.encode(value.team_flag),
            U8.encode(value.team_color),
            value.team_name_raw,
            value.team_motto_raw,
        )
    )


def _encode_event_node(value: object) -> bytes:
    if not isinstance(value, EventNode):
        raise TypeError("event entry values must be EventNode instances")
    _require_bytes_size("padding_raw", value.padding_raw, 2)
    if len(value.event_text_raw) != value.event_text_size:
        raise ValueError(
            f"event_text_raw expected {value.event_text_size} bytes, "
            f"got {len(value.event_text_raw)}"
        )
    return b"".join(
        (
            I16.encode(value.x),
            I16.encode(value.y),
            U32.encode(value.time),
            U8.encode(value.flags),
            U8.encode(value.team),
            value.padding_raw,
            I32.encode(value.event_text_pointer),
            I32.encode(value.ui_event_node_pointer),
            U16.encode(value.event_text_size),
            value.event_text_raw,
        )
    )


def _encode_squad_info(
    value: object,
    *,
    include_airbase_icon_path: bool,
    airbase_name_size: int,
) -> bytes:
    if not isinstance(value, SquadInfo):
        raise TypeError("squad_info values must be SquadInfo instances")
    _require_bytes_size("airbase_name_raw", value.airbase_name_raw, airbase_name_size)
    _require_bytes_size("padding_raw", value.padding_raw, 1)
    payload = bytearray()
    payload.extend(F32.encode(value.x))
    payload.extend(F32.encode(value.y))
    payload.extend(VUID.encode(value.squadron_id))
    payload.extend(I16.encode(value.description_index))
    payload.extend(I16.encode(value.name_id))
    if include_airbase_icon_path:
        payload.extend(I16.encode(value.airbase_icon))
        payload.extend(I16.encode(value.squadron_path))
    payload.extend(U8.encode(value.specialty))
    payload.extend(U8.encode(value.current_strength))
    payload.extend(U8.encode(value.country))
    payload.extend(value.airbase_name_raw)
    payload.extend(value.padding_raw)
    return bytes(payload)


def _require_bytes_size(name: str, value: bytes, size: int) -> None:
    if not isinstance(value, bytes):
        raise TypeError(f"{name} must be bytes")
    if len(value) != size:
        raise ValueError(f"{name} expected {size} bytes, got {len(value)}")


def _supports(version: int | None, minimum: int) -> bool:
    return version is None or version >= minimum
