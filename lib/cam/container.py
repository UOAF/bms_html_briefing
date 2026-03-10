"""Container parsing, decoding, and extraction."""

from __future__ import annotations

import json
from pathlib import Path

from .lzss import LzssError, lzss_expand

from .core import (
    CamEntry,
    CamFormatError,
    DecodeResult,
    DecodedEntry,
    _detect_container_version,
    _parse_entry_data,
    _read_u16_le,
    _read_u32_le,
    register_default_parsers,
)


def parse_container(blob: bytes) -> list[CamEntry]:
    """Parse top-level CAM/TRN/TAC directory into entry descriptors."""

    if len(blob) < 8:
        raise CamFormatError("file is too small to be a CAM/TRN/TAC container")

    directory_offset = _read_u32_le(blob, 0)
    if directory_offset >= len(blob):
        raise CamFormatError(
            f"directory offset {directory_offset} is past end of file ({len(blob)})"
        )

    entry_count = _read_u32_le(blob, directory_offset)
    cursor = directory_offset + 4

    entries: list[CamEntry] = []
    for index in range(entry_count):
        if cursor >= len(blob):
            raise CamFormatError(f"unexpected end of directory at entry {index}")

        name_len = blob[cursor]
        cursor += 1

        if cursor + name_len + 8 > len(blob):
            raise CamFormatError(
                f"directory entry {index} is truncated (name_len={name_len})"
            )

        name = blob[cursor : cursor + name_len].decode("ascii", errors="replace")
        cursor += name_len

        offset = _read_u32_le(blob, cursor)
        cursor += 4
        length = _read_u32_le(blob, cursor)
        cursor += 4

        if offset + length > len(blob):
            raise CamFormatError(
                f"entry {name!r} points outside file bounds: "
                f"offset={offset}, length={length}, file_size={len(blob)}"
            )

        entries.append(CamEntry(name=name, offset=offset, length=length))

    return entries


def _decode_compressed_entry(name: str, raw: bytes) -> DecodeResult:
    """Decode a container entry payload based on extension-specific headers."""

    ext = Path(name).suffix.lower()

    if ext == ".cmp":
        if len(raw) < 8:
            raise CamFormatError(f"{name}: too short for .cmp compression header")

        compressed_size = _read_u32_le(raw, 0)
        uncompressed_size = _read_u32_le(raw, 4)

        if compressed_size < 4:
            raise CamFormatError(f"{name}: invalid compressed size {compressed_size}")
        if compressed_size + 4 != len(raw):
            raise CamFormatError(
                f"{name}: compressed_size+4 ({compressed_size + 4}) != entry length ({len(raw)})"
            )

        payload = raw[8 : 8 + (compressed_size - 4)]
        output, consumed = lzss_expand(payload, uncompressed_size)
        if consumed != len(payload):
            raise CamFormatError(
                f"{name}: LZSS consumed {consumed} bytes, expected {len(payload)}"
            )

        return DecodeResult(
            data=output,
            compressed=True,
            metadata={
                "compressed_size": compressed_size,
                "uncompressed_size": uncompressed_size,
            },
        )

    if ext in {".obd", ".uni"}:
        if len(raw) < 10:
            raise CamFormatError(f"{name}: too short for {ext} compression header")

        compressed_size = _read_u32_le(raw, 0)
        record_count = _read_u16_le(raw, 4)
        uncompressed_size = _read_u32_le(raw, 6)

        if compressed_size < 6:
            raise CamFormatError(f"{name}: invalid compressed size {compressed_size}")
        if compressed_size + 4 != len(raw):
            raise CamFormatError(
                f"{name}: compressed_size+4 ({compressed_size + 4}) != entry length ({len(raw)})"
            )

        payload = raw[10 : 10 + (compressed_size - 6)]
        output, consumed = lzss_expand(payload, uncompressed_size)
        if consumed != len(payload):
            raise CamFormatError(
                f"{name}: LZSS consumed {consumed} bytes, expected {len(payload)}"
            )

        return DecodeResult(
            data=output,
            compressed=True,
            metadata={
                "compressed_size": compressed_size,
                "uncompressed_size": uncompressed_size,
                "record_count": record_count,
            },
        )

    if ext == ".obj":
        if len(raw) < 10:
            raise CamFormatError(f"{name}: too short for .obj compression header")

        num_objectives = _read_u16_le(raw, 0)
        uncompressed_size = _read_u32_le(raw, 2)
        compressed_size = _read_u32_le(raw, 6)

        if 10 + compressed_size != len(raw):
            raise CamFormatError(
                f"{name}: 10+compressed_size ({10 + compressed_size}) != entry length ({len(raw)})"
            )

        payload = raw[10 : 10 + compressed_size]
        output, consumed = lzss_expand(payload, uncompressed_size)
        if consumed != len(payload):
            raise CamFormatError(
                f"{name}: LZSS consumed {consumed} bytes, expected {len(payload)}"
            )

        return DecodeResult(
            data=output,
            compressed=True,
            metadata={
                "compressed_size": compressed_size,
                "uncompressed_size": uncompressed_size,
                "num_objectives": num_objectives,
            },
        )

    return DecodeResult(data=raw, compressed=False, metadata={})


def _safe_output_path(base_dir: Path, entry_name: str) -> Path:
    """Build a traversal-safe destination path for extracted entries."""

    normalized = entry_name.replace("\\", "/")
    candidate = (base_dir / normalized).resolve()
    base_resolved = base_dir.resolve()

    if candidate == base_resolved:
        raise CamFormatError(f"invalid output entry name {entry_name!r}")

    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise CamFormatError(f"unsafe output entry name {entry_name!r}") from exc

    return candidate


def extract_container(
    input_path: Path,
    output_dir: Path,
    *,
    best_effort: bool,
    parse_data: bool,
    support_base_dir: Path | None = None,
) -> list[dict[str, object]]:
    """Decode and optionally parse every container entry to disk + manifest."""

    register_default_parsers()

    blob = input_path.read_bytes()
    entries = parse_container(blob)

    decoded_entries: list[DecodedEntry] = []
    for entry in entries:
        raw = blob[entry.offset : entry.offset + entry.length]
        try:
            decoded = _decode_compressed_entry(entry.name, raw)
        except (CamFormatError, LzssError):
            if not best_effort:
                raise
            decoded = DecodeResult(data=raw, compressed=False, metadata={})
        decoded_entries.append(DecodedEntry(entry=entry, raw=raw, decoded=decoded))

    container_version = _detect_container_version(decoded_entries)

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []

    for item in decoded_entries:
        entry = item.entry
        decoded = item.decoded

        output_path = _safe_output_path(output_dir, entry.name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(decoded.data)

        manifest_item: dict[str, object] = {
            "name": entry.name,
            "offset": entry.offset,
            "length": entry.length,
            "output_path": str(output_path),
            "output_size": len(decoded.data),
            "decompressed": decoded.compressed,
        }
        if decoded.metadata:
            manifest_item.update(decoded.metadata)

        if parse_data:
            try:
                parsed = _parse_entry_data(
                    entry.name,
                    decoded.data,
                    container_version=container_version,
                    decode_metadata=decoded.metadata if decoded.metadata else None,
                    support_base_dir=support_base_dir,
                )
                if parsed is not None:
                    parsed_path = output_path.with_name(output_path.name + ".parsed.json")
                    parsed_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
                    manifest_item["parsed"] = True
                    manifest_item["parsed_path"] = str(parsed_path)
            except Exception as exc:
                manifest_item["parsed"] = False
                manifest_item["parse_error"] = str(exc)

        manifest.append(manifest_item)

    return manifest


__all__ = [
    "CamEntry",
    "CamFormatError",
    "DecodeResult",
    "DecodedEntry",
    "parse_container",
    "_decode_compressed_entry",
    "_detect_container_version",
    "_safe_output_path",
    "extract_container",
]
