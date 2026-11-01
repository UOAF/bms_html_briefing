"""Read the CAM entries OpenChart needs.

Adapted from OpenCAM's deterministic CAM container and LZSS readers at
commit e4dbcb54a9f4751f3045e1fd96f8627c5bf78115. The optional CMP decoder
and padding checks follow OpenCAM commit d9cb9746a2b59b239061cb838071ae22d666cfde.
OBJ is decoded by default; ownership lookup also requests CMP decoding.
Container rebuilding and other campaign-entry codecs are intentionally absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import struct


INDEX_BIT_COUNT = 12
LENGTH_BIT_COUNT = 4
WINDOW_SIZE = 1 << INDEX_BIT_COUNT
BREAK_EVEN = (1 + INDEX_BIT_COUNT + LENGTH_BIT_COUNT) // 9


class CamFormatError(RuntimeError):
    """Raised when a CAM container or required entry is malformed."""


class LzssError(RuntimeError):
    """Raised when an LZSS payload is malformed."""


@dataclass(frozen=True)
class CampaignEntry:
    name: str
    decoded: bytes
    metadata: dict[str, int] = field(default_factory=dict)


class CamContainer:
    """Read-only representation of the entries in a BMS CAM container."""

    def __init__(self, entries: tuple[CampaignEntry, ...]):
        self.entries = entries

    @classmethod
    def from_bytes(cls, blob: bytes, *, decode_cmp: bool = False) -> CamContainer:
        entries: list[CampaignEntry] = []
        for name, offset, length in _parse_directory(blob):
            raw = blob[offset : offset + length]
            if Path(name).suffix.casefold() == ".obj":
                decoded, metadata = _decode_obj_payload(name, raw)
            elif decode_cmp and Path(name).suffix.casefold() == ".cmp":
                decoded, metadata = _decode_cmp_payload(name, raw)
            else:
                decoded, metadata = raw, {}
            entries.append(CampaignEntry(name, decoded, metadata))
        return cls(tuple(entries))

    @classmethod
    def from_path(
        cls, path: str | Path, *, decode_cmp: bool = False
    ) -> CamContainer:
        return cls.from_bytes(Path(path).read_bytes(), decode_cmp=decode_cmp)


def detect_container_version(container: CamContainer) -> int | None:
    """Return the numeric embedded VER payload, when present."""

    for entry in container.entries:
        if not entry.name.casefold().endswith(".ver"):
            continue
        text = entry.decoded.decode("ascii", errors="replace").strip(
            "\x00\r\n\t "
        )
        if text.isdigit():
            return int(text)
    return None


def _parse_directory(blob: bytes) -> tuple[tuple[str, int, int], ...]:
    if len(blob) < 8:
        raise CamFormatError("file is too small to be a CAM container")

    directory_offset = _read_u32_le(blob, 0)
    if directory_offset >= len(blob):
        raise CamFormatError(f"directory offset {directory_offset} is past EOF")

    entry_count = _read_u32_le(blob, directory_offset)
    cursor = directory_offset + 4
    entries: list[tuple[str, int, int]] = []
    for index in range(entry_count):
        if cursor >= len(blob):
            raise CamFormatError(f"unexpected end of directory at entry {index}")
        name_length = blob[cursor]
        cursor += 1
        if cursor + name_length + 8 > len(blob):
            raise CamFormatError(f"directory entry {index} is truncated")
        name = blob[cursor : cursor + name_length].decode(
            "ascii", errors="replace"
        )
        cursor += name_length
        offset = _read_u32_le(blob, cursor)
        cursor += 4
        length = _read_u32_le(blob, cursor)
        cursor += 4
        if offset + length > len(blob):
            raise CamFormatError(f"entry {name!r} points outside file bounds")
        entries.append((name, offset, length))
    return tuple(entries)


def _decode_cmp_payload(
    name: str,
    raw: bytes,
) -> tuple[bytes, dict[str, int]]:
    if len(raw) < 8:
        raise CamFormatError(f"{name}: too short for .cmp header")

    compressed_size = _read_u32_le(raw, 0)
    uncompressed_size = _read_u32_le(raw, 4)
    _validate_expected_length(name, raw, compressed_size + 4)

    payload = raw[8 : 8 + (compressed_size - 4)]
    decoded, consumed = _lzss_expand(payload, uncompressed_size)
    _validate_lzss_consumption(name, payload, consumed)
    return decoded, {
        "compressed_size": compressed_size,
        "uncompressed_size": uncompressed_size,
    }


def _validate_expected_length(name: str, raw: bytes, expected_length: int) -> None:
    if expected_length > len(raw):
        raise CamFormatError(f"{name}: expected entry length {expected_length}, got {len(raw)}")
    if expected_length < len(raw) and any(raw[expected_length:]):
        raise CamFormatError(f"{name}: nonzero trailing bytes after compressed payload")


def _validate_lzss_consumption(name: str, payload: bytes, consumed: int) -> None:
    if consumed != len(payload) and any(payload[consumed:]):
        raise CamFormatError(f"{name}: nonzero trailing bytes after LZSS payload")


def _decode_obj_payload(
    name: str,
    raw: bytes,
) -> tuple[bytes, dict[str, int]]:
    if len(raw) < 10:
        raise CamFormatError(f"{name}: too short for .obj header")

    objective_count = _read_u16_le(raw, 0)
    uncompressed_size = _read_u32_le(raw, 2)
    compressed_size = _read_u32_le(raw, 6)
    if len(raw) != 10 + compressed_size:
        raise CamFormatError(f"{name}: invalid .obj compressed size")

    payload = raw[10:]
    decoded, consumed = _lzss_expand(payload, uncompressed_size)
    if consumed != len(payload):
        raise CamFormatError(
            f"{name}: LZSS consumed {consumed} bytes, expected {len(payload)}"
        )
    return decoded, {
        "compressed_size": compressed_size,
        "num_objectives": objective_count,
        "uncompressed_size": uncompressed_size,
    }


def _lzss_expand(compressed: bytes, uncompressed_size: int) -> tuple[bytes, int]:
    if uncompressed_size < 0:
        raise ValueError("uncompressed_size must be >= 0")
    if uncompressed_size == 0:
        return b"", 0
    if not compressed:
        raise LzssError("compressed input is empty")

    window = bytearray(WINDOW_SIZE)
    output = bytearray()
    input_index = 1
    flag_bit_mask = 1
    flag_byte = compressed[0]
    current_position = 1
    remaining = uncompressed_size

    while remaining > 0:
        consumed_flag_byte = False
        if flag_bit_mask == 0x100:
            if input_index >= len(compressed):
                raise LzssError("unexpected end of input while reading flag byte")
            flag_bit_mask = 1
            flag_byte = compressed[input_index]
            consumed_flag_byte = True

        flag_bit_mask <<= 1
        is_literal = (flag_byte & (flag_bit_mask >> 1)) != 0
        if is_literal:
            if consumed_flag_byte:
                input_index += 1
            if input_index >= len(compressed):
                raise LzssError("unexpected end of input while reading literal")
            value = compressed[input_index]
            input_index += 1
            output.append(value)
            remaining -= 1
            window[current_position] = value
            current_position = (current_position + 1) & (WINDOW_SIZE - 1)
            continue

        if consumed_flag_byte:
            input_index += 1
        if input_index + 1 >= len(compressed):
            raise LzssError("unexpected end of input while reading match pair")
        match_length = compressed[input_index]
        input_index += 1
        match_position = compressed[input_index]
        input_index += 1
        match_position |= (match_length & 0x0F) << 8
        match_length = (match_length >> 4) + BREAK_EVEN

        if match_length < remaining:
            copy_count = match_length + 1
            remaining -= copy_count
        else:
            copy_count = 0
            remaining = 0
        for index in range(copy_count):
            value = window[(match_position + index) & (WINDOW_SIZE - 1)]
            output.append(value)
            window[current_position] = value
            current_position = (current_position + 1) & (WINDOW_SIZE - 1)

    return bytes(output), input_index


def _read_u16_le(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        raise CamFormatError(f"cannot read u16 at offset {offset}")
    return struct.unpack_from("<H", data, offset)[0]


def _read_u32_le(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise CamFormatError(f"cannot read u32 at offset {offset}")
    return struct.unpack_from("<I", data, offset)[0]

