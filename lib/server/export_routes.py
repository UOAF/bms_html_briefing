from __future__ import annotations

import configparser
import logging
from typing import Callable, Dict

from fastapi import FastAPI, HTTPException

from lib.bms_config import BmsConfig
from lib.kneeboard_export import export_kneeboards
from lib.kneeboard_order import save_kneeboard_order
from lib.server.render_routes import PreviewRequest

logger = logging.getLogger("html_brief_log")


def register_export_routes(
    app: FastAPI,
    *,
    ensure_dirs: Callable[[configparser.ConfigParser], None],
    copy_config_with_overrides: Callable[..., configparser.ConfigParser],
) -> None:
    """Register kneeboard export endpoint."""

    @app.post("/api/export")
    def export(payload: PreviewRequest = None) -> Dict[str, str]:
        cfg_export = copy_config_with_overrides(
            app.state.cfg,
            pages=getattr(payload, "pages", None),
            bms=getattr(payload, "bms", None),
            system=getattr(payload, "system", None),
        )
        runtime_kneeboard_order = getattr(payload, "kneeboard_order", None) if payload else None
        if runtime_kneeboard_order:
            save_kneeboard_order(cfg_export, runtime_kneeboard_order)
        try:
            bms_cfg_export = BmsConfig(
                cfg_export,
                theater_ini_pattern=app.state.theater_ini_pattern,
            )
        except Exception as exc:
            logger.error("Failed to build export BMS config: %s", exc)
            raise HTTPException(status_code=500, detail=f"Export config error: {exc}")

        # Allow in-memory theater overrides (e.g., copy_to_kto) without persisting them.
        theater_overrides = getattr(payload, "theater", None) if payload else None
        if theater_overrides:
            theater_name = getattr(bms_cfg_export, "theater", None)
            if theater_name:
                if not bms_cfg_export.theater_config.has_section(theater_name):
                    bms_cfg_export.theater_config[theater_name] = {}
                section = bms_cfg_export.theater_config[theater_name]
                if "copy_to_kto" in theater_overrides:
                    section["copy_to_kto"] = "True" if theater_overrides["copy_to_kto"] else "False"

        ensure_dirs(cfg_export)
        try:
            export_kneeboards(cfg_export, bms_cfg_export)
        except Exception as exc:
            logger.error("Failed to export kneeboards: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to export kneeboards: {exc}")
        theater_name = getattr(bms_cfg_export, "theater", "")
        theater_cfg = getattr(bms_cfg_export, "theater_config", {})
        target_folder = ""
        if theater_name and theater_cfg and theater_cfg.has_section(theater_name):
            target_folder = theater_cfg[theater_name].get("target_folder", "")
        return {"status": "ok", "target_folder": target_folder}


__all__ = ["register_export_routes"]
