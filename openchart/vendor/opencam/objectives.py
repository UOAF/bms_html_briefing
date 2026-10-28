"""Read the objective facts OpenChart uses from a decoded OBJ entry.

This is the read-only subset of OpenCAM's deterministic OBJ parser and
objective wrapper from commit e4dbcb54a9f4751f3045e1fd96f8627c5bf78115.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import TYPE_CHECKING

from .campaign import CampaignEntry

if TYPE_CHECKING:
    from .support import CampaignObjectiveData, ClassTableEntry, SupportData


OBJECTIVE_TAIL_RAW_SIZE = 28
OBJECTIVE_NAME_SIZE = 80
RADAR_RATIO_COUNT = 8
LINK_SIZE = 16

DOMAIN_LAND = 3
CLASS_OBJECTIVE = 4
TYPE_AIRBASE = 1
TYPE_AIRSTRIP = 2
TYPE_ARMYBASE = 3
SPECIFIC_CARRIER = 7


class ObjRecordError(RuntimeError):
    """Raised when an OBJ objective record cannot be split exactly."""


class BinaryParseError(RuntimeError):
    """Raised when an objective field would read past EOF."""


@dataclass(frozen=True)
class Objective:
    objective_type: int
    camp_id: int
    name: str
    feature_statuses: tuple[int, ...]
    support: SupportData
    first_owner: int = 0

    @property
    def features(self) -> tuple[int, ...]:
        return self.feature_statuses

    @property
    def support_ct_number(self) -> int:
        return self.objective_type - 100

    @property
    def campaign_objective_data(self) -> CampaignObjectiveData | None:
        return self.support.campaign_objectives_by_id.get(self.camp_id)

    @property
    def class_table_entry(self) -> ClassTableEntry | None:
        return self.support.ct_by_number.get(self.support_ct_number)

    @property
    def airfield_kind(self) -> str | None:
        entry = self.class_table_entry
        if entry is None:
            return None
        if entry.domain != DOMAIN_LAND or entry.class_ != CLASS_OBJECTIVE:
            return None
        if entry.type_ == TYPE_AIRBASE and entry.specific == SPECIFIC_CARRIER:
            return "carrier"
        if entry.type_ == TYPE_AIRBASE:
            return "airbase"
        if entry.type_ == TYPE_AIRSTRIP:
            return "airstrip"
        if entry.type_ == TYPE_ARMYBASE:
            return "armybase"
        return None

    @property
    def is_airfield_objective(self) -> bool:
        return self.airfield_kind is not None


def parse_objectives(
    entry: CampaignEntry,
    *,
    container_version: int | None,
    support: SupportData,
) -> tuple[Objective, ...]:
    """Parse every objective in one decoded OBJ campaign entry."""

    if not entry.name.casefold().endswith(".obj"):
        raise ValueError(f"expected a .obj entry, got {entry.name!r}")
    record_count = entry.metadata.get("num_objectives")
    if not isinstance(record_count, int):
        raise ObjRecordError(f"{entry.name}: missing .obj num_objectives metadata")

    reader = _BinaryReader(entry.decoded)
    objectives: list[Objective] = []
    for record_index in range(record_count):
        start = reader.tell()
        try:
            objectives.append(
                _read_objective(
                    reader,
                    version=container_version,
                    support=support,
                )
            )
        except BinaryParseError as exc:
            raise ObjRecordError(
                f"truncated objective record {record_index} at offset {start}: {exc}"
            ) from exc
    if reader.tell() != len(entry.decoded):
        raise ObjRecordError(
            f"record walk ended at {reader.tell()}, decoded payload has "
            f"{len(entry.decoded)} bytes"
        )
    return tuple(objectives)


def _read_objective(
    reader: _BinaryReader,
    *,
    version: int | None,
    support: SupportData,
) -> Objective:
    objective_type = reader.u16()
    reader.skip(8)  # objective VU_ID
    entity_type_copy = reader.u16()
    if entity_type_copy != objective_type:
        raise ObjRecordError(
            f"objective type copy mismatch: {entity_type_copy} != {objective_type}"
        )
    reader.skip(4)  # grid x/y
    if _supports(version, 70):
        reader.skip(4)  # z
    reader.skip(4 + 2 + 2 + 1)  # spot time, spotted, base flags, owner
    camp_id = reader.i16()
    reader.skip(4)  # last repair
    reader.skip(2 if version is not None and version <= 1 else 4)  # flags
    reader.skip(3)  # supply, fuel, losses
    feature_count = reader.u8()
    feature_statuses = tuple(reader.u8() for _ in range(feature_count))
    reader.skip(1 + 2 + 8)  # priority, name ID, parent VU_ID
    first_owner = reader.u8()
    link_count = reader.u8()
    reader.skip(link_count * LINK_SIZE)
    if _supports(version, 20):
        has_radar_data = reader.u8()
        if has_radar_data:
            reader.skip(RADAR_RATIO_COUNT * 4)
    reader.skip(OBJECTIVE_TAIL_RAW_SIZE)
    name = reader.read_bytes(OBJECTIVE_NAME_SIZE).split(b"\x00", 1)[0].decode(
        "latin-1", errors="replace"
    )
    return Objective(
        objective_type=objective_type,
        camp_id=camp_id,
        name=name,
        feature_statuses=feature_statuses,
        support=support,
        first_owner=first_owner,
    )


def _supports(version: int | None, minimum: int) -> bool:
    return version is None or version >= minimum


class _BinaryReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def tell(self) -> int:
        return self.offset

    def skip(self, size: int) -> None:
        self._ensure(size)
        self.offset += size

    def read_bytes(self, size: int) -> bytes:
        self._ensure(size)
        value = self.data[self.offset : self.offset + size]
        self.offset += size
        return value

    def u8(self) -> int:
        self._ensure(1)
        value = self.data[self.offset]
        self.offset += 1
        return value

    def i16(self) -> int:
        self._ensure(2)
        value = struct.unpack_from("<h", self.data, self.offset)[0]
        self.offset += 2
        return value

    def u16(self) -> int:
        self._ensure(2)
        value = struct.unpack_from("<H", self.data, self.offset)[0]
        self.offset += 2
        return value

    def _ensure(self, size: int) -> None:
        if size < 0:
            raise ValueError("size must be >= 0")
        if self.offset + size > len(self.data):
            remaining = len(self.data) - self.offset
            raise BinaryParseError(
                f"need {size} bytes at offset {self.offset}, "
                f"only {remaining} remain"
            )

