"""Deterministic `.obj` objective-record splitting."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .binary import (
    BinaryParseError,
    BinaryReader,
    BytesCodec,
    Codec,
    F32,
    I16,
    U16,
    U32,
    U8,
    VUID,
    VuId,
    as_tuple_value,
)
from .cam_container import DecodedEntry
from .record_fields import Field, FieldMap


OBJECTIVE_TAIL_RAW_SIZE = 28
OBJECTIVE_NAME_SIZE = 80
RADAR_RATIO_COUNT = 8
LINK_COST_COUNT = 8


class ObjRecordError(RuntimeError):
    """Raised when a `.obj` objective record cannot be split deterministically."""


@dataclass(frozen=True)
class ObjectiveLink:
    costs: bytes
    objective_id: VuId


@dataclass(frozen=True)
class U8TupleCodec(Codec):
    def encode(self, value: object) -> bytes:
        return bytes(int(item) for item in as_tuple_value(value))


@dataclass(frozen=True)
class ObjectiveLinkListCodec(Codec):
    def encode(self, value: object) -> bytes:
        payload = bytearray()
        for item in as_tuple_value(value):
            if not isinstance(item, ObjectiveLink):
                raise TypeError("objective link values must be ObjectiveLink instances")
            if len(item.costs) != LINK_COST_COUNT:
                raise ValueError(
                    f"objective link costs expected {LINK_COST_COUNT} bytes, "
                    f"got {len(item.costs)}"
                )
            payload.extend(item.costs)
            payload.extend(VUID.encode(item.objective_id))
        return bytes(payload)


@dataclass(frozen=True)
class F32TupleCodec(Codec):
    size: int

    def encode(self, value: object) -> bytes:
        items = as_tuple_value(value)
        if len(items) != self.size:
            raise ValueError(f"expected {self.size} float values, got {len(items)}")
        return b"".join(F32.encode(float(item)) for item in items)


U8_TUPLE = U8TupleCodec()
OBJECTIVE_LINKS = ObjectiveLinkListCodec()
RADAR_RATIOS = F32TupleCodec(RADAR_RATIO_COUNT)


@dataclass(frozen=True)
class ObjectiveRecord:
    index: int
    start_offset: int
    end_offset: int
    objective_type: int
    objective_id: VuId
    fields: FieldMap
    raw: bytes

    @property
    def size(self) -> int:
        return self.end_offset - self.start_offset

    @property
    def feature_statuses(self) -> tuple[int, ...]:
        value = self.get("feature_statuses")
        if not isinstance(value, tuple):
            raise ObjRecordError("feature_statuses value is malformed")
        return tuple(int(item) for item in value)

    @property
    def objective_name_raw(self) -> bytes:
        value = self.get("objective_name_raw")
        if not isinstance(value, bytes):
            raise ObjRecordError("objective_name_raw value is malformed")
        return value

    def get(self, name: str) -> object:
        return self.fields[name].value

    def set(self, name: str, value: object) -> None:
        self.fields[name].value = value

    def to_bytes(self) -> bytes:
        return b"".join(field.codec.encode(field.value) for field in self.fields.values())


def parse_obj_records(
    entry: DecodedEntry,
    *,
    container_version: int | None,
) -> tuple[ObjectiveRecord, ...]:
    """Parse one decoded `.obj` entry into objective records."""

    if not entry.name.lower().endswith(".obj"):
        raise ValueError(f"expected a .obj entry, got {entry.name!r}")

    record_count = entry.metadata.get("num_objectives")
    if not isinstance(record_count, int):
        raise ObjRecordError(f"{entry.name}: missing .obj num_objectives metadata")

    return split_obj_records(
        entry.decoded,
        record_count=record_count,
        version=container_version,
    )


def encode_obj_records(records: Sequence[ObjectiveRecord]) -> bytes:
    """Encode parsed records back into a decoded `.obj` byte payload."""

    return b"".join(record.to_bytes() for record in records)


def split_obj_records(
    data: bytes,
    *,
    record_count: int,
    version: int | None,
) -> tuple[ObjectiveRecord, ...]:
    """Split decoded `.obj` bytes into top-level objective records."""

    reader = BinaryReader(data)
    records: list[ObjectiveRecord] = []
    for index in range(record_count):
        start = reader.tell()
        try:
            fields: FieldMap = {}
            _read_objective_record(fields, reader, version=version)
        except BinaryParseError as exc:
            raise ObjRecordError(
                f"truncated objective record at offset {start}: {exc}"
            ) from exc

        objective_type = int(fields["objective_type"].value)
        objective_id_value = fields["objective_id"].value
        if not isinstance(objective_id_value, tuple) or len(objective_id_value) != 2:
            raise ObjRecordError(f"objective_id is malformed at offset {start}")
        objective_id = int(objective_id_value[0]), int(objective_id_value[1])
        end = reader.tell()
        records.append(
            ObjectiveRecord(
                index=index,
                start_offset=start,
                end_offset=end,
                objective_type=objective_type,
                objective_id=objective_id,
                fields=fields,
                raw=data[start:end],
            )
        )

    if reader.tell() != len(data):
        raise ObjRecordError(
            f"record walk ended at {reader.tell()}, decoded payload has {len(data)} bytes"
        )
    return tuple(records)


def _read_objective_record(
    fields: FieldMap,
    reader: BinaryReader,
    *,
    version: int | None,
) -> None:
    objective_type = reader.u16()
    _set(fields, "objective_type", objective_type, U16)
    _set(fields, "objective_id", reader.vu_id(), VUID)
    _set(fields, "entity_type_copy", reader.u16(), U16)
    if fields["entity_type_copy"].value != objective_type:
        raise ObjRecordError(
            "objective type copy mismatch: "
            f"{fields['entity_type_copy'].value} != {objective_type}"
        )

    _set(fields, "x", reader.i16(), I16)
    _set(fields, "y", reader.i16(), I16)
    if _supports(version, 70):
        _set(fields, "z", reader.f32(), F32)
    _set(fields, "spot_time", reader.u32(), U32)
    _set(fields, "spotted", reader.i16(), I16)
    _set(fields, "base_flags", reader.i16(), I16)
    _set(fields, "owner", reader.u8(), U8)
    _set(fields, "camp_id", reader.i16(), I16)
    _set(fields, "last_repair", reader.u32(), U32)
    if version is not None and version <= 1:
        _set(fields, "obj_flags", reader.u16(), U16)
    else:
        _set(fields, "obj_flags", reader.u32(), U32)
    _set(fields, "supply", reader.u8(), U8)
    _set(fields, "fuel", reader.u8(), U8)
    _set(fields, "losses", reader.u8(), U8)
    _set(fields, "num_statuses", reader.u8(), U8)
    _set(
        fields,
        "feature_statuses",
        tuple(reader.u8() for _ in range(int(fields["num_statuses"].value))),
        U8_TUPLE,
    )
    _set(fields, "priority", reader.u8(), U8)
    _set(fields, "name_id", reader.i16(), I16)
    _set(fields, "parent_id", reader.vu_id(), VUID)
    _set(fields, "first_owner", reader.u8(), U8)
    _set(fields, "num_links", reader.u8(), U8)
    _set(
        fields,
        "links",
        tuple(_read_objective_link(reader) for _ in range(int(fields["num_links"].value))),
        OBJECTIVE_LINKS,
    )
    if _supports(version, 20):
        _set(fields, "has_radar_data", reader.u8(), U8)
        if fields["has_radar_data"].value:
            _set(
                fields,
                "detect_ratios",
                tuple(reader.f32() for _ in range(RADAR_RATIO_COUNT)),
                RADAR_RATIOS,
            )

    _opaque(fields, reader, "objective_tail_raw", OBJECTIVE_TAIL_RAW_SIZE)
    _opaque(fields, reader, "objective_name_raw", OBJECTIVE_NAME_SIZE)


def _read_objective_link(reader: BinaryReader) -> ObjectiveLink:
    return ObjectiveLink(
        costs=reader.read_bytes(LINK_COST_COUNT),
        objective_id=reader.vu_id(),
    )


def _set(fields: FieldMap, name: str, value: object, codec: Codec) -> None:
    fields[name] = Field(name=name, value=value, codec=codec)


def _opaque(fields: FieldMap, reader: BinaryReader, name: str, size: int) -> None:
    _set(fields, name, reader.read_bytes(size), BytesCodec(size))


def _supports(version: int | None, minimum: int) -> bool:
    return version is None or version >= minimum
