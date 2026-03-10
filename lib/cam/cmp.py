"""CMP entry parser API."""

from __future__ import annotations

from typing import Any

from .core import (
    BinaryReader,
    ParseContext,
    _decode_fixed_ascii,
    _format_campaign_time_z,
    _read_vuid,
)


def _parse_cmp(data: bytes, _ctx: ParseContext) -> dict[str, Any]:
    """Parse `.cmp` campaign state fields needed for summary extraction.

    The parser intentionally decodes a stable subset (current time, bullseye,
    identifying strings, player squadron id) and stores the remaining tail as
    opaque bytes metadata.
    """

    reader = BinaryReader(data)
    parsed: dict[str, Any] = {
        "file_type": "cmp",
        "size": len(data),
    }

    current_time = reader.read_u32()
    parsed["current_time"] = current_time
    parsed["current_time_z"] = _format_campaign_time_z(current_time)

    parsed["te_start_time"] = reader.read_u32()
    parsed["te_time_limit"] = reader.read_u32()
    parsed["te_victory_points"] = reader.read_i32()
    parsed["te_type"] = reader.read_i32()
    parsed["te_number_teams"] = reader.read_i32()

    # Skip arrays/fields that are currently not needed by the summary surface.
    reader.skip(8 * 4)
    reader.skip(8 * 4)
    reader.read_i32()
    reader.skip(8 * 4)
    reader.read_i32()

    for _ in range(8):
        reader.read_u8()
        reader.read_u8()
        reader.read_bytes(20)
        reader.read_bytes(200)

    reader.skip(4 * 4)

    for _ in range(9):
        reader.read_i16()

    reader.read_u8()
    reader.read_u8()
    reader.read_u8()
    reader.read_u8()
    reader.read_u8()
    reader.read_u8()
    reader.read_u8()

    parsed["bullseye_name_id"] = reader.read_u8()
    parsed["bullseye_x"] = reader.read_i16()
    parsed["bullseye_y"] = reader.read_i16()

    parsed["theater_name"] = _decode_fixed_ascii(reader.read_bytes(40))
    parsed["scenario"] = _decode_fixed_ascii(reader.read_bytes(40))
    parsed["save_file"] = _decode_fixed_ascii(reader.read_bytes(40))
    parsed["ui_name"] = _decode_fixed_ascii(reader.read_bytes(40))
    parsed["player_squadron_id"] = _read_vuid(reader)

    tail = reader.read_bytes(reader.remaining())
    parsed["undocumented_tail_size"] = len(tail)
    parsed["undocumented_tail_head_hex"] = tail[:64].hex()
    return parsed


__all__ = ["_parse_cmp"]
