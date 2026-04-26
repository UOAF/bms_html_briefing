from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from lib.cam.summary import extract_cam_brief_data as parse_cam_summary

logger = logging.getLogger("html_brief_log")


class CamIntegrationError(RuntimeError):
    """Raised when CAM parsing fails."""


def extract_cam_brief_data(
    cam_file_path: str | Path,
    *,
    bms_base_dir: str | Path | None = None,
    theater_target_folder: str | Path | None = None,
    theater_name: str | None = None,
    save_stem: str | None = None,
) -> dict[str, Any]:
    logger.debug(
        "Extract CAM brief data: cam=%s base=%s theater_target=%s theater=%s save_stem=%s",
        cam_file_path,
        bms_base_dir,
        theater_target_folder,
        theater_name,
        save_stem,
    )
    try:
        return parse_cam_summary(
            cam_file_path,
            bms_base_dir=bms_base_dir,
            theater_target_folder=theater_target_folder,
            theater_name=theater_name,
            save_stem=save_stem,
        )
    except Exception as exc:
        logger.exception("Failed to parse CAM file: %s", cam_file_path)
        raise CamIntegrationError(f"Failed to parse CAM file: {exc}") from exc
