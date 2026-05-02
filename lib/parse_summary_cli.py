from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.cam.opencam.cam_container import CamContainer
from lib.cam.extract import extract_cam_brief_data


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse Falcon/BMS campaign data and emit the final HTML brief summary JSON"
    )
    parser.add_argument("input_file", type=Path, help="Path to .cam/.trn/.tac file")
    parser.add_argument(
        "--bms-base-dir",
        type=Path,
        default=None,
        help="Optional BMS base directory for support files, TWX, and Link16",
    )
    parser.add_argument(
        "--theater-target-folder",
        type=Path,
        default=None,
        help="Optional theater target folder used to infer support files",
    )
    parser.add_argument(
        "--theater-name",
        type=str,
        default=None,
        help="Optional runtime theater name",
    )
    parser.add_argument(
        "--packages",
        type=int,
        nargs="+",
        default=None,
        help="Optional package numbers to include (default: all detected packages)",
    )
    parser.add_argument(
        "--best-effort",
        action="store_true",
        help="Accepted for CLI compatibility; opencam parsing does not fall back to old parser behavior",
    )
    parser.add_argument(
        "--extract-to",
        type=Path,
        default=None,
        help="Optional output directory to write decoded entries and manifest JSON",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    input_path: Path = args.input_file.resolve()
    if not input_path.is_file():
        parser.error(f"input file does not exist: {input_path}")

    if isinstance(args.extract_to, Path):
        manifest = extract_container(input_path, args.extract_to.resolve())
        manifest_path = args.extract_to.resolve() / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    summary = extract_cam_brief_data(
        input_path,
        bms_base_dir=args.bms_base_dir,
        theater_target_folder=args.theater_target_folder,
        theater_name=args.theater_name,
        save_stem=input_path.stem,
    )
    if args.packages:
        wanted = set(args.packages)
        packages = [
            package
            for package in summary.get("packages", [])
            if isinstance(package, dict) and package.get("package_number") in wanted
        ]
        summary["packages"] = packages
        summary["package_count"] = len(packages)

    print(json.dumps(summary, indent=2))
    return 0


def extract_container(input_path: Path, output_dir: Path) -> list[dict[str, object]]:
    container = CamContainer.from_path(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, object]] = []
    for entry in container.entries:
        output_path = _safe_output_path(output_dir, entry.name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(entry.decoded)
        item: dict[str, object] = {
            "name": entry.name,
            "offset": entry.offset,
            "length": entry.length,
            "output_path": str(output_path),
            "output_size": len(entry.decoded),
            "decompressed": entry.is_compressed,
        }
        item.update(entry.metadata)
        manifest.append(item)
    return manifest


def _safe_output_path(base_dir: Path, entry_name: str) -> Path:
    normalized = entry_name.replace("\\", "/")
    candidate = (base_dir / normalized).resolve()
    base_resolved = base_dir.resolve()
    if candidate == base_resolved:
        raise ValueError(f"invalid output entry name {entry_name!r}")
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(f"unsafe output entry name {entry_name!r}") from exc
    return candidate


if __name__ == "__main__":
    raise SystemExit(main())
