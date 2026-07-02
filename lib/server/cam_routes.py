from __future__ import annotations

import configparser
import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from lib.cam.extract import extract_cam_brief_data
from lib.campaign_paths import campaign_dirs

logger = logging.getLogger("html_brief_log")

CAM_SUFFIXES = {".cam", ".trn", ".tac"}


class CamLoadLocalRequest(BaseModel):
    path: str


def register_cam_routes(
    app: FastAPI,
    *,
    ensure_dirs: Callable[[configparser.ConfigParser], None],
    resolve_path: Callable[[str], Path],
) -> None:
    """Register CAM save listing/load/unload endpoints."""

    def resolve_cam_context() -> tuple[Optional[str], Optional[str], Optional[str], list[Path]]:
        bms = app.state.bms_cfg
        bms_base_dir: Optional[str] = None
        theater_target_folder: Optional[str] = None
        theater_name: Optional[str] = None
        if bms is not None:
            bms_base_dir = getattr(bms, "base_dir", None) or None
            theater_name = getattr(bms, "theater", None) or None
            try:
                if bms.theater_config.has_section(bms.theater):
                    theater_target_folder = bms.theater_config[bms.theater].get("target_folder", "") or None
            except Exception:
                theater_target_folder = None
        campaign_dir_list = campaign_dirs(
            bms_base_dir=bms_base_dir,
            theater_target_folder=theater_target_folder,
        )
        return bms_base_dir, theater_target_folder, theater_name, campaign_dir_list

    @app.get("/api/cam/saves")
    def list_cam_saves() -> Dict[str, Any]:
        _, _, _, resolved_campaign_dirs = resolve_cam_context()
        saves: list[dict[str, Any]] = []
        seen: set[Path] = set()
        for directory in resolved_campaign_dirs:
            try:
                for candidate in directory.iterdir():
                    if not candidate.is_file():
                        continue
                    suffix = candidate.suffix.lower()
                    if suffix not in CAM_SUFFIXES:
                        continue
                    resolved = candidate.resolve()
                    if resolved in seen:
                        continue
                    seen.add(resolved)
                    stat = candidate.stat()
                    saves.append(
                        {
                            "name": candidate.name,
                            "stem": candidate.stem,
                            "suffix": suffix,
                            "path": str(resolved),
                            "size": stat.st_size,
                            "mtime": stat.st_mtime,
                        }
                    )
            except Exception as exc:
                logger.warning("Failed listing campaign directory %s: %s", directory, exc)
        saves.sort(key=lambda item: item.get("mtime", 0.0), reverse=True)
        return {
            "campaign_dirs": [str(path) for path in resolved_campaign_dirs],
            "allowed_extensions": sorted(CAM_SUFFIXES),
            "saves": saves,
        }

    @app.post("/api/cam/load-local")
    def load_cam_local(payload: CamLoadLocalRequest) -> Dict[str, Any]:
        path_text = (payload.path or "").strip()
        if not path_text:
            raise HTTPException(status_code=400, detail="path is required")

        try:
            source_path = Path(path_text).expanduser().resolve()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid save path: {exc}") from exc
        if not source_path.is_file():
            raise HTTPException(status_code=400, detail=f"Save file does not exist: {source_path}")

        suffix = source_path.suffix.lower()
        if suffix not in CAM_SUFFIXES:
            raise HTTPException(status_code=400, detail="Only .cam/.trn/.tac files are supported")

        bms_base_dir, theater_target_folder, theater_name, resolved_campaign_dirs = resolve_cam_context()
        if not resolved_campaign_dirs:
            raise HTTPException(status_code=400, detail="No campaign directories resolved from BMS config")
        if not any(_path_within(source_path, directory) for directory in resolved_campaign_dirs):
            raise HTTPException(status_code=400, detail="Selected save path is outside allowed campaign directories")

        ensure_dirs(app.state.cfg)
        output_dir = resolve_path(app.state.cfg["system"]["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            cam_data = extract_cam_brief_data(
                source_path,
                bms_base_dir=bms_base_dir,
                theater_target_folder=theater_target_folder,
                theater_name=theater_name,
                save_stem=source_path.stem,
            )
        except Exception as exc:
            logger.error("CAM parsing failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to parse CAM file: {exc}") from exc

        json_path = output_dir / "summary.json"
        json_path.write_text(json.dumps(cam_data, indent=2), encoding="utf-8")

        app.state.last_brief_summary_path = str(json_path)
        app.state.last_brief_summary = cam_data
        app.state.last_selected_package_index = None

        return {
            "status": "ok",
            "source_file": str(source_path),
            "output_file": str(json_path),
            "selected_package_index": app.state.last_selected_package_index,
            "summary": cam_data,
        }

    @app.post("/api/cam/unload")
    def unload_cam_local() -> Dict[str, Any]:
        app.state.last_brief_summary_path = None
        app.state.last_brief_summary = None
        app.state.last_selected_package_index = None
        return {"status": "ok"}


def _path_within(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


__all__ = ["register_cam_routes"]
