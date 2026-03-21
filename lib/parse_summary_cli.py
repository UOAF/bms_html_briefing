from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.cam.types import ParsedCmpData, ParsedUniData, SummaryInput
from lib.parsers.parse_cmp import parse_cmp
from lib.parsers.parse_l16 import load_parsed_l16_for_save
from lib.parsers.parse_summary import parse_summary
from lib.parsers.parse_twx import load_parsed_twx_for_cam_path, load_parsed_twx_for_save
from lib.parsers.parse_uni import parse_uni


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse Falcon/BMS campaign data and emit the final HTML brief summary JSON"
    )
    parser.add_argument("input_file", type=Path, help="Path to .cam/.trn/.tac file")
    parser.add_argument(
        "--bms-base-dir",
        type=Path,
        default=None,
        help="Optional BMS base directory (for Strings.txt, TWX, Link16, and objects_cf XML files)",
    )
    parser.add_argument(
        "--packages",
        type=int,
        nargs="+",
        default=None,
        help="Optional package numbers to include (default: player-linked packages or all detected)",
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
    from lib.cam.cam_content import extract_container, parse_cam_file

    parser = build_arg_parser()
    args = parser.parse_args()

    input_path: Path = args.input_file.resolve()
    if not input_path.is_file():
        parser.error(f"input file does not exist: {input_path}")

    support_base_dir = args.bms_base_dir.resolve() if isinstance(args.bms_base_dir, Path) else None

    if isinstance(args.extract_to, Path):
        manifest = extract_container(
            input_path,
            args.extract_to.resolve(),
            best_effort=bool(args.best_effort),
            parse_data=True,
            support_base_dir=support_base_dir,
        )
        manifest_path = args.extract_to.resolve() / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    parsed_cam = parse_cam_file(
        input_path,
        bms_base_dir=support_base_dir,
        parse_entries=False,
        best_effort=bool(args.best_effort),
    )
    cmp_entry = parsed_cam.get_entry_by_ext(".cmp")
    uni_entry = parsed_cam.get_entry_by_ext(".uni")

    twx_data = load_parsed_twx_for_cam_path(input_path)
    if not twx_data.current_date:
        twx_data = load_parsed_twx_for_save(
            bms_base_dir=support_base_dir,
            save_stem=input_path.stem,
        )
    l16_data = load_parsed_l16_for_save(
        bms_base_dir=support_base_dir,
        save_stem=input_path.stem,
    )

    summary_input = SummaryInput(
        source_path=input_path,
        support_base_dir=support_base_dir,
        container_version=parsed_cam.container_version,
        cmp=(
            parse_cmp(
                cmp_entry.data,
                container_version=parsed_cam.container_version,
                support_base_dir=support_base_dir,
                decode_metadata=cmp_entry.decode_metadata,
            )
            if cmp_entry is not None
            else ParsedCmpData.from_dict(None)
        ),
        uni=(
            parse_uni(
                uni_entry.data,
                container_version=parsed_cam.container_version,
                support_base_dir=support_base_dir,
                decode_metadata=uni_entry.decode_metadata,
            )
            if uni_entry is not None
            else ParsedUniData.from_dict(None)
        ),
        twx=twx_data,
        l16=l16_data,
    )
    summary = parse_summary(summary_input, package_numbers=args.packages)
    print(json.dumps(summary.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
