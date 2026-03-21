from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from lib.cam.types import ParsedCmpData, ParsedUniData, SummaryInput, SummaryOutput
from lib.parsers.parse_cmp import parse_cmp
from lib.parsers.parse_l16 import load_parsed_l16_for_save
from lib.parsers.parse_summary import build_summary_output
from lib.parsers.parse_twx import load_parsed_twx_for_cam_path, load_parsed_twx_for_save
from lib.parsers.parse_uni import parse_uni

logger = logging.getLogger("html_brief_log")


class CamIntegrationError(RuntimeError):
    """Raised when CAM integration cannot parse expected data."""


def _resolve_cam_modules() -> Any:
    try:
        from lib.cam.cam_content import parse_cam_file
    except Exception as exc:
        logger.exception("Failed to import CAM parser modules")
        raise CamIntegrationError(f"Failed to import CAM parser modules: {exc}") from exc

    logger.debug("Resolved CAM modules via static package imports")
    return parse_cam_file


def _infer_support_base_dir(
    bms_base_dir: str | Path | None,
    theater_target_folder: str | Path | None,
    theater_name: str | None = None,
) -> Path | None:
    def normalize_token(text: str) -> str:
        return "".join(ch for ch in text.lower() if ch.isalnum())

    def has_ct(objects_dir: Path) -> bool:
        if not objects_dir.is_dir():
            return False
        try:
            for child in objects_dir.iterdir():
                if child.is_file() and child.name.lower() == "falcon4_ct.xml":
                    return True
        except Exception:
            return False
        return False

    def infer_objects_from_target(target_path: Path) -> Path | None:
        resolved = target_path.resolve()
        if resolved.name.lower() == "koreaobj":
            return resolved.parent
        parts_l = [part.lower() for part in resolved.parts]
        if "koreaobj" in parts_l:
            idx = parts_l.index("koreaobj")
            if idx > 0:
                return Path(*resolved.parts[:idx])
        # If the target already points to the objects folder.
        if resolved.name.lower() == "objects":
            return resolved
        return None

    def infer_addon_token_from_target(target_path: Path) -> str | None:
        resolved = target_path.resolve()
        for part in resolved.parts:
            part_l = part.lower()
            if part_l.startswith("add-on"):
                token = normalize_token(part_l.replace("add-on", "", 1))
                if token:
                    return token
        return None

    if theater_target_folder:
        target_path = Path(theater_target_folder).expanduser()
        objects_from_target = infer_objects_from_target(target_path)
        if objects_from_target is not None and has_ct(objects_from_target):
            logger.debug(
                "Support base dir resolved from theater target folder: %s",
                objects_from_target,
            )
            return objects_from_target

    if bms_base_dir:
        base = Path(bms_base_dir).expanduser()
        data_dir = base / "Data"

        add_on_objects: list[tuple[Path, str, str]] = []
        if data_dir.is_dir():
            try:
                for add_on_dir in data_dir.iterdir():
                    if not add_on_dir.is_dir():
                        continue
                    add_on_name = add_on_dir.name
                    if not add_on_name.lower().startswith("add-on"):
                        continue
                    objects_dir = None
                    for candidate in (
                        add_on_dir / "TerrData" / "Objects",
                        add_on_dir / "Terrdata" / "Objects",
                        add_on_dir / "Terrdata" / "objects",
                    ):
                        if has_ct(candidate):
                            objects_dir = candidate
                            break
                    if objects_dir is None:
                        continue
                    add_on_objects.append(
                        (
                            objects_dir,
                            add_on_name.lower(),
                            normalize_token(add_on_name.replace("add-on", "", 1)),
                        )
                    )
            except Exception:
                pass

        # First priority: infer add-on from theater target folder, even if the folder itself
        # points at a non-objects path (e.g. .../TerrData/Hellas/KoreaObj).
        if theater_target_folder and add_on_objects:
            target_path = Path(theater_target_folder).expanduser()
            target_addon_token = infer_addon_token_from_target(target_path)
            if target_addon_token:
                for objects_dir, add_on_name, add_on_token in add_on_objects:
                    if (
                        target_addon_token == add_on_token
                        or target_addon_token in add_on_token
                        or add_on_token in target_addon_token
                        or add_on_name in str(target_path).lower()
                    ):
                        logger.debug(
                            "Support base dir resolved from add-on target match: %s",
                            objects_dir,
                        )
                        return objects_dir

        # Second priority: infer add-on from active theater name.
        if add_on_objects and theater_name:
            theater_l = theater_name.lower()
            theater_token = normalize_token(theater_name)
            for objects_dir, add_on_name, add_on_token in add_on_objects:
                if (
                    theater_l in str(objects_dir).lower()
                    or theater_l in add_on_name
                    or (theater_token and (theater_token in add_on_token or add_on_token in theater_token))
                ):
                    logger.debug(
                        "Support base dir resolved from theater name match: %s",
                        objects_dir,
                    )
                    return objects_dir

        # Fallback to default KTO objects.
        default_objects_candidates = [
            base / "Data" / "TerrData" / "Objects",
            base / "Data" / "Terrdata" / "Objects",
        ]
        for objects_dir in default_objects_candidates:
            if has_ct(objects_dir):
                logger.debug("Support base dir resolved to default KTO objects: %s", objects_dir)
                return objects_dir

        if add_on_objects:
            logger.debug(
                "Support base dir falling back to first add-on objects: %s",
                add_on_objects[0][0],
            )
            return add_on_objects[0][0]

    if theater_target_folder:
        target_path = Path(theater_target_folder).expanduser()
        objects_from_target = infer_objects_from_target(target_path)
        if objects_from_target is not None and objects_from_target.is_dir():
            logger.debug(
                "Support base dir fallback to inferred objects dir without CT validation: %s",
                objects_from_target,
            )
            return objects_from_target

    if bms_base_dir:
        fallback = Path(bms_base_dir).expanduser().resolve()
        logger.debug("Support base dir fallback to BMS base dir: %s", fallback)
        return fallback
    logger.debug("Support base dir could not be inferred.")
    return None


def extract_cam_brief_data(
    cam_file_path: str | Path,
    *,
    bms_base_dir: str | Path | None = None,
    theater_target_folder: str | Path | None = None,
    theater_name: str | None = None,
    save_stem: str | None = None,
) -> dict[str, Any]:
    logger.debug(
        "Extract CAM brief data start: cam=%s base=%s theater_target=%s theater=%s save_stem=%s",
        cam_file_path,
        bms_base_dir,
        theater_target_folder,
        theater_name,
        save_stem,
    )
    parse_cam_file = _resolve_cam_modules()

    source_path = Path(cam_file_path).resolve()
    support_base_dir = _infer_support_base_dir(
        bms_base_dir,
        theater_target_folder,
        theater_name=theater_name,
    )

    parsed_cam = parse_cam_file(
        source_path,
        bms_base_dir=support_base_dir,
        parse_entries=False,
        best_effort=True,
    )
    cmp_entry = parsed_cam.get_entry_by_ext(".cmp")
    uni_entry = parsed_cam.get_entry_by_ext(".uni")

    twx_data = load_parsed_twx_for_cam_path(source_path)
    if not twx_data.current_date:
        twx_data = load_parsed_twx_for_save(
            bms_base_dir=bms_base_dir,
            theater_target_folder=theater_target_folder,
            save_stem=save_stem or source_path.stem,
        )
    l16_data = load_parsed_l16_for_save(
        bms_base_dir=bms_base_dir,
        theater_target_folder=theater_target_folder,
        save_stem=save_stem or source_path.stem,
    )

    summary_input = SummaryInput(
        source_path=source_path,
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
        theater_name=theater_name or "",
    )

    try:
        summary_output = build_summary_output(summary_input)
        logger.debug(
            "Extract CAM brief data done: package_count=%d warnings=%d",
            summary_output.package_count,
            len(summary_output.warnings),
        )
        return summary_output.to_dict()
    except Exception as exc:
        logger.exception("CAM summary shaping failed for %s", source_path)
        fallback = SummaryOutput(
            source_path=str(source_path),
            support_base_dir=str(support_base_dir) if support_base_dir is not None else "",
            l16_source_path=str(l16_data.source_path) if l16_data.source_path is not None else "",
            current_date=twx_data.current_date,
            current_time_ms=None,
            player={"squadron_id": None, "package_match_method": "summary_failed"},
            bullseye={
                "x": None,
                "y": None,
                "name_id": None,
                "name": "",
                "map_lat": None,
                "map_lng": None,
                "map_grid_size_x": 1024,
                "map_grid_size_y": 1024,
            },
            package_count=0,
            packages=[],
            warnings=[f"Summary shaping failed: {exc}"],
            container_version=parsed_cam.container_version,
        )
        return fallback.to_dict()
