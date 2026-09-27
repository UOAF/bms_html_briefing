"""Lossless parsing of standalone BMS FMAP v5/v8 weather maps.

Layout: https://wiki.falcon-bms.com/tutorials/format/fmap
Ported from Frag Helper's lib/weather.py; no forecast or briefing behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import struct


FMAP_HEADER_SIZE = 44
FMAP_SUPPORTED_VERSIONS = frozenset((5, 8))
FMAP_WIND_LEVELS_FT = (0, 3000, 6000, 9000, 12000, 18000, 24000, 30000, 40000, 50000)


class FmapRecordError(ValueError):
    """Raised when an FMAP layout is unsupported or malformed."""


@dataclass(frozen=True)
class FmapRecord:
    """Stored values; grid arrays use file order, winds use [cell][level]."""

    version: int
    width: int
    height: int
    movement_heading_deg: int
    movement_speed_knots: float
    stratus_fair_ft: int
    stratus_inclement_ft: int
    contrail_altitudes_ft: tuple[int, ...]
    weather_types: tuple[int, ...]
    pressure_hpa: tuple[float, ...]
    temperature_c: tuple[float, ...]
    wind_speeds_knots: tuple[tuple[float, ...], ...]
    wind_directions_deg: tuple[tuple[float, ...], ...]
    cumulus_base_ft: tuple[float, ...]
    cumulus_density: tuple[int, ...]
    cumulus_size: tuple[float, ...]
    tower_cumulus_flags: tuple[int, ...]
    shower_cumulus_flags: tuple[int, ...] | None
    fog_end_km: tuple[float, ...]
    fog_layer_z_ft: tuple[float, ...] | None
    raw: bytes = field(repr=False)

    @property
    def cell_count(self) -> int:
        return self.width * self.height

    def to_bytes(self) -> bytes:
        """Recover the original payload exactly; this is not an edit encoder."""
        return self.raw


def parse_fmap_record(blob: bytes) -> FmapRecord:
    """Decode a complete v5/v8 payload without inferring a theater or defaults."""

    if not isinstance(blob, bytes):
        raise TypeError("FMAP payload must be bytes")
    if len(blob) < FMAP_HEADER_SIZE:
        raise FmapRecordError("FMAP is shorter than its 44-byte header")
    version, width, height = struct.unpack_from("<Iii", blob)
    if version not in FMAP_SUPPORTED_VERSIONS:
        raise FmapRecordError(f"unsupported FMAP version {version}")
    if width <= 0 or height <= 0:
        raise FmapRecordError(f"invalid FMAP dimensions {width}x{height}")

    cell_count = width * height
    words_per_cell = 30 if version == 8 else 28
    expected_size = FMAP_HEADER_SIZE + words_per_cell * cell_count * 4
    if len(blob) != expected_size:
        raise FmapRecordError(
            f"FMAP v{version} size is {len(blob)} bytes; expected "
            f"{expected_size} for {width}x{height}"
        )
    # Check size before allocating arrays. No arbitrary theater/grid size cap.
    cursor = FMAP_HEADER_SIZE

    def read_int_array() -> tuple[int, ...]:
        nonlocal cursor
        values = struct.unpack_from(f"<{cell_count}i", blob, cursor)
        cursor += cell_count * 4
        return values

    def read_float_array() -> tuple[float, ...]:
        nonlocal cursor
        values = struct.unpack_from(f"<{cell_count}f", blob, cursor)
        cursor += cell_count * 4
        return values

    def read_winds() -> tuple[tuple[float, ...], ...]:
        nonlocal cursor
        level_count = len(FMAP_WIND_LEVELS_FT)
        values = struct.unpack_from(f"<{cell_count * level_count}f", blob, cursor)
        cursor += cell_count * level_count * 4
        return tuple(
            values[start : start + level_count]
            for start in range(0, len(values), level_count)
        )

    weather_types = read_int_array()
    pressure_hpa = read_float_array()
    temperature_c = read_float_array()
    wind_speeds_knots = read_winds()
    wind_directions_deg = read_winds()
    cumulus_base_ft = read_float_array()
    cumulus_density = read_int_array()
    cumulus_size = read_float_array()
    tower_cumulus_flags = read_int_array()
    shower_cumulus_flags = read_int_array() if version == 8 else None
    fog_end_km = read_float_array()
    fog_layer_z_ft = read_float_array() if version == 8 else None
    if cursor != len(blob):
        raise FmapRecordError(f"unconsumed FMAP bytes at offset {cursor}")

    return FmapRecord(
        version=version,
        width=width,
        height=height,
        movement_heading_deg=struct.unpack_from("<i", blob, 12)[0],
        movement_speed_knots=struct.unpack_from("<f", blob, 16)[0],
        stratus_fair_ft=struct.unpack_from("<i", blob, 20)[0],
        stratus_inclement_ft=struct.unpack_from("<i", blob, 24)[0],
        contrail_altitudes_ft=struct.unpack_from("<4i", blob, 28),
        weather_types=weather_types,
        pressure_hpa=pressure_hpa,
        temperature_c=temperature_c,
        wind_speeds_knots=wind_speeds_knots,
        wind_directions_deg=wind_directions_deg,
        cumulus_base_ft=cumulus_base_ft,
        cumulus_density=cumulus_density,
        cumulus_size=cumulus_size,
        tower_cumulus_flags=tower_cumulus_flags,
        shower_cumulus_flags=shower_cumulus_flags,
        fog_end_km=fog_end_km,
        fog_layer_z_ft=fog_layer_z_ft,
        raw=blob,
    )
