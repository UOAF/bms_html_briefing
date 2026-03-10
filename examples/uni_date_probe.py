#!/usr/bin/env python3
"""Standalone UNI date probe for CAM/TRN/TAC saves.

This utility is intentionally separate from runtime parser code.
It scans the decoded `.uni` blob for date-like encodings, with optional
target-date matching (for example: 2025-10-07).
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import struct
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.cam.cam_content import parse_cam_file


EPOCHS: list[tuple[str, date]] = [
    ("unix_1970", date(1970, 1, 1)),
    ("epoch_1900_01_01", date(1900, 1, 1)),
    ("epoch_1899_12_30", date(1899, 12, 30)),
]


def _find_uni_blob(input_path: Path) -> tuple[bytes, str, int | None]:
    parsed = parse_cam_file(input_path, parse_entries=False, best_effort=True)
    uni_entries = [entry for entry in parsed.entries if Path(entry.name).suffix.lower() == ".uni"]
    if not uni_entries:
        raise RuntimeError("No decoded .uni entry found in container")
    uni = uni_entries[0]
    return uni.data, uni.name, parsed.container_version


def _scan_day_count_candidates(
    blob: bytes,
    *,
    stride: int,
    min_year: int,
    max_year: int,
) -> dict[str, dict[str, list[int]]]:
    by_epoch: dict[str, dict[str, list[int]]] = {name: {} for name, _ in EPOCHS}
    max_offset = max(0, len(blob) - 3)
    for offset in range(0, max_offset, stride):
        value = struct.unpack_from("<I", blob, offset)[0]
        for epoch_name, epoch_start in EPOCHS:
            try:
                candidate = epoch_start + timedelta(days=value)
            except OverflowError:
                continue
            if not (min_year <= candidate.year <= max_year):
                continue
            key = candidate.isoformat()
            by_epoch[epoch_name].setdefault(key, []).append(offset)
    return by_epoch


def _top_dates(candidates: dict[str, list[int]], limit: int) -> list[dict[str, Any]]:
    ranked = sorted(candidates.items(), key=lambda item: len(item[1]), reverse=True)
    out: list[dict[str, Any]] = []
    for date_text, offsets in ranked[:limit]:
        out.append(
            {
                "date": date_text,
                "count": len(offsets),
                "sample_offsets": offsets[:24],
            }
        )
    return out


def _scan_target_day_counts(blob: bytes, target: date, stride: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for epoch_name, epoch_start in EPOCHS:
        expected = (target - epoch_start).days
        offsets: list[int] = []
        for offset in range(0, max(0, len(blob) - 3), stride):
            value = struct.unpack_from("<I", blob, offset)[0]
            if value == expected:
                offsets.append(offset)
        out.append(
            {
                "epoch": epoch_name,
                "expected_day_count": expected,
                "hit_count": len(offsets),
                "sample_offsets": offsets[:64],
            }
        )
    return out


def _scan_target_unix_seconds(blob: bytes, target: date, stride: int) -> dict[str, Any]:
    start = int(datetime(target.year, target.month, target.day, tzinfo=timezone.utc).timestamp())
    end = start + 86400 - 1
    offsets: list[dict[str, Any]] = []
    for offset in range(0, max(0, len(blob) - 3), stride):
        value = struct.unpack_from("<I", blob, offset)[0]
        if start <= value <= end:
            iso = datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            offsets.append({"offset": offset, "value": value, "iso_utc": iso})
    return {
        "start_unix_utc": start,
        "end_unix_utc": end,
        "hit_count": len(offsets),
        "sample_hits": offsets[:64],
    }


def _scan_target_triplets_u16(blob: bytes, target: date) -> list[dict[str, Any]]:
    y = target.year
    m = target.month
    d = target.day
    patterns = [
        ("Y-M-D", struct.pack("<HHH", y, m, d)),
        ("D-M-Y", struct.pack("<HHH", d, m, y)),
        ("M-D-Y", struct.pack("<HHH", m, d, y)),
    ]
    out: list[dict[str, Any]] = []
    for order, pattern in patterns:
        offsets: list[int] = []
        start = 0
        while True:
            index = blob.find(pattern, start)
            if index < 0:
                break
            offsets.append(index)
            start = index + 1
        out.append({"order": order, "hit_count": len(offsets), "sample_offsets": offsets[:64]})
    return out


def _scan_target_year_month_day_u16(blob: bytes, target: date, stride: int) -> dict[str, Any]:
    year_hits: list[int] = []
    month_hits: list[int] = []
    day_hits: list[int] = []
    for offset in range(0, max(0, len(blob) - 1), stride):
        value = struct.unpack_from("<H", blob, offset)[0]
        if value == target.year:
            year_hits.append(offset)
        if value == target.month:
            month_hits.append(offset)
        if value == target.day:
            day_hits.append(offset)
    return {
        "year_u16_hits": len(year_hits),
        "year_sample_offsets": year_hits[:64],
        "month_u16_hits": len(month_hits),
        "month_sample_offsets": month_hits[:64],
        "day_u16_hits": len(day_hits),
        "day_sample_offsets": day_hits[:64],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Standalone probe for date fields in decoded .uni payload."
    )
    parser.add_argument("input_file", type=Path, help="Path to .cam/.trn/.tac file")
    parser.add_argument(
        "--target-date",
        type=str,
        default=None,
        help="Optional ISO date to match exactly (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=1,
        help="Scan step in bytes (default: 1, use 4 for aligned-only fast scan)",
    )
    parser.add_argument(
        "--min-year",
        type=int,
        default=2000,
        help="Minimum year for generic day-count candidates (default: 2000)",
    )
    parser.add_argument(
        "--max-year",
        type=int,
        default=2100,
        help="Maximum year for generic day-count candidates (default: 2100)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Top date frequencies per epoch (default: 20)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional output file path for JSON result",
    )
    args = parser.parse_args()

    source = args.input_file.resolve()
    if not source.is_file():
        raise SystemExit(f"Input file does not exist: {source}")

    stride = max(1, int(args.stride))
    top_n = max(1, int(args.top))

    uni_blob, uni_name, container_version = _find_uni_blob(source)
    generic_candidates = _scan_day_count_candidates(
        uni_blob,
        stride=stride,
        min_year=int(args.min_year),
        max_year=int(args.max_year),
    )

    report: dict[str, Any] = {
        "source_path": str(source),
        "uni_entry_name": uni_name,
        "container_version": container_version,
        "uni_size": len(uni_blob),
        "scan_stride": stride,
        "generic_day_count_candidates": {
            epoch: _top_dates(cands, top_n) for epoch, cands in generic_candidates.items()
        },
    }

    if args.target_date:
        try:
            target = datetime.strptime(args.target_date.strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise SystemExit(f"Invalid --target-date, expected YYYY-MM-DD: {exc}") from exc
        report["target_date"] = target.isoformat()
        report["target_matches"] = {
            "u32_day_counts": _scan_target_day_counts(uni_blob, target, stride),
            "u32_unix_seconds_in_day": _scan_target_unix_seconds(uni_blob, target, stride),
            "u16_triplets": _scan_target_triplets_u16(uni_blob, target),
            "u16_year_month_day": _scan_target_year_month_day_u16(uni_blob, target, stride),
        }

    output = json.dumps(report, indent=2)
    if args.out is not None:
        args.out.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
