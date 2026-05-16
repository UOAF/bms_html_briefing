from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from lib.brief_render import build_brief_render_context
from lib.map_sources import map_selection as select_map, map_source_options as get_map_source_options
from lib.map_tiles import prepare_local_map_tiles, resolve_local_map_file
from lib.parsers.parse_callsign_ini import Callsign_ini, replace_fcc_sections, replace_icp_section, replace_laser_section, replace_nav_offsets_section
from lib.terrain_elevation import TerrainElevationError, get_terrain_elevation_feet

logger = logging.getLogger("html_brief_log")
logger_ui = logging.getLogger("ui_logger")


class DtcNavOffsetsRequest(BaseModel):
    nav_offsets: Dict[str, Any]


class DtcIcpRequest(BaseModel):
    icp_settings: Dict[str, Any]


class DtcFccRequest(BaseModel):
    fcc_settings: Dict[str, Any]


class DtcLaserRequest(BaseModel):
    laser_settings: Dict[str, Any]


def register_dtc_routes(app: FastAPI, *, static_root: Path) -> None:
    """Register DTC management pages."""

    @app.get("/dtc", response_class=HTMLResponse)
    def serve_dtc() -> HTMLResponse:
        bms_conf = app.state.bms_cfg
        if bms_conf is None:
            raise HTTPException(status_code=500, detail="BMS config is not loaded. Reload and try again.")

        callsignini_contents = _read_callsign_ini(bms_conf)

        ci = Callsign_ini(callsignini_contents)
        map_context = _build_map_context(app, bms_conf, static_root)
        templates_dir = static_root / "templates"
        env = Environment(loader=FileSystemLoader(str(templates_dir)))
        template = env.get_template("dtc.html")
        return HTMLResponse(
            template.render(
                stpt_coords=ci.steerpoints,
                tstpt_coords=ci.threat_steerpoints,
                stpt_lines=ci.steerpoint_lines,
                tgtsteerpoints=ci.tgtsteerpoints,
                wpntgts=ci.wpntgts,
                nav_offsets=ci.nav_offsets,
                icp_settings=ci.icp_settings,
                fcc_settings=ci.fcc_settings,
                laser_settings=ci.laser_settings,
                callsign=bms_conf.callsign,
                theater_name=bms_conf.theater,
                enable_map_bullseye_edit=False,
                enable_map_collapse=False,
                **map_context,
            )
        )

    @app.post("/api/dtc/nav-offsets")
    def save_dtc_nav_offsets(payload: DtcNavOffsetsRequest) -> Dict[str, str]:
        bms_conf = app.state.bms_cfg
        if bms_conf is None:
            raise HTTPException(status_code=500, detail="BMS config is not loaded. Reload and try again.")

        callsignini_location = _callsign_ini_path(bms_conf)
        callsignini_contents = _read_callsign_ini(bms_conf)
        updated_contents = replace_nav_offsets_section(callsignini_contents, payload.nav_offsets)
        try:
            with open(callsignini_location, "w", encoding="latin1", newline="") as callsignini_file:
                callsignini_file.writelines(updated_contents)
        except Exception as exc:
            logger.error("Couldn't save NAV OFFSETS to callsign.ini: %s", exc)
            logger_ui.error("Couldn't save DTC NAV OFFSETS: %s", exc)
            raise HTTPException(status_code=500, detail=f"Couldn't save NAV OFFSETS: {exc}")
        logger_ui.info("DTC NAV OFFSETS saved to %s", callsignini_location)
        return {"status": "ok"}

    @app.get("/api/dtc/icp")
    def get_dtc_icp() -> Dict[str, Dict[str, str]]:
        bms_conf = app.state.bms_cfg
        if bms_conf is None:
            raise HTTPException(status_code=500, detail="BMS config is not loaded. Reload and try again.")

        callsignini_contents = _read_callsign_ini(bms_conf)
        ci = Callsign_ini(callsignini_contents)
        return {"icp_settings": ci.icp_settings}

    @app.post("/api/dtc/icp")
    def save_dtc_icp(payload: DtcIcpRequest) -> Dict[str, str]:
        bms_conf = app.state.bms_cfg
        if bms_conf is None:
            raise HTTPException(status_code=500, detail="BMS config is not loaded. Reload and try again.")

        callsignini_location = _callsign_ini_path(bms_conf)
        callsignini_contents = _read_callsign_ini(bms_conf)
        updated_contents = replace_icp_section(callsignini_contents, payload.icp_settings)
        try:
            with open(callsignini_location, "w", encoding="latin1", newline="") as callsignini_file:
                callsignini_file.writelines(updated_contents)
        except Exception as exc:
            logger.error("Couldn't save ICP to callsign.ini: %s", exc)
            logger_ui.error("Couldn't save DTC ICP: %s", exc)
            raise HTTPException(status_code=500, detail=f"Couldn't save ICP: {exc}")
        logger_ui.info("DTC ICP saved to %s", callsignini_location)
        return {"status": "ok"}

    @app.get("/api/dtc/fcc")
    def get_dtc_fcc() -> Dict[str, Dict[str, Dict[str, str]]]:
        bms_conf = app.state.bms_cfg
        if bms_conf is None:
            raise HTTPException(status_code=500, detail="BMS config is not loaded. Reload and try again.")

        callsignini_contents = _read_callsign_ini(bms_conf)
        ci = Callsign_ini(callsignini_contents)
        return {"fcc_settings": ci.fcc_settings}

    @app.post("/api/dtc/fcc")
    def save_dtc_fcc(payload: DtcFccRequest) -> Dict[str, str]:
        bms_conf = app.state.bms_cfg
        if bms_conf is None:
            raise HTTPException(status_code=500, detail="BMS config is not loaded. Reload and try again.")

        callsignini_location = _callsign_ini_path(bms_conf)
        callsignini_contents = _read_callsign_ini(bms_conf)
        updated_contents = replace_fcc_sections(callsignini_contents, payload.fcc_settings)
        try:
            with open(callsignini_location, "w", encoding="latin1", newline="") as callsignini_file:
                callsignini_file.writelines(updated_contents)
        except Exception as exc:
            logger.error("Couldn't save FCC to callsign.ini: %s", exc)
            logger_ui.error("Couldn't save DTC FCC: %s", exc)
            raise HTTPException(status_code=500, detail=f"Couldn't save FCC: {exc}")
        logger_ui.info("DTC FCC saved to %s", callsignini_location)
        return {"status": "ok"}

    @app.post("/api/dtc/laser")
    def save_dtc_laser(payload: DtcLaserRequest) -> Dict[str, str]:
        bms_conf = app.state.bms_cfg
        if bms_conf is None:
            raise HTTPException(status_code=500, detail="BMS config is not loaded. Reload and try again.")

        callsignini_location = _callsign_ini_path(bms_conf)
        callsignini_contents = _read_callsign_ini(bms_conf)
        updated_contents = replace_laser_section(callsignini_contents, payload.laser_settings)
        try:
            with open(callsignini_location, "w", encoding="latin1", newline="") as callsignini_file:
                callsignini_file.writelines(updated_contents)
        except Exception as exc:
            logger.error("Couldn't save Laser to callsign.ini: %s", exc)
            logger_ui.error("Couldn't save DTC Laser: %s", exc)
            raise HTTPException(status_code=500, detail=f"Couldn't save Laser: {exc}")
        logger_ui.info("DTC Laser saved to %s", callsignini_location)
        return {"status": "ok"}

    @app.get("/api/dtc/elevation")
    def get_dtc_elevation(
        north_ft: float = Query(...),
        east_ft: float = Query(...),
    ) -> Dict[str, int]:
        bms_conf = app.state.bms_cfg
        if bms_conf is None:
            raise HTTPException(status_code=500, detail="BMS config is not loaded. Reload and try again.")
        try:
            elevation_ft = get_terrain_elevation_feet(
                getattr(bms_conf, "base_dir", None),
                getattr(bms_conf, "theater", None),
                north_ft,
                east_ft,
                theater_size_km=getattr(bms_conf, "theater_size_km", None),
            )
        except TerrainElevationError as exc:
            logger.warning("Couldn't resolve DTC terrain elevation: %s", exc)
            raise HTTPException(status_code=404, detail=str(exc))
        return {"elevation_ft": elevation_ft}


def _callsign_ini_path(bms_conf: Any) -> Path:
    return Path(bms_conf.base_dir) / "User" / "Config" / f"{bms_conf.callsign}.ini"


def _read_callsign_ini(bms_conf: Any) -> list[str]:
    callsignini_location = _callsign_ini_path(bms_conf)
    try:
        with open(callsignini_location, "r", encoding="latin1") as callsignini_file:
            return callsignini_file.readlines()
    except Exception as exc:
        logger.error("Couldn't load callsign.ini for DTC: %s", exc)
        raise HTTPException(status_code=500, detail=f"Couldn't load callsign.ini: {exc}")


def _build_map_context(app: FastAPI, bms_conf: Any, static_root: Path) -> dict[str, Any]:
    map_dir = static_root / "assets" / "maps"
    try:
        map_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.error("Couldn't create the map folder: %s", exc)
        logger_ui.error(f"Couldn't create the map folder: {exc}")

    map_selection = select_map(app.state.cfg)
    map_tile_max_native_zoom = 0
    map_tile_url_template = ""
    if map_selection["base_mode"] == "web":
        logger_ui.info("Using web map tiles for DTC; local map tile generation skipped.")
    else:
        map_file = resolve_local_map_file(bms_conf, str(static_root))
        local_map_tiles = prepare_local_map_tiles(map_file, str(map_dir), bms_conf.theater)
        map_tile_url_template = local_map_tiles["map_tile_url_template"]
        map_tile_max_native_zoom = local_map_tiles["map_tile_max_native_zoom"]

    render_context = build_brief_render_context(
        brief_summary=app.state.last_brief_summary if isinstance(app.state.last_brief_summary, dict) else None,
        selected_package_index=app.state.last_selected_package_index,
        theater_center={
            "lat": getattr(bms_conf, "theater_center_latitude", None),
            "lng": getattr(bms_conf, "theater_center_longitude", None),
        },
    )
    return {
        "map_id": map_selection["id"],
        "map_source_options": get_map_source_options(),
        "map_base_mode": map_selection["base_mode"],
        "web_tile_url_template": map_selection["web_tile_url_template"],
        "web_tile_attribution": map_selection["web_tile_attribution"],
        "web_tile_filter": map_selection["web_tile_filter"],
        "web_tile_layers": map_selection["web_tile_layers"],
        "web_tile_max_zoom": map_selection["web_tile_max_zoom"],
        "map_tile_max_native_zoom": map_tile_max_native_zoom,
        "map_tile_url_template": map_tile_url_template,
        "theater_center_latitude": getattr(bms_conf, "theater_center_latitude", None),
        "theater_center_longitude": getattr(bms_conf, "theater_center_longitude", None),
        "theater_size_km": getattr(bms_conf, "theater_size_km", None),
        "bullseye": render_context["bullseye"],
    }


__all__ = ["DtcFccRequest", "DtcIcpRequest", "DtcLaserRequest", "DtcNavOffsetsRequest", "register_dtc_routes"]
