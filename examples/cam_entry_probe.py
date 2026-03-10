#!/usr/bin/env python3
"""Standalone CAM entry probe (container directory + token scan).

This script is isolated from runtime parser integration so it can be removed
without touching application code.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lib.cam.cam_content import parse_cam_file
from lib.cam.container import parse_container


def _scan_tokens(blob: bytes, tokens: list[bytes]) -> dict[str, int]:
    lower = blob.lower()
    return {token.decode("ascii", errors="ignore"): lower.count(token) for token in tokens}


def _probe_file(path: Path, tokens: list[bytes]) -> dict[str, Any]:
    blob = path.read_bytes()
    directory_offset = struct.unpack_from("<I", blob, 0)[0] if len(blob) >= 4 else None
    parsed_entries = parse_container(blob)
    parsed_cam = parse_cam_file(path, parse_entries=False, best_effort=True)

    entries: list[dict[str, Any]] = []
    for entry in parsed_cam.entries:
        token_counts = _scan_tokens(entry.data, tokens)
        entries.append(
            {
                "name": entry.name,
                "decoded_size": entry.decoded_size,
                "compressed": entry.compressed,
                "token_counts": token_counts,
            }
        )

    return {
        "source_path": str(path),
        "file_size": len(blob),
        "container_directory_offset": directory_offset,
        "container_entry_count": len(parsed_entries),
        "entry_names": [entry.name for entry in parsed_entries],
        "raw_token_counts": _scan_tokens(blob, tokens),
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe CAM/TRN/TAC container entries and token presence.")
    parser.add_argument("input_files", nargs="+", type=Path, help="One or more .cam/.trn/.tac files")
    parser.add_argument(
        "--tokens",
        type=str,
        default=".wth,wth,weather,.tea",
        help="Comma-separated ASCII tokens to search in raw and decoded payloads",
    )
    parser.add_argument("--out", type=Path, default=None, help="Optional JSON output file")
    args = parser.parse_args()

    tokens = [part.strip().lower().encode("ascii", errors="ignore") for part in args.tokens.split(",")]
    tokens = [token for token in tokens if token]
    if not tokens:
        raise SystemExit("No valid tokens provided")

    results: list[dict[str, Any]] = []
    for file_path in args.input_files:
        path = file_path.resolve()
        if not path.is_file():
            raise SystemExit(f"Input file does not exist: {path}")
        results.append(_probe_file(path, tokens))

    output = json.dumps({"files": results}, indent=2)
    if args.out is not None:
        args.out.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
