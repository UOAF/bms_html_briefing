"""Small little-endian binary reader."""

from __future__ import annotations

from dataclasses import dataclass
import struct


class BinaryParseError(RuntimeError):
    """Raised when a binary read would pass EOF."""


VuId = tuple[int, int]


class Codec:
    """Binary encoder for one parsed field value."""

    def encode(self, value: object) -> bytes:
        raise NotImplementedError


@dataclass(frozen=True)
class StructCodec(Codec):
    fmt: str

    def encode(self, value: object) -> bytes:
        return struct.pack(self.fmt, value)


@dataclass(frozen=True)
class BytesCodec(Codec):
    size: int | None = None

    def encode(self, value: object) -> bytes:
        if not isinstance(value, bytes):
            raise TypeError("bytes field value must be bytes")
        if self.size is not None and len(value) != self.size:
            raise ValueError(f"bytes field expected {self.size} bytes, got {len(value)}")
        return value


@dataclass(frozen=True)
class VuIdCodec(Codec):
    def encode(self, value: object) -> bytes:
        num, creator = as_vuid_pair(value)
        return struct.pack("<II", num, creator)


I16 = StructCodec("<h")
U16 = StructCodec("<H")
I32 = StructCodec("<i")
U32 = StructCodec("<I")
U8 = StructCodec("<B")
F32 = StructCodec("<f")
VUID = VuIdCodec()


class BinaryReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def tell(self) -> int:
        return self.offset

    def remaining(self) -> int:
        return len(self.data) - self.offset

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

    def i32(self) -> int:
        self._ensure(4)
        value = struct.unpack_from("<i", self.data, self.offset)[0]
        self.offset += 4
        return value

    def u32(self) -> int:
        self._ensure(4)
        value = struct.unpack_from("<I", self.data, self.offset)[0]
        self.offset += 4
        return value

    def f32(self) -> float:
        self._ensure(4)
        value = struct.unpack_from("<f", self.data, self.offset)[0]
        self.offset += 4
        return value

    def vu_id(self) -> VuId:
        return self.u32(), self.u32()

    def _ensure(self, size: int) -> None:
        if size < 0:
            raise ValueError("size must be >= 0")
        if self.offset + size > len(self.data):
            raise BinaryParseError(
                f"need {size} bytes at offset {self.offset}, only {self.remaining()} remain"
            )


def as_tuple_value(value: object) -> tuple:
    if not isinstance(value, tuple):
        raise TypeError("field value must be a tuple")
    return value


def as_vuid_pair(value: object) -> VuId:
    items = as_tuple_value(value)
    if len(items) != 2:
        raise ValueError(f"expected VU_ID pair, got {len(items)} values")
    return int(items[0]), int(items[1])
