from __future__ import annotations

import logging
from pathlib import Path

from lib.theater_paths import resolve_theater_data_root
from lib.cam.brief_data import build_cam_brief_data
from lib.cam.types import ParsedCmpData, ParsedL16Data, ParsedTwxData, SummaryOutput, Vuid
from lib.parsers.parse_l16 import load_parsed_l16_for_save
from lib.parsers.parse_twx import load_parsed_twx_for_cam_path, load_parsed_twx_for_save

from .opencam.cam_container import CamContainer, DecodedEntry
from .opencam.cmp_parser import parse_cmp_record
from .opencam.cmp_wrappers import wrap_campaign
from .opencam.support_files import (
    BmsSupportError,
    BmsSupportPaths,
    detect_container_version,
    load_support_data,
    resolve_support_paths,
)
from .opencam.uni_parser import parse_uni_records
from .opencam.uni_wrappers import Unit, wrap_units

logger = logging.getLogger("html_brief_log")


def extract_cam_brief_data(
    cam_file_path: str | Path,
    *,
    bms_base_dir: str | Path | None = None,
    theater_target_folder: str | Path | None = None,
    theater_name: str | None = None,
    save_stem: str | None = None,
) -> SummaryOutput:
    """Parse a CAM-like save and return app brief JSON."""

    source_path = Path(cam_file_path).resolve()
    support_base_dir = _resolve_support_root(
        bms_base_dir,
        theater_target_folder,
        theater_name=theater_name,
    )

    warnings: list[str] = []
    container = CamContainer.from_path(source_path)
    container_version = detect_container_version(container)
    cmp_entry = _entry_by_ext(container, ".cmp")
    uni_entry = _entry_by_ext(container, ".uni")

    twx_data, l16_data = _load_sidecars(
        source_path,
        bms_base_dir=bms_base_dir,
        theater_target_folder=theater_target_folder,
        save_stem=save_stem,
    )
    cmp_data = _parse_cmp_data(cmp_entry, container_version, warnings)
    units = _parse_uni_units(
        uni_entry,
        source_path=source_path,
        support_base_dir=support_base_dir,
        container_version=container_version,
        warnings=warnings,
    )

    warnings.extend(twx_data.warnings)
    warnings.extend(l16_data.warnings)

    return build_cam_brief_data(
        source_path=source_path,
        support_base_dir=support_base_dir,
        twx_data=twx_data,
        l16_data=l16_data,
        cmp_data=cmp_data,
        units=units,
        warnings=warnings,
        bms_base_dir=bms_base_dir,
        theater_name=theater_name,
    )


def _load_sidecars(
    source_path: Path,
    *,
    bms_base_dir: str | Path | None,
    theater_target_folder: str | Path | None,
    save_stem: str | None,
) -> tuple[ParsedTwxData, ParsedL16Data]:
    twx_data = load_parsed_twx_for_cam_path(source_path)
    stem = save_stem or source_path.stem
    if not twx_data.current_date:
        twx_data = load_parsed_twx_for_save(
            bms_base_dir=bms_base_dir,
            theater_target_folder=theater_target_folder,
            save_stem=stem,
        )
    l16_data = load_parsed_l16_for_save(
        bms_base_dir=bms_base_dir,
        theater_target_folder=theater_target_folder,
        save_stem=stem,
    )
    return twx_data, l16_data


def _entry_by_ext(container: CamContainer, ext: str) -> DecodedEntry | None:
    normalized = ext.lower()
    for entry in container.entries:
        if Path(entry.name).suffix.lower() == normalized:
            return entry
    return None


def _parse_cmp_data(
    entry: DecodedEntry | None,
    container_version: int | None,
    warnings: list[str],
) -> ParsedCmpData:
    if entry is None:
        warnings.append(".cmp entry not found in CAM container")
        return ParsedCmpData()

    record = parse_cmp_record(entry, container_version=container_version)
    campaign = wrap_campaign(record)
    try:
        player_squadron_id: object = record.player_squadron_id
    except Exception:
        player_squadron_id = None
        warnings.append("player_squadron_id not found in .cmp")

    return ParsedCmpData(
        current_time_ms=campaign.current_time_ms,
        current_time_z=campaign.current_time_z,
        bullseye_name_id=campaign.bullseye_name,
        bullseye_x=campaign.bullseye_x,
        bullseye_y=campaign.bullseye_y,
        player_squadron_id=_as_vuid(player_squadron_id),
    )


def _parse_uni_units(
    entry: DecodedEntry | None,
    *,
    source_path: Path,
    support_base_dir: Path | None,
    container_version: int | None,
    warnings: list[str],
) -> tuple[Unit, ...]:
    if entry is None:
        warnings.append(".uni entry not found in CAM container")
        return ()

    try:
        support_paths = _support_paths_from_base(support_base_dir)
        support = load_support_data(support_paths)
        records = parse_uni_records(
            entry,
            container_version=container_version or 0,
            support=support,
        )
        return wrap_units(records, support)
    except Exception as exc:
        logger.warning("opencam UNI summary projection failed for %s: %s", source_path, exc)
        warnings.append(f"opencam UNI summary projection failed: {exc}")
        return ()


def _resolve_support_root(
    bms_base_dir: str | Path | None,
    theater_target_folder: str | Path | None,
    *,
    theater_name: str | None = None,
) -> Path | None:
    """Resolve explicit theater context; never pick an arbitrary add-on."""
    root = resolve_theater_data_root(bms_base_dir, theater_name)
    if root is not None:
        root = root.resolve()
    if theater_target_folder:
        target = Path(theater_target_folder).expanduser()
        if not target.is_absolute() and bms_base_dir:
            target = Path(bms_base_dir).expanduser() / target
        target = target.resolve()
        for candidate in (target, *target.parents):
            if candidate.name.casefold() == "objects" and candidate.parent.name.casefold() == "terrdata":
                target_root = candidate.parent.parent
                return target_root if root is None or root == target_root else None
    if root is not None:
        return root
    if bms_base_dir and not theater_name:
        return (Path(bms_base_dir).expanduser() / "Data").resolve()
    return None


def _support_paths_from_base(support_base_dir: Path | None) -> BmsSupportPaths:
    if support_base_dir is None:
        raise BmsSupportError("support base directory could not be inferred")

    if not support_base_dir.is_dir():
        raise BmsSupportError(f"missing required support files under {support_base_dir}")
    return resolve_support_paths(support_base_dir)


def _as_vuid(value: object) -> Vuid | None:
    if (
        isinstance(value, tuple)
        and len(value) == 2
        and isinstance(value[0], int)
        and isinstance(value[1], int)
    ):
        return int(value[0]), int(value[1])
    return None


__all__ = ["extract_cam_brief_data"]
