#!/usr/bin/env python3
"""Shared parser primitives and dispatch registry.

This module intentionally contains only cross-cutting infrastructure:
- common datatypes and reader utilities
- support-file lookup and string-table loading
- parser registration/dispatch
- container version detection via `.ver`
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import struct
from typing import Any, Callable

logger = logging.getLogger("html_brief_log")


class CamFormatError(RuntimeError):
    """Raised when the input .CAM/.TRN/.TAC file is malformed."""


class ParseError(RuntimeError):
    """Raised when parsed entry data is malformed."""


@dataclass(frozen=True)
class CamEntry:
    name: str
    offset: int
    length: int


@dataclass(frozen=True)
class DecodeResult:
    data: bytes
    compressed: bool
    metadata: dict[str, int]


@dataclass(frozen=True)
class DecodedEntry:
    entry: CamEntry
    raw: bytes
    decoded: DecodeResult


@dataclass(frozen=True)
class ParseContext:
    """Per-entry parse context passed to extension parsers."""

    container_version: int | None
    decode_metadata: dict[str, int] | None
    support_base_dir: Path | None


class BinaryReader:
    """Minimal little-endian sequential reader with bounds checks."""

    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def remaining(self) -> int:
        return len(self.data) - self.offset

    def _ensure(self, size: int) -> None:
        if self.offset + size > len(self.data):
            raise ParseError(
                f"need {size} bytes at offset {self.offset}, only {self.remaining()} remain"
            )

    def skip(self, size: int) -> None:
        self._ensure(size)
        self.offset += size

    def read_u8(self) -> int:
        self._ensure(1)
        value = self.data[self.offset]
        self.offset += 1
        return value

    def read_i16(self) -> int:
        self._ensure(2)
        value = struct.unpack_from("<h", self.data, self.offset)[0]
        self.offset += 2
        return value

    def read_u16(self) -> int:
        self._ensure(2)
        value = struct.unpack_from("<H", self.data, self.offset)[0]
        self.offset += 2
        return value

    def read_i32(self) -> int:
        self._ensure(4)
        value = struct.unpack_from("<i", self.data, self.offset)[0]
        self.offset += 4
        return value

    def read_u32(self) -> int:
        self._ensure(4)
        value = struct.unpack_from("<I", self.data, self.offset)[0]
        self.offset += 4
        return value

    def read_f32(self) -> float:
        self._ensure(4)
        value = struct.unpack_from("<f", self.data, self.offset)[0]
        self.offset += 4
        return value

    def read_bytes(self, size: int) -> bytes:
        self._ensure(size)
        value = self.data[self.offset : self.offset + size]
        self.offset += size
        return value


EntryParser = Callable[[bytes, ParseContext], dict[str, Any]]
_ENTRY_PARSERS: dict[str, EntryParser] = {}

_STRINGS_BY_ID_CACHE: dict[Path, dict[int, str]] = {}


def _decode_fixed_ascii(raw: bytes) -> str:
    """Decode null-terminated fixed-size ASCII fields."""

    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")


def _read_u16_le(data: bytes, offset: int) -> int:
    """Read a u16 from an arbitrary offset in a bytes blob."""

    if offset + 2 > len(data):
        raise CamFormatError(f"cannot read u16 at offset {offset}")
    return struct.unpack_from("<H", data, offset)[0]


def _read_u32_le(data: bytes, offset: int) -> int:
    """Read a u32 from an arbitrary offset in a bytes blob."""

    if offset + 4 > len(data):
        raise CamFormatError(f"cannot read u32 at offset {offset}")
    return struct.unpack_from("<I", data, offset)[0]


def _safe_int(text: str | None, *, default: int = 0) -> int:
    """Parse an int safely from XML text content with a default fallback."""

    if text is None:
        return default
    cleaned = text.strip()
    if not cleaned:
        return default
    try:
        return int(cleaned)
    except ValueError:
        return default


def _to_vuid_tuple(value: Any) -> tuple[int, int] | None:
    """Normalize a VU_ID dict-like object to a hashable `(num, creator)` tuple."""

    if not isinstance(value, dict):
        return None
    num = value.get("num")
    creator = value.get("creator")
    if isinstance(num, int) and isinstance(creator, int):
        return (num, creator)
    return None


def _read_vuid(reader: BinaryReader) -> dict[str, int]:
    """Read VU_ID struct (two u32 values) from the current stream position."""

    return {"num": reader.read_u32(), "creator": reader.read_u32()}


def _find_support_file(
    name: str,
    *,
    support_base_dir: Path | None = None,
) -> Path | None:
    """Find support assets (XML / Strings.txt) in common search locations."""

    script_dir = Path(__file__).resolve().parent
    candidates: list[Path] = []
    if support_base_dir is not None:
        support_base_dir = support_base_dir.resolve()
        # Strings are campaign assets; prefer Campaign over Objects when both exist.
        is_strings = name.lower() == "strings.txt"
        if is_strings and support_base_dir.name.lower() == "objects":
            theater_data_dir = support_base_dir.parent.parent
            candidates.extend(
                [
                    theater_data_dir / "Campaign" / name,
                    support_base_dir / name,
                ]
            )
        else:
            candidates.extend(
                [
                    support_base_dir / name,
                ]
            )
        # If support dir is .../TerrData/Objects, campaign strings are in ../.. /Campaign.
        if support_base_dir.name.lower() == "objects" and not is_strings:
            theater_data_dir = support_base_dir.parent.parent
            candidates.append(theater_data_dir / "Campaign" / name)
    candidates.extend(
        [
            Path.cwd() / name,
            script_dir / name,
        ]
    )
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            logger.debug("Support file resolved: %s -> %s", name, resolved)
            return resolved
        # Linux installs often use mixed-case filenames (e.g. Falcon4_CT.xml).
        parent = resolved.parent
        wanted = resolved.name.lower()
        try:
            if parent.is_dir():
                for child in parent.iterdir():
                    if child.is_file() and child.name.lower() == wanted:
                        logger.debug("Support file resolved (case-insensitive): %s -> %s", name, child)
                        return child.resolve()
        except Exception:
            continue
    logger.debug("Support file not found: %s (support_base_dir=%s)", name, support_base_dir)
    return None


def _load_strings_by_id(path: Path) -> dict[int, str]:
    """Load BMS `Strings.txt` tab-separated id -> text mapping."""

    cached = _STRINGS_BY_ID_CACHE.get(path)
    if cached is not None:
        logger.debug("Strings cache hit: %s entries=%d", path, len(cached))
        return cached

    strings_by_id: dict[int, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            text = line.rstrip("\r\n")
            if not text:
                continue
            key_value = text.split("\t", 1)
            if len(key_value) != 2:
                continue
            key_text, value = key_value
            if not key_text.isdigit():
                continue
            strings_by_id[int(key_text)] = value

    _STRINGS_BY_ID_CACHE[path] = strings_by_id
    logger.debug("Strings loaded: %s entries=%d", path, len(strings_by_id))
    return strings_by_id


def _load_strings(support_base_dir: Path | None) -> dict[int, str]:
    """Resolve and load the campaign string table if available."""

    strings_path = _find_support_file("Strings.txt", support_base_dir=support_base_dir)
    if strings_path is None:
        strings_path = _find_support_file("strings.txt", support_base_dir=support_base_dir)
    if strings_path is None:
        return {}
    return _load_strings_by_id(strings_path)


def _format_campaign_time_z(value_ms: int | None) -> str | None:
    """Convert campaign milliseconds to a clock string (HH:MM:SS[.mmm]z)."""

    if not isinstance(value_ms, int) or value_ms < 0:
        return None
    total_seconds, milliseconds = divmod(value_ms, 1000)
    hours = (total_seconds // 3600) % 24
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if milliseconds:
        return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}z"
    return f"{hours:02}:{minutes:02}:{seconds:02}z"


def _parse_ver(data: bytes) -> dict[str, Any]:
    """Parse `.ver` payload and return numeric version when present."""

    text = data.decode("ascii", errors="replace").strip("\x00\r\n\t ")
    version: int | None = None
    if text.isdigit():
        version = int(text)
    return {
        "file_type": "ver",
        "size": len(data),
        "raw_ascii": text,
        "version": version,
    }


def register_entry_parser(ext: str, parser: EntryParser) -> None:
    """Register an extension parser callback (e.g. `.cmp`, `.uni`)."""

    normalized = ext.lower()
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    _ENTRY_PARSERS[normalized] = parser


def _parse_entry_data(
    name: str,
    data: bytes,
    *,
    container_version: int | None,
    decode_metadata: dict[str, int] | None,
    support_base_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Dispatch a decoded entry to registered extension parser."""

    ext = Path(name).suffix.lower()

    if ext == ".ver":
        return _parse_ver(data)

    parser = _ENTRY_PARSERS.get(ext)
    if parser is None:
        logger.debug("No parser registered for entry %s (%s)", name, ext)
        return None

    context = ParseContext(
        container_version=container_version,
        decode_metadata=decode_metadata,
        support_base_dir=support_base_dir,
    )
    parsed = parser(data, context)
    logger.debug("Parsed entry %s (%s): size=%d", name, ext, len(data))
    return parsed


def _detect_container_version(decoded_entries: list[DecodedEntry]) -> int | None:
    """Detect campaign serialization version from decoded `.ver` entry."""

    for item in decoded_entries:
        if Path(item.entry.name).suffix.lower() != ".ver":
            continue
        parsed_ver = _parse_ver(item.decoded.data)
        version = parsed_ver.get("version")
        if isinstance(version, int):
            logger.debug("Container version detected from %s: %d", item.entry.name, version)
            return version
    logger.debug("Container version not detected (no parseable .ver entry)")
    return None


def register_default_parsers() -> None:
    """Register built-in entry parsers used by this package."""

    # Local import prevents module initialization cycles.
    from .cmp import _parse_cmp
    from .uni import _parse_uni

    register_entry_parser(".cmp", _parse_cmp)
    register_entry_parser(".uni", _parse_uni)
    logger.debug("Registered default CAM entry parsers: .cmp, .uni")
