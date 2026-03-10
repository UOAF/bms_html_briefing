#!/usr/bin/env python3
"""Compatibility wrapper exposing CAM parser APIs from a flat package layout."""

from .cmp import _parse_cmp
from .container import (
    CamEntry,
    CamFormatError,
    DecodeResult,
    DecodedEntry,
    _decode_compressed_entry,
    _detect_container_version,
    _safe_output_path,
    extract_container,
    parse_container,
)
from .core import (
    BinaryReader,
    ParseContext,
    ParseError,
    _find_support_file,
    _load_strings_by_id,
    _parse_entry_data,
    register_default_parsers,
    register_entry_parser,
)
from .lzss import LzssError
from .summary import build_arg_parser, main, parse_cam_summary
from .uni import (
    _collect_package_numbers,
    _parse_uni,
    list_package_flight_callsigns,
    list_package_generated_flights,
)

register_default_parsers()

__all__ = [
    "CamFormatError",
    "ParseError",
    "LzssError",
    "CamEntry",
    "DecodeResult",
    "DecodedEntry",
    "ParseContext",
    "BinaryReader",
    "parse_container",
    "_decode_compressed_entry",
    "_detect_container_version",
    "_safe_output_path",
    "extract_container",
    "register_entry_parser",
    "_parse_entry_data",
    "_parse_cmp",
    "_parse_uni",
    "_collect_package_numbers",
    "list_package_generated_flights",
    "list_package_flight_callsigns",
    "_find_support_file",
    "_load_strings_by_id",
    "parse_cam_summary",
    "build_arg_parser",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
