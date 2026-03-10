"""In-memory CAM parser library."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from . import cam_parser

logger = logging.getLogger("html_brief_log")


@dataclass(frozen=True)
class CamEntryData:
    name: str
    offset: int
    length: int
    decoded_size: int
    compressed: bool
    decode_metadata: dict[str, int]
    data: bytes
    parsed: dict[str, Any] | None


@dataclass(frozen=True)
class ParsedCamData:
    source_path: Path
    bms_base_dir: Path | None
    container_version: int | None
    entries: list[CamEntryData]
    parsed_by_name: dict[str, dict[str, Any]]
    parsed_by_ext: dict[str, dict[str, Any]]

    def get_parsed(self, name: str) -> dict[str, Any] | None:
        return self.parsed_by_name.get(name)

    def get_parsed_by_ext(self, ext: str) -> dict[str, Any] | None:
        normalized = ext if ext.startswith(".") else f".{ext}"
        return self.parsed_by_ext.get(normalized.lower())


def parse_cam_file(
    input_path: str | Path,
    *,
    bms_base_dir: str | Path | None = None,
    parse_entries: bool = True,
    best_effort: bool = False,
) -> ParsedCamData:
    source_path = Path(input_path).resolve()
    support_base_dir = Path(bms_base_dir).resolve() if bms_base_dir is not None else None
    logger.debug(
        "parse_cam_file start: input=%s support_base_dir=%s parse_entries=%s best_effort=%s",
        source_path,
        support_base_dir,
        parse_entries,
        best_effort,
    )

    blob = source_path.read_bytes()
    entries = cam_parser.parse_container(blob)
    logger.debug("CAM container parsed: entries=%d", len(entries))

    decoded_entries: list[cam_parser.DecodedEntry] = []
    for entry in entries:
        raw = blob[entry.offset : entry.offset + entry.length]
        try:
            decoded = cam_parser._decode_compressed_entry(entry.name, raw)
        except (cam_parser.CamFormatError, cam_parser.LzssError) as exc:
            if not best_effort:
                raise
            logger.warning(
                "CAM decode failed for entry %s; using raw payload due to best_effort: %s",
                entry.name,
                exc,
            )
            decoded = cam_parser.DecodeResult(data=raw, compressed=False, metadata={})
        decoded_entries.append(
            cam_parser.DecodedEntry(entry=entry, raw=raw, decoded=decoded)
        )

    container_version = cam_parser._detect_container_version(decoded_entries)
    logger.debug("CAM container version detected: %s", container_version)

    out_entries: list[CamEntryData] = []
    parsed_by_name: dict[str, dict[str, Any]] = {}
    parsed_by_ext: dict[str, dict[str, Any]] = {}

    for decoded_item in decoded_entries:
        entry = decoded_item.entry
        decoded = decoded_item.decoded

        parsed: dict[str, Any] | None = None
        if parse_entries:
            parsed = cam_parser._parse_entry_data(
                entry.name,
                decoded.data,
                container_version=container_version,
                decode_metadata=decoded.metadata if decoded.metadata else None,
                support_base_dir=support_base_dir,
            )
            if parsed is not None:
                parsed_by_name[entry.name] = parsed
                ext = Path(entry.name).suffix.lower()
                if ext and ext not in parsed_by_ext:
                    parsed_by_ext[ext] = parsed

        out_entries.append(
            CamEntryData(
                name=entry.name,
                offset=entry.offset,
                length=entry.length,
                decoded_size=len(decoded.data),
                compressed=decoded.compressed,
                decode_metadata=dict(decoded.metadata),
                data=decoded.data,
                parsed=parsed,
            )
        )

    return ParsedCamData(
        source_path=source_path,
        bms_base_dir=support_base_dir,
        container_version=container_version,
        entries=out_entries,
        parsed_by_name=parsed_by_name,
        parsed_by_ext=parsed_by_ext,
    )
