"""Typed convenience wrappers for parsed `.cmp` campaign records."""

from __future__ import annotations

from dataclasses import dataclass

from .cmp_parser import CmpRecord
from .record_fields import FieldMap
from .support_files import format_campaign_time_z


@dataclass
class Campaign:
    """Convenience API for one parsed campaign record."""

    record: CmpRecord

    @property
    def fields(self) -> FieldMap:
        return self.record.fields

    def get(self, name: str) -> object:
        return self.record.get(name)

    def set(self, name: str, value: object) -> None:
        self.record.set(name, value)

    @property
    def current_time_ms(self) -> int:
        return self.record.current_time

    @current_time_ms.setter
    def current_time_ms(self, value: int) -> None:
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError(f"current_time_ms must fit in uint32, got {value}")
        self.set("current_time", value)

    @property
    def current_time_z(self) -> str | None:
        return format_campaign_time_z(self.current_time_ms)

    @property
    def bullseye_name(self) -> int:
        return int(self.get("bullseye_name"))

    @bullseye_name.setter
    def bullseye_name(self, value: int) -> None:
        if not 0 <= value <= 255:
            raise ValueError(f"bullseye_name must fit in uint8, got {value}")
        self.set("bullseye_name", value)

    @property
    def bullseye_x(self) -> int:
        return int(self.get("bullseye_x"))

    @bullseye_x.setter
    def bullseye_x(self, value: int) -> None:
        _validate_i16("bullseye_x", value)
        self.set("bullseye_x", value)

    @property
    def bullseye_y(self) -> int:
        return int(self.get("bullseye_y"))

    @bullseye_y.setter
    def bullseye_y(self, value: int) -> None:
        _validate_i16("bullseye_y", value)
        self.set("bullseye_y", value)

    @property
    def bullseye(self) -> tuple[int, int]:
        return self.bullseye_x, self.bullseye_y

    @bullseye.setter
    def bullseye(self, value: tuple[int, int]) -> None:
        if len(value) != 2:
            raise ValueError(f"bullseye must be an x/y pair, got {len(value)} values")
        x, y = value
        self.bullseye_x = x
        self.bullseye_y = y

    def to_view(self) -> dict[str, object]:
        return {
            "current_time_ms": self.current_time_ms,
            "current_time_z": self.current_time_z,
            "bullseye": {
                "name": self.bullseye_name,
                "x": self.bullseye_x,
                "y": self.bullseye_y,
            },
        }


def wrap_campaign(record: CmpRecord) -> Campaign:
    return Campaign(record)


def _validate_i16(name: str, value: int) -> None:
    if not -0x8000 <= value <= 0x7FFF:
        raise ValueError(f"{name} must fit in int16, got {value}")
