from __future__ import annotations

import configparser
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from lib.bms_paths import callsign_ini_path
from lib.bms_config import BmsConfig
from lib.html_gen import generate_html_file, page_contents_ini_to_list

logger = logging.getLogger("html_brief_log")


class PreviewRequest(BaseModel):
    pages: Optional[Dict[str, str]] = None
    bms: Optional[Dict[str, str]] = None
    system: Optional[Dict[str, str]] = None
    theater: Optional[Dict[str, Any]] = None
    kneeboard_order: Optional[List[Dict[str, Any]]] = None
    selected_package_index: Optional[int] = None


def resolve_brief_render_state(
    app: FastAPI,
    request_index: Optional[int],
) -> tuple[Optional[Dict[str, Any]], Optional[int]]:
    brief_summary = app.state.last_brief_summary if isinstance(app.state.last_brief_summary, dict) else None
    if brief_summary is None:
        app.state.last_selected_package_index = None
        return None, None

    packages = brief_summary.get("packages")
    package_count = len(packages) if isinstance(packages, list) else 0
    if package_count <= 0:
        app.state.last_selected_package_index = None
        return brief_summary, None

    selected_index = request_index if isinstance(request_index, int) else app.state.last_selected_package_index
    if not isinstance(selected_index, int) or selected_index < 0 or selected_index >= package_count:
        selected_index = 0
    app.state.last_selected_package_index = selected_index
    return brief_summary, selected_index


def register_render_routes(
    app: FastAPI,
    *,
    ensure_dirs: Callable[[configparser.ConfigParser], None],
    resolve_path: Callable[[str], Path],
    copy_config_with_overrides: Callable[..., configparser.ConfigParser],
) -> None:
    """Register HTML render endpoints."""

    @app.post("/api/generate")
    def generate(payload: PreviewRequest = None) -> Dict[str, str]:
        if app.state.bms_cfg is None:
            raise HTTPException(status_code=500, detail="BMS config is not loaded. Reload and try again.")
        overrides = payload.model_dump(exclude_none=True) if payload else {}
        cfg_generate = copy_config_with_overrides(
            app.state.cfg,
            pages=overrides.get("pages"),
            bms=overrides.get("bms"),
            system=overrides.get("system"),
        )
        try:
            bms_cfg_generate = BmsConfig(
                cfg_generate,
                theater_ini_pattern=app.state.theater_ini_pattern,
            )
        except Exception as exc:
            logger.error("Failed to build generate BMS config: %s", exc)
            raise HTTPException(status_code=500, detail=f"Generate config error: {exc}")
        ensure_dirs(cfg_generate)
        try:
            brief_summary, selected_package_index = resolve_brief_render_state(
                app,
                getattr(payload, "selected_package_index", None) if payload else None,
            )
            generate_html_file(
                cfg_generate,
                bms_cfg_generate,
                "index",
                brief_summary=brief_summary,
                selected_package_index=selected_package_index,
            )
            output_file = resolve_path(cfg_generate["system"]["output_dir"]) / "index.html"
            app.state.last_brief_path = str(output_file)
            _update_brief_mtime_state(app, bms_cfg_generate)
            app.state.brief_pages_ref = len(page_contents_ini_to_list(cfg_generate))
        except Exception as exc:
            logger.error("Failed to generate HTML: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to generate HTML: {exc}")
        return {"status": "ok", "output_file": str(output_file)}

    @app.post("/api/preview")
    def preview(payload: PreviewRequest) -> Dict[str, str]:
        cfg_preview = copy_config_with_overrides(
            app.state.cfg,
            pages=payload.pages,
            bms=payload.bms,
            system=payload.system,
        )
        try:
            bms_cfg_preview = BmsConfig(
                cfg_preview,
                theater_ini_pattern=app.state.theater_ini_pattern,
            )
        except Exception as exc:
            logger.error("Failed to build preview BMS config: %s", exc)
            raise HTTPException(status_code=500, detail=f"Preview config error: {exc}")
        ensure_dirs(cfg_preview)
        try:
            brief_summary, selected_package_index = resolve_brief_render_state(
                app,
                payload.selected_package_index,
            )
            generate_html_file(
                cfg_preview,
                bms_cfg_preview,
                "index",
                brief_summary=brief_summary,
                selected_package_index=selected_package_index,
            )
            output_file = resolve_path(cfg_preview["system"]["output_dir"]) / "index.html"
            app.state.last_brief_path = str(output_file)
            _update_brief_mtime_state(app, bms_cfg_preview)
            app.state.brief_pages_ref = len(page_contents_ini_to_list(cfg_preview))
        except Exception as exc:
            logger.error("Failed to generate preview HTML: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to generate HTML: {exc}")
        return {"status": "ok", "output_file": str(output_file)}


def _update_brief_mtime_state(app: FastAPI, bms_cfg: BmsConfig) -> None:
    try:
        app.state.brief_mtime_ref = os.path.getmtime(
            Path(bms_cfg.base_dir) / "User" / "Briefings" / "briefing.txt"
        )
        app.state.callsign_mtime_ref = os.path.getmtime(
            callsign_ini_path(bms_cfg)
        )
    except Exception:
        pass


__all__ = ["PreviewRequest", "register_render_routes", "resolve_brief_render_state"]
