"""Deterministic `.obd` objective-delta record splitting."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import overload

from .binary import (
    BinaryParseError,
    BinaryReader,
    Codec,
    U32,
    U8,
    VUID,
    VuId,
    as_tuple_value,
)
from .cam_container import DecodedEntry
from .obj_parser import ObjectiveRecord
from .objective_status import validate_feature_status
from .record_fields import Field, FieldMap


class ObdRecordError(RuntimeError):
    """Raised when a `.obd` objective-delta record cannot be split deterministically."""


@dataclass(frozen=True)
class U8TupleCodec(Codec):
    def encode(self, value: object) -> bytes:
        return bytes(int(item) for item in as_tuple_value(value))


U8_TUPLE = U8TupleCodec()
MAX_OBD_RECORD_COUNT = 0xFFFF
MULTI_STATUS_MIN_VERSION = 64
EDITABLE_OBJECTIVE_DELTA_FIELDS = {
    "last_repair",
    "owner",
    "supply",
    "fuel",
    "losses",
}


@dataclass(frozen=True)
class ObjectiveDeltaRecord:
    index: int
    start_offset: int
    end_offset: int
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
            raise ObdRecordError("feature_statuses value is malformed")
        return tuple(int(item) for item in value)

    def get(self, name: str) -> object:
        return self.fields[name].value

    def set(self, name: str, value: object) -> None:
        self.fields[name].value = value

    def to_bytes(self) -> bytes:
        return b"".join(field.codec.encode(field.value) for field in self.fields.values())


class ObjectiveDeltaRecordCollection(Sequence[ObjectiveDeltaRecord]):
    """Mutable entry-backed collection that can add complete `.obd` snapshots."""

    def __init__(
        self,
        entry: DecodedEntry,
        records: Sequence[ObjectiveDeltaRecord],
        *,
        version: int | None,
    ) -> None:
        if not entry.name.lower().endswith(".obd"):
            raise ValueError(f"expected an .obd entry, got {entry.name!r}")
        record_count = entry.metadata.get("record_count")
        if not isinstance(record_count, int):
            raise ObdRecordError(f"{entry.name}: missing .obd record_count metadata")
        if record_count != len(records):
            raise ObdRecordError(
                f"{entry.name}: metadata declares {record_count} records, "
                f"got {len(records)} parsed records"
            )
        duplicates = _duplicate_objective_ids(records)
        if duplicates:
            raise ObdRecordError(f"duplicate objective delta id {duplicates[0]}")
        self.entry = entry
        self.version = version
        self._records = list(records)

    @overload
    def __getitem__(self, index: int) -> ObjectiveDeltaRecord: ...

    @overload
    def __getitem__(self, index: slice) -> list[ObjectiveDeltaRecord]: ...

    def __getitem__(
        self,
        index: int | slice,
    ) -> ObjectiveDeltaRecord | list[ObjectiveDeltaRecord]:
        return self._records[index]

    def __iter__(self) -> Iterator[ObjectiveDeltaRecord]:
        return iter(self._records)

    def __len__(self) -> int:
        return len(self._records)

    @property
    def records(self) -> tuple[ObjectiveDeltaRecord, ...]:
        return tuple(self._records)

    def get(self, objective_id: VuId) -> ObjectiveDeltaRecord | None:
        positions = self._positions(objective_id)
        return None if not positions else self._records[positions[0]]

    def require(self, objective_id: VuId) -> ObjectiveDeltaRecord:
        record = self.get(objective_id)
        if record is None:
            raise KeyError(f"objective delta id not present: {objective_id}")
        return record

    def ensure_from_base(self, base: ObjectiveRecord) -> ObjectiveDeltaRecord:
        """Return an existing delta or append a complete snapshot from `.obj`."""

        if not isinstance(base, ObjectiveRecord):
            raise TypeError("base must be an ObjectiveRecord")
        existing = self.get(base.objective_id)
        if existing is not None:
            return existing
        start_offset = len(self.entry.decoded)
        created = create_objective_delta_record(
            base,
            version=self.version,
            index=len(self._records),
            start_offset=start_offset,
        )
        self._commit((*self._records, created))
        return created

    def set_feature_status(
        self,
        base: ObjectiveRecord,
        feature_index: int,
        status: int,
    ) -> ObjectiveDeltaRecord:
        """Update an existing delta or atomically create and update one from base."""

        if not isinstance(base, ObjectiveRecord):
            raise TypeError("base must be an ObjectiveRecord")
        positions = self._positions(base.objective_id)
        if positions:
            position = positions[0]
            source = self._records[position]
            candidate = list(self._records)
            candidate[position] = _record_with_feature_status(
                source,
                feature_index,
                status,
            )
        else:
            position = len(self._records)
            source = create_objective_delta_record(
                base,
                version=self.version,
                index=position,
                start_offset=len(self.entry.decoded),
            )
            candidate = [
                *self._records,
                _record_with_feature_status(source, feature_index, status),
            ]
        self._commit(candidate)
        return self._records[position]

    def set_record_field(
        self,
        record: ObjectiveDeltaRecord,
        field_name: str,
        value: object,
    ) -> ObjectiveDeltaRecord:
        """Atomically set one fixed-width field on one existing delta record."""

        if not isinstance(record, ObjectiveDeltaRecord):
            raise TypeError("record must be an ObjectiveDeltaRecord")
        if field_name not in EDITABLE_OBJECTIVE_DELTA_FIELDS:
            names = ", ".join(sorted(EDITABLE_OBJECTIVE_DELTA_FIELDS))
            raise ObdRecordError(
                f"field {field_name!r} is not an editable delta scalar; expected {names}"
            )
        position = self._identity_position(record)
        candidate = list(self._records)
        candidate[position] = _record_with_field(record, field_name, value)
        self._commit(candidate)
        return self._records[position]

    def set_record_feature_status(
        self,
        record: ObjectiveDeltaRecord,
        feature_index: int,
        status: int,
    ) -> ObjectiveDeltaRecord:
        """Atomically edit one status on one existing delta record."""

        if not isinstance(record, ObjectiveDeltaRecord):
            raise TypeError("record must be an ObjectiveDeltaRecord")
        position = self._identity_position(record)
        candidate = list(self._records)
        candidate[position] = _record_with_feature_status(
            record,
            feature_index,
            status,
        )
        self._commit(candidate)
        return self._records[position]

    def _positions(self, objective_id: object) -> list[int]:
        validated_id = _validate_vuid(objective_id)
        positions = [
            index
            for index, record in enumerate(self._records)
            if record.objective_id == validated_id
        ]
        if len(positions) > 1:
            raise ObdRecordError(
                f"objective delta id {validated_id} occurs {len(positions)} times"
            )
        return positions

    def _identity_position(self, record: ObjectiveDeltaRecord) -> int:
        positions = [
            index for index, current in enumerate(self._records) if current is record
        ]
        if len(positions) != 1:
            raise ObdRecordError(
                f"objective delta record matches {len(positions)} current records"
            )
        return positions[0]

    def _commit(self, records: Sequence[ObjectiveDeltaRecord]) -> None:
        candidate = tuple(records)
        if len(candidate) > MAX_OBD_RECORD_COUNT:
            raise ObdRecordError(
                f".obd record count must fit in uint16, got {len(candidate)}"
            )
        try:
            payload = encode_obd_records(candidate)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ObdRecordError(f"candidate .obd records cannot be encoded: {exc}") from exc
        self._records = list(candidate)
        self.entry.metadata["record_count"] = len(candidate)
        self.entry.set_decoded(payload)


def parse_obd_records(
    entry: DecodedEntry,
    *,
    container_version: int | None,
) -> tuple[ObjectiveDeltaRecord, ...]:
    """Parse one decoded `.obd` entry into objective-delta records."""

    if not entry.name.lower().endswith(".obd"):
        raise ValueError(f"expected a .obd entry, got {entry.name!r}")

    record_count = entry.metadata.get("record_count")
    if not isinstance(record_count, int):
        raise ObdRecordError(f"{entry.name}: missing .obd record_count metadata")

    return split_obd_records(
        entry.decoded,
        record_count=record_count,
        version=container_version,
    )


def parse_obd_record_collection(
    entry: DecodedEntry,
    *,
    container_version: int | None,
) -> ObjectiveDeltaRecordCollection:
    """Parse an entry-backed `.obd` collection with safe record creation."""

    records = parse_obd_records(entry, container_version=container_version)
    return ObjectiveDeltaRecordCollection(
        entry,
        records,
        version=container_version,
    )


def encode_obd_records(records: Sequence[ObjectiveDeltaRecord]) -> bytes:
    """Encode parsed records back into a decoded `.obd` byte payload."""

    return b"".join(record.to_bytes() for record in records)


def create_objective_delta_record(
    base: ObjectiveRecord,
    *,
    version: int | None,
    index: int = 0,
    start_offset: int = 0,
) -> ObjectiveDeltaRecord:
    """Create one complete modern `.obd` snapshot from decoded `.obj` fields."""

    if not isinstance(base, ObjectiveRecord):
        raise TypeError("base must be an ObjectiveRecord")
    if version is not None and version < MULTI_STATUS_MIN_VERSION:
        raise ObdRecordError(
            "creating .obd records before version 64 is unsupported because the "
            "legacy single-status shape cannot preserve all base feature statuses"
        )
    if type(index) is not int or index < 0:
        raise ValueError("index must be a nonnegative integer")
    if type(start_offset) is not int or start_offset < 0:
        raise ValueError("start_offset must be a nonnegative integer")

    statuses = base.feature_statuses
    if len(statuses) > 0xFF:
        raise ObdRecordError(
            f"feature status count must fit in uint8, got {len(statuses)}"
        )
    fields: FieldMap = {}
    _set(fields, "objective_id", base.objective_id, VUID)
    _set(fields, "last_repair", base.get("last_repair"), U32)
    _set(fields, "owner", base.get("owner"), U8)
    _set(fields, "supply", base.get("supply"), U8)
    _set(fields, "fuel", base.get("fuel"), U8)
    _set(fields, "losses", base.get("losses"), U8)
    _set(fields, "num_statuses", len(statuses), U8)
    _set(fields, "feature_statuses", statuses, U8_TUPLE)

    payload = b"".join(field.codec.encode(field.value) for field in fields.values())
    return ObjectiveDeltaRecord(
        index=index,
        start_offset=start_offset,
        end_offset=start_offset + len(payload),
        objective_id=base.objective_id,
        fields=fields,
        raw=payload,
    )


def split_obd_records(
    data: bytes,
    *,
    record_count: int,
    version: int | None,
) -> tuple[ObjectiveDeltaRecord, ...]:
    """Split decoded `.obd` bytes into objective-delta records."""

    reader = BinaryReader(data)
    records: list[ObjectiveDeltaRecord] = []
    for index in range(record_count):
        start = reader.tell()
        try:
            fields: FieldMap = {}
            _read_objective_delta_record(fields, reader, version=version)
        except BinaryParseError as exc:
            raise ObdRecordError(
                f"truncated objective-delta record at offset {start}: {exc}"
            ) from exc

        objective_id_value = fields["objective_id"].value
        if not isinstance(objective_id_value, tuple) or len(objective_id_value) != 2:
            raise ObdRecordError(f"objective_id is malformed at offset {start}")
        objective_id = int(objective_id_value[0]), int(objective_id_value[1])
        end = reader.tell()
        records.append(
            ObjectiveDeltaRecord(
                index=index,
                start_offset=start,
                end_offset=end,
                objective_id=objective_id,
                fields=fields,
                raw=data[start:end],
            )
        )

    if reader.tell() != len(data):
        raise ObdRecordError(
            f"record walk ended at {reader.tell()}, decoded payload has {len(data)} bytes"
        )
    return tuple(records)


def _read_objective_delta_record(
    fields: FieldMap,
    reader: BinaryReader,
    *,
    version: int | None,
) -> None:
    _set(fields, "objective_id", reader.vu_id(), VUID)
    _set(fields, "last_repair", reader.u32(), U32)
    _set(fields, "owner", reader.u8(), U8)
    _set(fields, "supply", reader.u8(), U8)
    _set(fields, "fuel", reader.u8(), U8)
    _set(fields, "losses", reader.u8(), U8)
    _set(fields, "num_statuses", reader.u8(), U8)

    status_count = int(fields["num_statuses"].value) if _supports(version, 64) else 1
    _set(
        fields,
        "feature_statuses",
        tuple(reader.u8() for _ in range(status_count)),
        U8_TUPLE,
    )


def _set(fields: FieldMap, name: str, value: object, codec: Codec) -> None:
    fields[name] = Field(name=name, value=value, codec=codec)


def _supports(version: int | None, minimum: int) -> bool:
    return version is None or version >= minimum


def _record_with_feature_status(
    record: ObjectiveDeltaRecord,
    feature_index: object,
    status: object,
) -> ObjectiveDeltaRecord:
    statuses = record.feature_statuses
    if type(feature_index) is not int:
        raise ObdRecordError(
            f"feature index must be an integer, got {type(feature_index).__name__}"
        )
    if not 0 <= feature_index < len(statuses):
        raise ObdRecordError(
            f"feature index {feature_index} is out of range for {len(statuses)} features"
        )
    validate_feature_status(status, error_type=ObdRecordError)

    candidate_statuses = list(statuses)
    candidate_statuses[feature_index] = status
    fields = {
        name: Field(name=field.name, value=field.value, codec=field.codec)
        for name, field in record.fields.items()
    }
    fields["feature_statuses"].value = tuple(candidate_statuses)
    fields["feature_statuses"].codec.encode(fields["feature_statuses"].value)
    return ObjectiveDeltaRecord(
        index=record.index,
        start_offset=record.start_offset,
        end_offset=record.end_offset,
        objective_id=record.objective_id,
        fields=fields,
        raw=record.raw,
    )


def _record_with_field(
    record: ObjectiveDeltaRecord,
    field_name: str,
    value: object,
) -> ObjectiveDeltaRecord:
    fields = {
        name: Field(name=field.name, value=field.value, codec=field.codec)
        for name, field in record.fields.items()
    }
    field = fields[field_name]
    try:
        field.codec.encode(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ObdRecordError(f"{field_name} cannot be encoded: {exc}") from exc
    field.value = value
    return ObjectiveDeltaRecord(
        index=record.index,
        start_offset=record.start_offset,
        end_offset=record.end_offset,
        objective_id=record.objective_id,
        fields=fields,
        raw=record.raw,
    )


def _validate_vuid(value: object) -> VuId:
    if not isinstance(value, tuple) or len(value) != 2:
        raise ObdRecordError("objective_id must be a (num, creator) tuple")
    if any(type(part) is not int for part in value):
        raise ObdRecordError("objective_id values must be integers")
    try:
        VUID.encode(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ObdRecordError(f"objective_id cannot be encoded: {exc}") from exc
    return value


def _duplicate_objective_ids(
    records: Sequence[ObjectiveDeltaRecord],
) -> tuple[VuId, ...]:
    seen: set[VuId] = set()
    duplicates: list[VuId] = []
    for record in records:
        if record.objective_id in seen and record.objective_id not in duplicates:
            duplicates.append(record.objective_id)
        seen.add(record.objective_id)
    return tuple(duplicates)
