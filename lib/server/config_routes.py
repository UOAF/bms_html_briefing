from __future__ import annotations

import configparser
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from lib.bms_config import BmsConfig
from lib.html_gen import page_contents_ini_to_list

logger = logging.getLogger("html_brief_log")

CHECKLIST_ALLOWED_TAGS = {"br", "b", "strong", "i", "em", "u", "span", "img"}
CHECKLIST_DROP_TAGS = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "link",
    "meta",
    "base",
    "form",
    "input",
    "button",
    "textarea",
    "select",
    "option",
    "svg",
    "math",
}
CHECKLIST_IMAGE_SRC_PREFIXES = (
    "data:image/png;base64,",
    "data:image/jpeg;base64,",
    "data:image/jpg;base64,",
    "data:image/gif;base64,",
    "data:image/webp;base64,",
)
REPLACED_MAP_SYSTEM_KEYS = {
    "map_base_mode",
    "web_tile_url_template",
    "web_tile_attribution",
    "web_tile_filter",
    "web_tile_layers",
}


class ConfigUpdate(BaseModel):
    system: Optional[Dict[str, str]] = None
    bms: Optional[Dict[str, str]] = None
    pages: Optional[Dict[str, str]] = None


class TheaterUpdate(BaseModel):
    target_folder: Optional[str] = None
    map_file: Optional[str] = None
    copy_to_kto: Optional[bool] = None


class CustomChecklistSaveRequest(BaseModel):
    values: Dict[str, Any]


def register_config_routes(
    app: FastAPI,
    *,
    ensure_dirs: Callable[[configparser.ConfigParser], None],
    load_config: Callable[[Path], configparser.ConfigParser],
    save_config: Callable[[configparser.ConfigParser, Path], None],
    configure_debug_file_logging: Callable[[configparser.ConfigParser], None],
    get_runtime_template_path: Callable[[str], Path],
) -> None:
    """Register config, theater, status, reload, and checklist endpoints."""

    @app.get("/api/theater")
    def get_theater() -> Dict[str, Any]:
        bms = app.state.bms_cfg
        if bms is None:
            raise HTTPException(status_code=500, detail="BMS config not loaded")
        if not bms.theater_config.has_section(bms.theater):
            bms.theater_config[bms.theater] = {"copy_to_kto": "False"}
        cfg = bms.theater_config[bms.theater]
        map_file = cfg.get("map_file", "") or cfg.get("default_map_file", "")
        if map_file and not os.path.isabs(map_file):
            map_file = os.path.join(bms.base_dir, map_file)
        if not map_file:
            map_file = os.path.join(bms.script_dir, "assets", "maps", "map.png")
        return {
            "theater": bms.theater,
            "target_folder": cfg.get("target_folder", ""),
            "map_file": map_file,
            "copy_to_kto": cfg.get("copy_to_kto", "False") == "True",
            "center_latitude": getattr(bms, "theater_center_latitude", None),
            "center_longitude": getattr(bms, "theater_center_longitude", None),
            "center_source": getattr(bms, "theater_center_source", ""),
        }

    @app.get("/api/config")
    def get_config() -> Dict[str, Dict[str, str]]:
        return _serialize_config(app.state.cfg)

    @app.post("/api/custom-checklist/template")
    def save_custom_checklist_template(payload: CustomChecklistSaveRequest) -> Dict[str, Any]:
        values = payload.values or {}
        if not values:
            raise HTTPException(status_code=400, detail="No checklist values provided")
        template_path = get_runtime_template_path("custom_checklist.html")
        if not template_path.exists():
            raise HTTPException(status_code=404, detail="Custom checklist template not found")
        try:
            soup = BeautifulSoup(template_path.read_text(encoding="utf-8"), "html.parser")
            editable_nodes = soup.select("[data-checklist-editable='1'][id]")
            editable_ids = {node.get("id") for node in editable_nodes if node.get("id")}
            updated = 0
            for key, value in values.items():
                if key not in editable_ids:
                    continue
                el = soup.find(id=key)
                if el is None or el.get("data-checklist-editable") != "1":
                    continue
                el.clear()
                _append_sanitized_html(el, value)
                updated += 1
            if updated == 0:
                raise HTTPException(status_code=400, detail="No valid checklist fields provided")
            template_path.write_text(str(soup), encoding="utf-8")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Failed to save custom checklist template: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to save custom checklist template: {exc}")
        return {"status": "ok", "updated": updated, "path": str(template_path)}

    @app.post("/api/config")
    def update_config(payload: ConfigUpdate) -> Dict[str, Dict[str, str]]:
        payload_dict = payload.model_dump(exclude_none=True)
        if not payload_dict:
            raise HTTPException(status_code=400, detail="No config fields provided")
        # Keep in-memory config in sync for immediate UI/runtime behavior.
        for section, values in payload_dict.items():
            if section not in app.state.cfg:
                app.state.cfg[section] = {}
            if section == "system" and "map" in values:
                for stale_key in REPLACED_MAP_SYSTEM_KEYS:
                    app.state.cfg[section].pop(stale_key, None)
            for key, value in values.items():
                app.state.cfg[section][key] = str(value)

        # Persist only explicitly provided fields so runtime-only overrides
        # (set via /api/config/runtime) are not accidentally written to disk.
        cfg_to_persist = load_config(app.state.config_path)
        for section, values in payload_dict.items():
            if section not in cfg_to_persist:
                cfg_to_persist[section] = {}
            if section == "system" and "map" in values:
                for stale_key in REPLACED_MAP_SYSTEM_KEYS:
                    cfg_to_persist[section].pop(stale_key, None)
            for key, value in values.items():
                cfg_to_persist[section][key] = str(value)
        save_config(cfg_to_persist, app.state.config_path)
        ensure_dirs(app.state.cfg)
        configure_debug_file_logging(app.state.cfg)
        app.state.bms_cfg = BmsConfig(app.state.cfg, theater_ini_pattern=app.state.theater_ini_pattern)
        return _serialize_config(app.state.cfg)

    @app.post("/api/config/runtime")
    def update_config_runtime(payload: ConfigUpdate) -> Dict[str, Dict[str, str]]:
        payload_dict = payload.model_dump(exclude_none=True)
        if not payload_dict:
            raise HTTPException(status_code=400, detail="No config fields provided")
        for section, values in payload_dict.items():
            if section not in app.state.cfg:
                app.state.cfg[section] = {}
            if section == "system" and "map" in values:
                for stale_key in REPLACED_MAP_SYSTEM_KEYS:
                    app.state.cfg[section].pop(stale_key, None)
            for key, value in values.items():
                app.state.cfg[section][key] = str(value)
        ensure_dirs(app.state.cfg)
        configure_debug_file_logging(app.state.cfg)
        try:
            app.state.bms_cfg = BmsConfig(app.state.cfg, theater_ini_pattern=app.state.theater_ini_pattern)
        except Exception as exc:
            logger.error("Failed to reload BMS config (runtime): %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to reload BMS config: {exc}")
        return _serialize_config(app.state.cfg)

    @app.post("/api/theater")
    def update_theater(payload: TheaterUpdate) -> Dict[str, Any]:
        bms = app.state.bms_cfg
        if bms is None:
            raise HTTPException(status_code=500, detail="BMS config not loaded")
        theater_cfg = configparser.ConfigParser()
        theater_ini_path = Path(getattr(bms, "theater_ini_path", Path(bms.script_dir) / f"theaters_{bms.version}.ini"))
        try:
            if theater_ini_path.exists():
                theater_cfg.read(str(theater_ini_path), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to read theater config before update: %s", exc)

        if not theater_cfg.has_section(bms.theater):
            theater_cfg[bms.theater] = {}
        section = theater_cfg[bms.theater]
        if payload.target_folder is not None:
            section["target_folder"] = payload.target_folder
        if payload.map_file is not None and str(payload.map_file).strip() != "":
            path_val = payload.map_file
            if path_val and not os.path.isabs(path_val):
                path_val = os.path.join(bms.base_dir, path_val)
            section["map_file"] = path_val
        if payload.copy_to_kto is not None:
            section["copy_to_kto"] = "True" if payload.copy_to_kto else "False"
        try:
            theater_ini_path.parent.mkdir(parents=True, exist_ok=True)
            with open(theater_ini_path, "w+", encoding="utf-8") as f:
                theater_cfg.write(f)
            bms.theater_config = theater_cfg  # keep in-memory state in sync
        except Exception as exc:
            logger.error("Failed to write theater config: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to save theater config: {exc}")
        return {
            "theater": bms.theater,
            "target_folder": section.get("target_folder", ""),
            "map_file": section.get("map_file", section.get("default_map_file", "")),
            "copy_to_kto": section.get("copy_to_kto", "False") == "True",
            "center_latitude": getattr(bms, "theater_center_latitude", None),
            "center_longitude": getattr(bms, "theater_center_longitude", None),
            "center_source": getattr(bms, "theater_center_source", ""),
        }

    @app.post("/api/reload")
    def reload_bms_config() -> Dict[str, Any]:
        try:
            app.state.bms_cfg = BmsConfig(app.state.cfg, theater_ini_pattern=app.state.theater_ini_pattern)
        except Exception as exc:
            logger.error("Failed to reload BMS config: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to reload BMS config: {exc}")
        return {
            "status": "ok",
            "base_dir": getattr(app.state.bms_cfg, "base_dir", ""),
            "theater": getattr(app.state.bms_cfg, "theater", ""),
        }

    @app.get("/api/status")
    def status() -> Dict[str, Any]:
        bms = app.state.bms_cfg
        cfg = app.state.cfg
        data: Dict[str, Any] = {
            "app_instance_id": app.state.instance_id,
            "config_path": str(app.state.config_path),
            "output_dir": cfg["system"]["output_dir"],
            "pdf_output_dir": cfg["system"]["pdf_output_dir"],
            "pages": page_contents_ini_to_list(cfg),
            "pdf_pages": app.state.pdf_page_count,
            "brief_pages": app.state.brief_pages_ref,
            "pdf_overflow": app.state.pdf_overflow,
            "pdf_busy": app.state.pdf_busy,
            "cam_loaded": isinstance(app.state.last_brief_summary, dict),
            "cam_output_file": app.state.last_brief_summary_path,
        }
        if bms:
            target_folder = ""
            if bms.theater_config.has_section(bms.theater):
                target_folder = bms.theater_config[bms.theater].get("target_folder", "")
            brief_path = Path(bms.base_dir) / "User" / "Briefings" / "briefing.txt"
            callsign_path = Path(bms.base_dir) / "User" / "Config" / f"{bms.callsign}.ini"
            brief_mtime = brief_path.stat().st_mtime if brief_path.exists() else None
            callsign_mtime = callsign_path.stat().st_mtime if callsign_path.exists() else None
            data.update(
                {
                    "callsign": bms.callsign,
                    "base_dir": bms.base_dir,
                    "theater": bms.theater,
                    "target_folder": target_folder,
                    "kto_target_folder": bms.kto_target_folder,
                    "target_folder_failed": bms.target_folder_failed,
                    "center_latitude": getattr(bms, "theater_center_latitude", None),
                    "center_longitude": getattr(bms, "theater_center_longitude", None),
                    "center_source": getattr(bms, "theater_center_source", ""),
                    "brief_changed": None if (app.state.brief_mtime_ref is None or brief_mtime is None) else brief_mtime > app.state.brief_mtime_ref,
                    "callsign_changed": None if (app.state.callsign_mtime_ref is None or callsign_mtime is None) else callsign_mtime > app.state.callsign_mtime_ref,
                }
            )
        else:
            data.update({"error": "BMS config not loaded"})
        return data


def _serialize_config(cfg: configparser.ConfigParser) -> Dict[str, Dict[str, str]]:
    return {section: dict(cfg[section]) for section in cfg.sections()}


def _append_sanitized_html(el: Any, raw: Any) -> None:
    fragment = BeautifulSoup("" if raw is None else str(raw), "html.parser")
    _sanitize_checklist_fragment(fragment)
    for node in list(fragment.contents):
        el.append(node)


def _sanitize_checklist_fragment(fragment: BeautifulSoup) -> None:
    for tag in list(fragment.find_all(True)):
        name = str(tag.name or "").lower()
        if name in CHECKLIST_DROP_TAGS:
            tag.decompose()
            continue
        if name == "a":
            tag.unwrap()
            continue
        if name not in CHECKLIST_ALLOWED_TAGS:
            tag.unwrap()
            continue

        if name == "img":
            src = str(tag.get("src", "")).strip()
            if not src.lower().startswith(CHECKLIST_IMAGE_SRC_PREFIXES):
                tag.decompose()
                continue
            alt = str(tag.get("alt", ""))
            tag.attrs = {
                "src": src,
                "alt": alt,
                "style": "max-width:100%;height:auto;",
            }
            continue

        tag.attrs = {}


__all__ = ["register_config_routes"]
