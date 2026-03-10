#!/usr/bin/env python3
"""Standalone CMP temporal probe for CAM/TRN/TAC saves.

This utility is intentionally separate from the main parser flow.
It decodes the `.cmp` entry and scans for plausible date/time encodings
without changing runtime APIs or JSON output schemas.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys
from typing import Any

# Allow running the script directly: `python examples/cmp_time_probe.py ...`
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.cam.cam_content import parse_cam_file
from lib.cam.cmp import _parse_cmp
from lib.cam.core import BinaryReader, ParseContext


def _cmp_known_prefix_size(data: bytes) -> int:
    """Replicate known CMP field skips to get the parsed-prefix boundary."""

    try:
        reader = BinaryReader(data)
        reader.read_u32()
        reader.read_u32()
        reader.read_u32()
        reader.read_i32()
        reader.read_i32()
        reader.read_i32()

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

        reader.read_u8()
        reader.read_i16()
        reader.read_i16()
        reader.read_bytes(40)
        reader.read_bytes(40)
        reader.read_bytes(40)
        reader.read_bytes(40)
        reader.read_u32()
        reader.read_u32()
        return reader.offset
    except Exception:
        return 0


def _scan_cmp_temporal_probe(
    data: bytes,
    *,
    parsed_prefix_size: int,
    sample_size: int,
) -> dict[str, Any]:
    def region_for_offset(offset: int) -> str:
        return "parsed_prefix" if offset < parsed_prefix_size else "tail"

    def compact(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "count": len(items),
            "samples": items[:sample_size],
        }

    unix_candidates: list[dict[str, Any]] = []
    ms_of_day_candidates: list[dict[str, Any]] = []
    minutes_of_day_candidates: list[dict[str, Any]] = []
    day_of_year_candidates: list[dict[str, Any]] = []
    date_triplet_candidates: list[dict[str, Any]] = []

    for offset in range(0, max(0, len(data) - 3), 4):
        value = struct.unpack_from("<I", data, offset)[0]
        region = region_for_offset(offset)

        if 946684800 <= value <= 4102444800:
            iso_utc: str | None
            try:
                iso_utc = datetime.fromtimestamp(value, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            except (OSError, OverflowError, ValueError):
                iso_utc = None
            unix_candidates.append(
                {
                    "offset": offset,
                    "value": value,
                    "iso_utc": iso_utc,
                    "region": region,
                }
            )

        if 0 <= value < 86_400_000:
            total_seconds, millis = divmod(value, 1000)
            hh = (total_seconds // 3600) % 24
            mm = (total_seconds % 3600) // 60
            ss = total_seconds % 60
            time_z = f"{hh:02}:{mm:02}:{ss:02}.{millis:03}z" if millis else f"{hh:02}:{mm:02}:{ss:02}z"
            ms_of_day_candidates.append(
                {
                    "offset": offset,
                    "value": value,
                    "time_z": time_z,
                    "region": region,
                }
            )

        if 0 <= value <= 1439:
            minutes_of_day_candidates.append(
                {
                    "offset": offset,
                    "value": value,
                    "hhmm": f"{value // 60:02}:{value % 60:02}",
                    "region": region,
                }
            )

        if 1 <= value <= 366:
            day_of_year_candidates.append(
                {
                    "offset": offset,
                    "value": value,
                    "region": region,
                }
            )

    seen_date_triplets: set[tuple[int, str, int, int, int]] = set()
    for offset in range(0, max(0, len(data) - 5), 2):
        a, b, c = struct.unpack_from("<HHH", data, offset)
        region = region_for_offset(offset)

        combos = (
            ("Y-M-D", a, b, c),
            ("D-M-Y", c, b, a),
            ("M-D-Y", c, a, b),
        )
        for order, year, month, day in combos:
            if not (1980 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
                continue
            key = (offset, order, year, month, day)
            if key in seen_date_triplets:
                continue
            seen_date_triplets.add(key)
            date_triplet_candidates.append(
                {
                    "offset": offset,
                    "order": order,
                    "year": year,
                    "month": month,
                    "day": day,
                    "region": region,
                }
            )

    return {
        "scan_size": len(data),
        "parsed_prefix_size": parsed_prefix_size,
        "u32_unix_seconds": compact(unix_candidates),
        "u32_ms_of_day": compact(ms_of_day_candidates),
        "u32_minutes_of_day": compact(minutes_of_day_candidates),
        "u32_day_of_year": compact(day_of_year_candidates),
        "u16_date_triplets": compact(date_triplet_candidates),
    }


def _load_cmp_entry(cam_path: Path) -> tuple[bytes, str, int | None, dict[str, Any]]:
    parsed = parse_cam_file(cam_path, parse_entries=False, best_effort=True)
    cmp_entries = [entry for entry in parsed.entries if Path(entry.name).suffix.lower() == ".cmp"]
    if not cmp_entries:
        raise RuntimeError("No decoded .cmp entry found in container")

    cmp_entry = cmp_entries[0]
    cmp_ctx = ParseContext(
        container_version=parsed.container_version,
        decode_metadata=cmp_entry.decode_metadata or None,
        support_base_dir=parsed.bms_base_dir,
    )
    known_cmp = _parse_cmp(cmp_entry.data, cmp_ctx)
    return cmp_entry.data, cmp_entry.name, parsed.container_version, known_cmp


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Standalone heuristic probe for campaign date/time fields in CMP."
    )
    parser.add_argument("input_file", type=Path, help="Path to .cam/.trn/.tac file")
    parser.add_argument(
        "--samples",
        type=int,
        default=24,
        help="Max sample items per candidate category (default: 24)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional output path for JSON probe results",
    )
    args = parser.parse_args()

    source = args.input_file.resolve()
    if not source.is_file():
        raise SystemExit(f"Input file does not exist: {source}")

    cmp_blob, cmp_name, container_version, known_cmp = _load_cmp_entry(source)
    prefix_size = _cmp_known_prefix_size(cmp_blob)

    probe = _scan_cmp_temporal_probe(
        cmp_blob,
        parsed_prefix_size=prefix_size,
        sample_size=max(1, int(args.samples)),
    )

    report = {
        "source_path": str(source),
        "cmp_entry_name": cmp_name,
        "container_version": container_version,
        "known_cmp": {
            "current_time": known_cmp.get("current_time"),
            "current_time_z": known_cmp.get("current_time_z"),
            "te_start_time": known_cmp.get("te_start_time"),
            "te_time_limit": known_cmp.get("te_time_limit"),
            "theater_name": known_cmp.get("theater_name"),
            "scenario": known_cmp.get("scenario"),
            "save_file": known_cmp.get("save_file"),
            "ui_name": known_cmp.get("ui_name"),
            "undocumented_tail_size": known_cmp.get("undocumented_tail_size"),
        },
        "probe": probe,
    }

    output = json.dumps(report, indent=2)
    if args.out is not None:
        args.out.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
