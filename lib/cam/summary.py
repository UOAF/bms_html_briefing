"""Campaign summary API and CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .lzss import LzssError

from .container import _decode_compressed_entry, extract_container, parse_container
from .core import (
    CamFormatError,
    DecodeResult,
    DecodedEntry,
    ParseError,
    _detect_container_version,
    _find_support_file,
    _format_campaign_time_z,
    _load_strings_by_id,
    _parse_entry_data,
    _to_vuid_tuple,
    register_default_parsers,
)
from .uni import _collect_package_numbers, _record_index_by_id, list_package_generated_flights


def _load_strings(support_base_dir: Path | None) -> dict[int, str]:
    strings_path = _find_support_file("Strings.txt", support_base_dir=support_base_dir)
    if strings_path is None:
        strings_path = _find_support_file("strings.txt", support_base_dir=support_base_dir)
    if strings_path is None:
        return {}
    return _load_strings_by_id(strings_path)


def _callsign_root_from_idx(
    callsign_idx: int | None,
    strings_by_id: dict[int, str],
) -> str | None:
    if not isinstance(callsign_idx, int):
        return None
    root = strings_by_id.get(2000 + callsign_idx)
    if isinstance(root, str) and root.strip():
        return root.strip()
    root = strings_by_id.get(callsign_idx)
    if isinstance(root, str) and root.strip():
        return root.strip()
    return None


def _resolve_callsign(
    generated_flight: dict[str, Any],
    *,
    strings_by_id: dict[int, str],
    callsign_by_idx: dict[int, str],
    callsign_num_by_idx: dict[int, int],
) -> str | None:
    squadron_callsign = generated_flight.get("squadron_callsign")
    if isinstance(squadron_callsign, dict):
        value = squadron_callsign.get("callsign")
        if isinstance(value, str) and value.strip():
            return value.strip()

    callsign_profile = generated_flight.get("callsign_profile")
    callsign_idx: int | None = None
    if isinstance(callsign_profile, dict):
        value = callsign_profile.get("callsign_idx")
        if isinstance(value, int):
            callsign_idx = value

    root: str | None = None
    if isinstance(squadron_callsign, dict):
        callsign_root = squadron_callsign.get("callsign_root")
        if isinstance(callsign_root, str) and callsign_root.strip():
            root = callsign_root.strip()
        strings_id = squadron_callsign.get("strings_id")
        if not root and isinstance(strings_id, int):
            mapped = strings_by_id.get(strings_id)
            if isinstance(mapped, str) and mapped.strip():
                root = mapped.strip()
    if not root and callsign_idx is not None:
        root = callsign_by_idx.get(callsign_idx)
    if not root and callsign_idx is not None:
        root = _callsign_root_from_idx(callsign_idx, strings_by_id)

    if not root:
        return None

    callsign_num: int | None = None
    if isinstance(squadron_callsign, dict):
        value = squadron_callsign.get("callsign_num")
        if isinstance(value, int):
            callsign_num = value

    if (callsign_num is None or not (1 <= callsign_num <= 9)) and callsign_idx is not None:
        idx_num = callsign_num_by_idx.get(callsign_idx)
        if isinstance(idx_num, int):
            callsign_num = idx_num

    if callsign_num is None or not (1 <= callsign_num <= 9):
        air_task_number = generated_flight.get("air_task_number")
        if isinstance(air_task_number, int):
            candidate = air_task_number % 10
            if 1 <= candidate <= 9:
                callsign_num = candidate

    if callsign_num is None or not (1 <= callsign_num <= 9):
        slot_index = generated_flight.get("slot_index")
        if isinstance(slot_index, int):
            candidate = slot_index + 1
            if 1 <= candidate <= 9:
                callsign_num = candidate

    if isinstance(callsign_num, int) and 1 <= callsign_num <= 9:
        return f"{root}{callsign_num}"
    return root


def _merge_flight_timing(
    *,
    base_timing: Any,
    flight_mission: Any,
    package_timing: Any,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if isinstance(base_timing, dict):
        merged.update(base_timing)
    if not isinstance(flight_mission, dict):
        flight_mission = {}
    if not isinstance(package_timing, dict):
        package_timing = {}

    for stem in ("takeoff_time", "push_time", "time_on_target"):
        ms_key = f"{stem}_ms"
        z_key = f"{stem}_z"
        if merged.get(ms_key) is None:
            mission_val = flight_mission.get(ms_key)
            merged[ms_key] = mission_val if isinstance(mission_val, int) else package_timing.get(ms_key)
        if not merged.get(z_key):
            mission_val = flight_mission.get(z_key)
            merged[z_key] = mission_val if isinstance(mission_val, str) else package_timing.get(z_key)
    return merged


def _build_summary_from_parsed(
    *,
    source_path: Path,
    container_version: int | None,
    cmp_parsed: dict[str, Any],
    uni_parsed: dict[str, Any],
    support_base_dir: Path | None,
    package_numbers: list[int] | None = None,
) -> dict[str, Any]:
    selected_numbers = package_numbers or _collect_package_numbers(uni_parsed)
    generated = list_package_generated_flights(uni_parsed, selected_numbers)

    strings_by_id = _load_strings(support_base_dir)
    bullseye_name_id = cmp_parsed.get("bullseye_name_id")
    bullseye_name = (
        strings_by_id.get(bullseye_name_id)
        if isinstance(bullseye_name_id, int)
        else None
    )

    record_by_id = _record_index_by_id(uni_parsed)
    package_by_id: dict[tuple[int, int], dict[str, Any]] = {}
    uni_packages = uni_parsed.get("packages")
    if isinstance(uni_packages, list):
        for uni_package in uni_packages:
            if not isinstance(uni_package, dict):
                continue
            uni_package_id = _to_vuid_tuple(uni_package.get("id"))
            if uni_package_id is None:
                continue
            package_by_id[uni_package_id] = uni_package

    packages: list[dict[str, Any]] = []
    for query in generated:
        matches = query.get("matches")
        if not isinstance(matches, list):
            continue
        for match in matches:
            if not isinstance(match, dict):
                continue

            package_id = _to_vuid_tuple(match.get("package_id"))
            package_record = record_by_id.get(package_id) if package_id is not None else None
            package_link = package_by_id.get(package_id) if package_id is not None else None
            callsign_by_idx: dict[int, str] = {}
            callsign_num_by_idx: dict[int, int] = {}
            if isinstance(package_link, dict):
                unit_refs = package_link.get("unit_refs")
                if isinstance(unit_refs, list):
                    for ref in unit_refs:
                        if not isinstance(ref, dict) or ref.get("kind") != "squadron":
                            continue
                        ref_id = _to_vuid_tuple(ref.get("id"))
                        if ref_id is None:
                            continue
                        squadron_record = record_by_id.get(ref_id)
                        if not isinstance(squadron_record, dict):
                            continue
                        profile = squadron_record.get("callsign_profile")
                        if not isinstance(profile, dict):
                            continue
                        callsign_idx = profile.get("callsign_idx")
                        if not isinstance(callsign_idx, int):
                            continue
                        squad_callsign = squadron_record.get("squadron_callsign")
                        if isinstance(squad_callsign, dict):
                            root: str | None = None
                            callsign_root = squad_callsign.get("callsign_root")
                            if isinstance(callsign_root, str) and callsign_root.strip():
                                root = callsign_root.strip()
                            callsign = squad_callsign.get("callsign")
                            if not root and isinstance(callsign, str) and callsign.strip():
                                root = callsign.strip().rstrip("123456789")
                            strings_id = squad_callsign.get("strings_id")
                            if not root and isinstance(strings_id, int):
                                mapped = strings_by_id.get(strings_id)
                                if isinstance(mapped, str) and mapped.strip():
                                    root = mapped.strip()
                            if root:
                                callsign_by_idx[callsign_idx] = root
                            callsign_num = squad_callsign.get("callsign_num")
                            if isinstance(callsign_num, int):
                                callsign_num_by_idx[callsign_idx] = callsign_num

            flights: list[dict[str, Any]] = []
            generated_flights = match.get("generated_flights")
            if isinstance(generated_flights, list):
                for generated_flight in generated_flights:
                    if not isinstance(generated_flight, dict):
                        continue
                    unit_id = _to_vuid_tuple(generated_flight.get("unit_id"))
                    if unit_id is None:
                        continue
                    unit_record = record_by_id.get(unit_id)

                    callsign = _resolve_callsign(
                        generated_flight,
                        strings_by_id=strings_by_id,
                        callsign_by_idx=callsign_by_idx,
                        callsign_num_by_idx=callsign_num_by_idx,
                    )

                    callsign_profile = generated_flight.get("callsign_profile")
                    aircraft = None
                    if isinstance(callsign_profile, dict):
                        value = callsign_profile.get("vehicle_name")
                        if isinstance(value, str):
                            aircraft = value

                    tasking = generated_flight.get("flight_mission")
                    if not isinstance(tasking, dict):
                        # Squadron mission is used as fallback when flight mission is absent.
                        tasking = generated_flight.get("squadron_mission")
                    timing = _merge_flight_timing(
                        base_timing=generated_flight.get("timing"),
                        flight_mission=generated_flight.get("flight_mission"),
                        package_timing=match.get("timing"),
                    )

                    steerpoints: list[dict[str, Any]] = []
                    if isinstance(unit_record, dict):
                        waypoints = unit_record.get("waypoints")
                        if isinstance(waypoints, list):
                            steerpoints = waypoints

                    flights.append(
                        {
                            "unit_id": {"num": unit_id[0], "creator": unit_id[1]},
                            "unit_kind": generated_flight.get("unit_kind"),
                            "flight_number": generated_flight.get("air_task_number"),
                            "callsign": callsign,
                            "aircraft": aircraft,
                            "aircraft_count": generated_flight.get("aircraft_count"),
                            "tasking": tasking,
                            "timing": timing,
                            "steerpoints": steerpoints,
                        }
                    )

            package_steerpoints: list[dict[str, Any]] = []
            if isinstance(package_record, dict):
                waypoints = package_record.get("waypoints")
                if isinstance(waypoints, list):
                    package_steerpoints = waypoints

            packages.append(
                {
                    "package_id": match.get("package_id"),
                    "package_number": match.get("package_number"),
                    "tasking": match.get("package_mission"),
                    "timing": match.get("timing"),
                    "steerpoints": package_steerpoints,
                    "flights": flights,
                    "notes": match.get("notes", []),
                }
            )

    current_time_ms = cmp_parsed.get("current_time")
    current_time_z = cmp_parsed.get("current_time_z")
    if not isinstance(current_time_z, str):
        current_time_z = _format_campaign_time_z(
            current_time_ms if isinstance(current_time_ms, int) else None
        )

    warnings: list[str] = []
    uni_warnings = uni_parsed.get("warnings")
    if isinstance(uni_warnings, list):
        warnings.extend(str(item) for item in uni_warnings)

    return {
        "source_path": str(source_path),
        "container_version": container_version,
        "current_time_ms": current_time_ms if isinstance(current_time_ms, int) else None,
        "current_time_z": current_time_z,
        "bullseye": {
            "x": cmp_parsed.get("bullseye_x")
            if isinstance(cmp_parsed.get("bullseye_x"), int)
            else None,
            "y": cmp_parsed.get("bullseye_y")
            if isinstance(cmp_parsed.get("bullseye_y"), int)
            else None,
            "name_id": bullseye_name_id if isinstance(bullseye_name_id, int) else None,
            "name": bullseye_name,
        },
        "package_count": len(packages),
        "packages": packages,
        "warnings": warnings,
    }


def parse_cam_summary(
    input_path: str | Path | None = None,
    *,
    bms_base_dir: str | Path | None = None,
    package_numbers: list[int] | None = None,
    best_effort: bool = False,
    cmp_parsed: dict[str, Any] | None = None,
    uni_parsed: dict[str, Any] | None = None,
    container_version: int | None = None,
) -> dict[str, Any]:
    """High-level API: parse CAM and return package/time/bullseye summary."""

    register_default_parsers()

    support_base_dir = Path(bms_base_dir).resolve() if bms_base_dir is not None else None

    has_preparsed = cmp_parsed is not None or uni_parsed is not None
    if has_preparsed:
        if input_path is None:
            raise ValueError("input_path is required when passing pre-parsed cmp/uni dictionaries")
        source_path = Path(input_path).resolve()
        if not isinstance(cmp_parsed, dict):
            raise ParseError("CAM file does not contain a parseable .cmp entry")
        if not isinstance(uni_parsed, dict):
            raise ParseError("CAM file does not contain a parseable .uni entry")
    else:
        if input_path is None:
            raise ValueError("input_path is required when cmp_parsed/uni_parsed are not provided")
        source_path = Path(input_path).resolve()
        blob = source_path.read_bytes()
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

        parsed_by_ext: dict[str, dict[str, Any]] = {}
        for item in decoded_entries:
            name = item.entry.name
            parsed = _parse_entry_data(
                name,
                item.decoded.data,
                container_version=container_version,
                decode_metadata=item.decoded.metadata if item.decoded.metadata else None,
                support_base_dir=support_base_dir,
            )
            if parsed is None:
                continue
            ext = Path(name).suffix.lower()
            if ext and ext not in parsed_by_ext:
                parsed_by_ext[ext] = parsed

        cmp_parsed = parsed_by_ext.get(".cmp")
        if not isinstance(cmp_parsed, dict):
            raise ParseError("CAM file does not contain a parseable .cmp entry")

        uni_parsed = parsed_by_ext.get(".uni")
        if not isinstance(uni_parsed, dict):
            raise ParseError("CAM file does not contain a parseable .uni entry")

    return _build_summary_from_parsed(
        source_path=source_path,
        container_version=container_version,
        cmp_parsed=cmp_parsed,
        uni_parsed=uni_parsed,
        support_base_dir=support_base_dir,
        package_numbers=package_numbers,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser for quick summary/extraction workflows."""

    parser = argparse.ArgumentParser(
        description="Parse Falcon/BMS CAM/TRN/TAC files for package-focused campaign data"
    )
    parser.add_argument("input_file", type=Path, help="Path to .cam/.trn/.tac file")
    parser.add_argument(
        "--bms-base-dir",
        type=Path,
        default=None,
        help="Optional BMS base directory (for Strings.txt and objects_cf XML files)",
    )
    parser.add_argument(
        "--packages",
        type=int,
        nargs="+",
        default=None,
        help="Optional package numbers to include (default: all detected)",
    )
    parser.add_argument(
        "--best-effort",
        action="store_true",
        help="Keep raw entry payload when decompression fails",
    )
    parser.add_argument(
        "--extract-to",
        type=Path,
        default=None,
        help="Optional output directory to write decoded entries and parsed sidecar JSON",
    )
    return parser


def main() -> int:
    """CLI entry point."""

    parser = build_arg_parser()
    args = parser.parse_args()

    input_path: Path = args.input_file
    if not input_path.is_file():
        parser.error(f"input file does not exist: {input_path}")

    support_base_dir = (
        args.bms_base_dir.resolve() if isinstance(args.bms_base_dir, Path) else None
    )

    if isinstance(args.extract_to, Path):
        manifest = extract_container(
            input_path.resolve(),
            args.extract_to.resolve(),
            best_effort=bool(args.best_effort),
            parse_data=True,
            support_base_dir=support_base_dir,
        )
        manifest_path = args.extract_to.resolve() / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    summary = parse_cam_summary(
        input_path,
        bms_base_dir=support_base_dir,
        package_numbers=args.packages,
        best_effort=bool(args.best_effort),
    )
    print(json.dumps(summary, indent=2))
    return 0


__all__ = [
    "parse_cam_summary",
    "build_arg_parser",
    "main",
]
