from __future__ import annotations

import logging
import math
import re
import struct
import threading
from dataclasses import dataclass
from pathlib import Path

from lib.theater_paths import resolve_theater_txt_path


logger = logging.getLogger("html_brief_log")

FEET_TO_METERS = 0.3048
DEFAULT_HEIGHTMAP_SIZE = 32768


class TerrainElevationError(RuntimeError):
    """Base error for BMS terrain elevation lookup failures."""


class HeightmapNotFoundError(TerrainElevationError):
    """Raised when the active theater heightmap cannot be resolved."""


class CoordinateOutOfBoundsError(TerrainElevationError):
    """Raised when a BMS coordinate is outside the active theater bounds."""


class HeightmapReadError(TerrainElevationError):
    """Raised when a heightmap sample cannot be read."""


@dataclass(frozen=True)
class HeightmapSpec:
    path: Path
    width: int
    height: int
    max_north_feet: float
    max_east_feet: float


class HeightmapSampler:
    def __init__(self, spec: HeightmapSpec):
        self.spec = spec
        self._file = None
        self._lock = threading.Lock()

    def elevation_feet(self, north_feet: float, east_feet: float) -> int:
        if north_feet < 0 or north_feet > self.spec.max_north_feet or east_feet < 0 or east_feet > self.spec.max_east_feet:
            raise CoordinateOutOfBoundsError(
                "Coordinates outside theater bounds: "
                f"north={north_feet:.1f}, east={east_feet:.1f}, "
                f"max_north={self.spec.max_north_feet:.1f}, max_east={self.spec.max_east_feet:.1f}"
            )

        east_ratio = east_feet / self.spec.max_east_feet if self.spec.max_east_feet else 0
        north_ratio = north_feet / self.spec.max_north_feet if self.spec.max_north_feet else 0
        pixel_x = int(east_ratio * (self.spec.width - 1))
        pixel_y = int((1.0 - north_ratio) * (self.spec.height - 1))
        pixel_x = max(0, min(self.spec.width - 1, pixel_x))
        pixel_y = max(0, min(self.spec.height - 1, pixel_y))

        offset = (pixel_y * self.spec.width + pixel_x) * 2
        with self._lock:
            if self._file is None:
                try:
                    self._file = self.spec.path.open("rb")
                except OSError as exc:
                    raise HeightmapReadError(f"Could not open heightmap {self.spec.path}: {exc}") from exc
            try:
                self._file.seek(offset)
                raw = self._file.read(2)
            except OSError as exc:
                raise HeightmapReadError(f"Could not read heightmap {self.spec.path}: {exc}") from exc

        if len(raw) != 2:
            raise HeightmapReadError(f"Expected 2 bytes at offset {offset}, got {len(raw)}")
        return int(struct.unpack("<h", raw)[0])


_SAMPLER_CACHE: dict[tuple[str, str], HeightmapSampler] = {}
_CACHE_LOCK = threading.Lock()
_THEATER_VALUE_RE = re.compile(r"^\s*([^=]+?)\s*=\s*(.*?)\s*$")


def get_terrain_elevation_feet(
    base_dir: str | Path | None,
    theater_name: str | None,
    north_feet: float,
    east_feet: float,
    theater_size_km: float | None = None,
) -> int:
    sampler = get_heightmap_sampler(base_dir, theater_name, theater_size_km=theater_size_km)
    return sampler.elevation_feet(float(north_feet), float(east_feet))


def get_heightmap_sampler(
    base_dir: str | Path | None,
    theater_name: str | None,
    theater_size_km: float | None = None,
) -> HeightmapSampler:
    if not base_dir or not theater_name:
        raise HeightmapNotFoundError("BMS base directory or theater name is not configured")

    key = (str(Path(base_dir).expanduser().resolve()), str(theater_name).lower())
    with _CACHE_LOCK:
        sampler = _SAMPLER_CACHE.get(key)
        if sampler is None:
            sampler = HeightmapSampler(_resolve_heightmap_spec(base_dir, theater_name, theater_size_km))
            _SAMPLER_CACHE[key] = sampler
        return sampler


def _resolve_heightmap_spec(
    base_dir: str | Path,
    theater_name: str,
    theater_size_km: float | None,
) -> HeightmapSpec:
    theater_txt = resolve_theater_txt_path(base_dir, theater_name)
    if theater_txt is None:
        raise HeightmapNotFoundError(f"Theater.txt could not be resolved for theater {theater_name!r}")

    theater_values = _read_theater_values(theater_txt)
    size_km = _float_or_none(theater_values.get("theater size in km")) or theater_size_km
    if not size_km or size_km <= 0:
        raise HeightmapNotFoundError(f"Theater size is missing from {theater_txt}")

    heightmap_path = _find_heightmap_path(theater_txt.parent)
    width, height = _resolve_heightmap_dimensions(
        heightmap_path,
        _int_or_none(theater_values.get("map size in pixels")),
    )
    max_feet = size_km * 1000 / FEET_TO_METERS
    spec = HeightmapSpec(
        path=heightmap_path,
        width=width,
        height=height,
        max_north_feet=max_feet,
        max_east_feet=max_feet,
    )
    logger.info("Resolved BMS heightmap for %s: %s (%dx%d)", theater_name, heightmap_path, width, height)
    return spec


def _read_theater_values(theater_txt: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = theater_txt.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise HeightmapNotFoundError(f"Could not read {theater_txt}: {exc}") from exc
    for line in lines:
        match = _THEATER_VALUE_RE.match(line)
        if match:
            values[match.group(1).strip().lower()] = match.group(2).strip()
    return values


def _find_heightmap_path(newterrain_dir: Path) -> Path:
    path = _resolve_case_insensitive(newterrain_dir, ["HeightMaps", "HeightMap.raw"])
    if path is not None and path.is_file():
        return path
    try:
        for candidate in newterrain_dir.rglob("*"):
            if candidate.is_file() and candidate.name.lower() == "heightmap.raw":
                return candidate
    except OSError:
        pass
    raise HeightmapNotFoundError(f"HeightMap.raw not found under {newterrain_dir}")


def _resolve_heightmap_dimensions(heightmap_path: Path, configured_size: int | None) -> tuple[int, int]:
    if configured_size and configured_size > 0:
        return configured_size, configured_size
    try:
        samples = heightmap_path.stat().st_size // 2
    except OSError as exc:
        raise HeightmapReadError(f"Could not stat {heightmap_path}: {exc}") from exc
    side = int(math.isqrt(samples))
    if side > 0 and side * side == samples:
        return side, side
    logger.warning("Could not infer square heightmap size from %s; using %d", heightmap_path, DEFAULT_HEIGHTMAP_SIZE)
    return DEFAULT_HEIGHTMAP_SIZE, DEFAULT_HEIGHTMAP_SIZE


def _resolve_case_insensitive(root: Path, rel_parts: list[str]) -> Path | None:
    current = root
    for part in rel_parts:
        candidate = current / part
        if candidate.exists():
            current = candidate
            continue
        try:
            current = next(child for child in current.iterdir() if child.name.lower() == part.lower())
        except (FileNotFoundError, NotADirectoryError, PermissionError, StopIteration):
            return None
    return current


def _float_or_none(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _int_or_none(value: str | None) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except ValueError:
        return None


__all__ = [
    "CoordinateOutOfBoundsError",
    "HeightmapNotFoundError",
    "HeightmapReadError",
    "HeightmapSampler",
    "HeightmapSpec",
    "TerrainElevationError",
    "get_heightmap_sampler",
    "get_terrain_elevation_feet",
]
