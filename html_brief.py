import argparse
import configparser
import logging
import os
import sys
from contextlib import asynccontextmanager
from collections import deque
from itertools import count
from threading import Thread
from pathlib import Path
from typing import Any, Dict, List, Optional
import webbrowser

from bs4 import BeautifulSoup, NavigableString
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
try:
    from weasyprint import HTML
except Exception:  # pragma: no cover - optional dependency
    HTML = None

from lib.bms_config import BmsConfig
from lib.html_gen import generate_html_file, page_contents_ini_to_list
from lib.kneeboard_export import export_kneeboards

logger = logging.getLogger("html_brief_log")
logger_ui = logging.getLogger("ui_logger")
logging.basicConfig(
    filename="debug.log",
    filemode="w",
    encoding="utf-8",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

IS_FROZEN = getattr(sys, "frozen", False)
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))  # where bundled assets live
RUN_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else BUNDLE_DIR  # writable location beside the entrypoint
STATIC_ROOT = BUNDLE_DIR if (BUNDLE_DIR / "assets").exists() else RUN_DIR

os.environ.setdefault("BMS_BRIEF_HOME", str(STATIC_ROOT))

DEFAULT_CONFIG_PATH = RUN_DIR / "config.ini"
WEB_DIR = STATIC_ROOT / "web"
KNEEBOARDS_DIR = RUN_DIR / "kneeboards"

class MemoryUIHandler(logging.Handler):
    """Keeps a small buffer of UI-facing log messages."""
    def __init__(self, capacity: int = 200):
        super().__init__()
        self.buffer: deque = deque(maxlen=capacity)
        self._ids = count(1)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self.buffer.append({"id": next(self._ids), "level": record.levelname, "msg": msg})


class ConfigUpdate(BaseModel):
    system: Optional[Dict[str, str]] = None
    bms: Optional[Dict[str, str]] = None
    pages: Optional[Dict[str, str]] = None


class PdfRequest(BaseModel):
    content: Optional[Dict[str, Any]] = None
    pages: Optional[Dict[str, str]] = None
    bms: Optional[Dict[str, str]] = None
    system: Optional[Dict[str, str]] = None
    theater: Optional[Dict[str, Any]] = None


class PreviewRequest(BaseModel):
    pages: Optional[Dict[str, str]] = None
    bms: Optional[Dict[str, str]] = None
    system: Optional[Dict[str, str]] = None
    theater: Optional[Dict[str, Any]] = None


class TheaterUpdate(BaseModel):
    target_folder: Optional[str] = None
    map_file: Optional[str] = None
    copy_to_kto: Optional[bool] = None


def build_default_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg["system"] = {
        "output_dir": str(RUN_DIR / "output"),
        "pdf_output_dir": str(KNEEBOARDS_DIR),
        "wine_prefix": "",
        "auto_export_on_change": "False",
    }
    cfg["bms"] = {
        "bms_version": "4.38",
        "bms_available_versions": "4.37, 4.38",
        "default_airframe": "F-16",
    }
    cfg["pages"] = {}
    return cfg


def resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = RUN_DIR / path
    return path


def load_config(config_path: Path) -> configparser.ConfigParser:
    cfg = build_default_config()
    cfg.read(config_path)
    return cfg


def save_config(cfg: configparser.ConfigParser, config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as fp:
        cfg.write(fp)


def serialize_config(cfg: configparser.ConfigParser) -> Dict[str, Dict[str, str]]:
    return {section: dict(cfg[section]) for section in cfg.sections()}


def ensure_dirs(cfg: configparser.ConfigParser) -> None:
    resolve_path(cfg["system"]["output_dir"]).mkdir(parents=True, exist_ok=True)
    resolve_path(cfg["system"]["pdf_output_dir"]).mkdir(parents=True, exist_ok=True)
    # Static /kneeboards mount requires the directory to exist even if the configured
    # PDF output path points somewhere else.
    KNEEBOARDS_DIR.mkdir(parents=True, exist_ok=True)


def copy_config_with_overrides(cfg: configparser.ConfigParser, pages: Optional[Dict[str, str]] = None,
                               bms: Optional[Dict[str, str]] = None,
                               system: Optional[Dict[str, str]] = None) -> configparser.ConfigParser:
    new_cfg = configparser.ConfigParser()
    for section in cfg.sections():
        new_cfg[section] = dict(cfg[section])
    if pages:
        new_cfg["pages"] = pages
    if bms:
        if "bms" not in new_cfg:
            new_cfg["bms"] = {}
        for k, v in bms.items():
            new_cfg["bms"][k] = v
    if system:
        if "system" not in new_cfg:
            new_cfg["system"] = {}
        for k, v in system.items():
            new_cfg["system"][k] = v
    if "system" in new_cfg:
        for key in ("output_dir", "pdf_output_dir"):
            if key in new_cfg["system"] and new_cfg["system"][key]:
                new_cfg["system"][key] = str(resolve_path(new_cfg["system"][key]))
    return new_cfg


def apply_content_edits(html_path: Path, content: Dict[str, Any]) -> Path:
    """Apply stored contenteditable values and hide states to generated HTML."""
    if not content:
        return html_path
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")

    def normalize_text(val: Any) -> str:
        text = BeautifulSoup(str(val), "html.parser").get_text("\n")
        return text.replace("\r\n", "\n").replace("\r", "\n")
    # Replace map with captured image if provided
    if content.get("map_image"):
        map_container = soup.find(id="image-map")
        if map_container:
            img_tag = soup.new_tag("img", id="map-image-print")
            img_tag["src"] = content["map_image"]
            img_tag["style"] = "width:100%;height:auto;"
            map_container.clear()
            map_container.append(img_tag)
    # Inject target reference images if provided as data URLs
    for tgt_id in ("tgt1Img", "tgt2Img", "tgt3Img"):
        data_key = tgt_id + "_src"
        if content.get(data_key):
            el = soup.find(id=tgt_id)
            if el:
                el["src"] = content[data_key]
                row = soup.find(id="refImageRow")
                if row:
                    # ensure the row is visible for PDF
                    row["style"] = "visibility: visible;"
    for key, value in content.items():
        if key.endswith("_display"):
            target_id = key.removesuffix("_display")
            el = soup.find(id=target_id)
            if el:
                style = el.get("style", "")
                rules = [r.strip() for r in style.split(";") if r.strip() and not r.strip().startswith("display")]
                rules.append(f"display:{value}")
                el["style"] = ";".join(rules)
            header = soup.find(id=f"{target_id}_header")
            if header:
                arrow = header.find(class_="arrow")
                if arrow:
                    arrow.string = "▸" if value == "none" else "▼"
            continue

        el = soup.find(id=key)
        if el is None:
            continue
        el.clear()
        text = normalize_text(value)
        lines = text.split("\n")
        for idx, line in enumerate(lines):
            el.append(NavigableString(line))
            if idx != len(lines) - 1:
                el.append(soup.new_tag("br"))

    patched = html_path.parent / "index_print.html"
    patched.write_text(str(soup), encoding="utf-8")
    return patched


def create_app(config_path: Path = DEFAULT_CONFIG_PATH) -> FastAPI:
    cfg = load_config(config_path)
    ensure_dirs(cfg)
    try:
        bms_cfg = BmsConfig(cfg)
    except Exception as exc:  # pragma: no cover - BMS paths may be missing locally
        logger.error("Failed to initialize BMS config: %s", exc)
        bms_cfg = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        url = getattr(app.state, "auto_open_url", None)
        if url:
            try:
                Thread(target=webbrowser.open, args=(url,), daemon=True).start()
            except Exception as exc:
                logger.warning("Failed to open browser automatically: %s", exc)
        yield

    app = FastAPI(title="BMS Briefing Server", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    ui_handler = MemoryUIHandler()
    ui_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    ui_handler.setFormatter(ui_formatter)
    logger_ui.addHandler(ui_handler)

    app.state.cfg = cfg
    app.state.bms_cfg = bms_cfg
    app.state.config_path = config_path
    app.state.ui_handler = ui_handler
    app.state.brief_mtime_ref: Optional[float] = None
    app.state.callsign_mtime_ref: Optional[float] = None
    app.state.brief_pages_ref: Optional[int] = None
    app.state.pdf_page_count: Optional[int] = None
    app.state.pdf_overflow: Optional[bool] = None
    app.state.auto_open_url: Optional[str] = None
    app.state.last_pdf_path: Optional[str] = None
    app.state.last_brief_path: Optional[str] = None
    app.state.brief_mtime_ref: Optional[float] = None
    app.state.callsign_mtime_ref: Optional[float] = None
    app.state.brief_pages_ref: Optional[int] = None
    app.state.pdf_page_count: Optional[int] = None
    app.state.pdf_overflow: Optional[bool] = None

    app.mount("/assets", StaticFiles(directory=STATIC_ROOT / "assets"), name="assets")
    app.mount("/templates", StaticFiles(directory=STATIC_ROOT / "templates"), name="templates")
    app.mount("/dist", StaticFiles(directory=STATIC_ROOT / "dist"), name="dist")
    app.mount("/kneeboards", StaticFiles(directory=KNEEBOARDS_DIR), name="kneeboards")
    if WEB_DIR.exists():
        app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")

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
        }

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        ui_path = WEB_DIR / "index.html"
        if not ui_path.exists():
            raise HTTPException(status_code=500, detail="UI not found. Did you delete web/index.html?")
        return HTMLResponse(ui_path.read_text(encoding="utf-8"))

    @app.get("/api/config")
    def get_config() -> Dict[str, Dict[str, str]]:
        return serialize_config(app.state.cfg)

    @app.get("/api/logs")
    def get_logs() -> JSONResponse:
        logs: List[Dict[str, str]] = list(app.state.ui_handler.buffer)
        return JSONResponse(content=logs)

    @app.post("/api/config")
    def update_config(payload: ConfigUpdate) -> Dict[str, Dict[str, str]]:
        payload_dict = payload.model_dump(exclude_none=True)
        if not payload_dict:
            raise HTTPException(status_code=400, detail="No config fields provided")
        # Keep in-memory config in sync for immediate UI/runtime behavior.
        for section, values in payload_dict.items():
            if section not in app.state.cfg:
                app.state.cfg[section] = {}
            for key, value in values.items():
                app.state.cfg[section][key] = str(value)

        # Persist only explicitly provided fields so runtime-only overrides
        # (set via /api/config/runtime) are not accidentally written to disk.
        cfg_to_persist = load_config(app.state.config_path)
        for section, values in payload_dict.items():
            if section not in cfg_to_persist:
                cfg_to_persist[section] = {}
            for key, value in values.items():
                cfg_to_persist[section][key] = str(value)
        save_config(cfg_to_persist, app.state.config_path)
        ensure_dirs(app.state.cfg)
        app.state.bms_cfg = BmsConfig(app.state.cfg)
        return serialize_config(app.state.cfg)

    @app.post("/api/config/runtime")
    def update_config_runtime(payload: ConfigUpdate) -> Dict[str, Dict[str, str]]:
        payload_dict = payload.model_dump(exclude_none=True)
        if not payload_dict:
            raise HTTPException(status_code=400, detail="No config fields provided")
        for section, values in payload_dict.items():
            if section not in app.state.cfg:
                app.state.cfg[section] = {}
            for key, value in values.items():
                app.state.cfg[section][key] = str(value)
        ensure_dirs(app.state.cfg)
        try:
            app.state.bms_cfg = BmsConfig(app.state.cfg)
        except Exception as exc:
            logger.error("Failed to reload BMS config (runtime): %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to reload BMS config: {exc}")
        return serialize_config(app.state.cfg)

    @app.post("/api/theater")
    def update_theater(payload: TheaterUpdate) -> Dict[str, Any]:
        bms = app.state.bms_cfg
        if bms is None:
            raise HTTPException(status_code=500, detail="BMS config not loaded")
        theater_cfg = configparser.ConfigParser()
        theater_ini_path = Path(bms.script_dir) / f"theaters_{bms.version}.ini"
        try:
            theater_cfg.read(theater_ini_path, encoding="utf-8")
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
        }

    @app.post("/api/reload")
    def reload_bms_config() -> Dict[str, Any]:
        try:
            app.state.bms_cfg = BmsConfig(app.state.cfg)
        except Exception as exc:
            logger.error("Failed to reload BMS config: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to reload BMS config: {exc}")
        return {"status": "ok", "base_dir": getattr(app.state.bms_cfg, 'base_dir', ""), "theater": getattr(app.state.bms_cfg, 'theater', "")}

    @app.get("/api/status")
    def status() -> Dict[str, Any]:
        bms = app.state.bms_cfg
        cfg = app.state.cfg
        data: Dict[str, Any] = {
            "config_path": str(app.state.config_path),
            "output_dir": cfg["system"]["output_dir"],
            "pdf_output_dir": cfg["system"]["pdf_output_dir"],
            "pages": page_contents_ini_to_list(cfg),
            "pdf_pages": app.state.pdf_page_count,
            "brief_pages": app.state.brief_pages_ref,
            "pdf_overflow": app.state.pdf_overflow,
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
                    "brief_changed": None if (app.state.brief_mtime_ref is None or brief_mtime is None) else brief_mtime > app.state.brief_mtime_ref,
                    "callsign_changed": None if (app.state.callsign_mtime_ref is None or callsign_mtime is None) else callsign_mtime > app.state.callsign_mtime_ref,
                }
            )
        else:
            data.update({"error": "BMS config not loaded"})
        return data

    @app.post("/api/generate")
    def generate(payload: PreviewRequest = None) -> Dict[str, str]:
        if app.state.bms_cfg is None:
            raise HTTPException(status_code=500, detail="BMS config is not loaded. Reload and try again.")
        overrides = payload.model_dump(exclude_none=True) if payload else {}
        cfg_generate = copy_config_with_overrides(app.state.cfg, pages=overrides.get("pages"), bms=overrides.get("bms"), system=overrides.get("system"))
        try:
            bms_cfg_generate = BmsConfig(cfg_generate)
        except Exception as exc:
            logger.error("Failed to build generate BMS config: %s", exc)
            raise HTTPException(status_code=500, detail=f"Generate config error: {exc}")
        ensure_dirs(cfg_generate)
        try:
            generate_html_file(cfg_generate, bms_cfg_generate, "index")
            output_file = resolve_path(cfg_generate["system"]["output_dir"]) / "index.html"
            app.state.last_brief_path = str(output_file)
            try:
                app.state.brief_mtime_ref = os.path.getmtime(Path(bms_cfg_generate.base_dir) / "User" / "Briefings" / "briefing.txt")
                app.state.callsign_mtime_ref = os.path.getmtime(Path(bms_cfg_generate.base_dir) / "User" / "Config" / f"{bms_cfg_generate.callsign}.ini")
            except Exception:
                pass
            app.state.brief_pages_ref = len(page_contents_ini_to_list(cfg_generate))
        except Exception as exc:
            logger.error("Failed to generate HTML: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to generate HTML: {exc}")
        return {"status": "ok", "output_file": str(output_file)}

    @app.post("/api/preview")
    def preview(payload: PreviewRequest) -> Dict[str, str]:
        cfg_preview = copy_config_with_overrides(app.state.cfg, pages=payload.pages, bms=payload.bms, system=payload.system)
        try:
            bms_cfg_preview = BmsConfig(cfg_preview)
        except Exception as exc:
            logger.error("Failed to build preview BMS config: %s", exc)
            raise HTTPException(status_code=500, detail=f"Preview config error: {exc}")
        ensure_dirs(cfg_preview)
        try:
            generate_html_file(cfg_preview, bms_cfg_preview, "index")
            output_file = resolve_path(cfg_preview["system"]["output_dir"]) / "index.html"
            app.state.last_brief_path = str(output_file)
            try:
                app.state.brief_mtime_ref = os.path.getmtime(Path(bms_cfg_preview.base_dir) / "User" / "Briefings" / "briefing.txt")
                app.state.callsign_mtime_ref = os.path.getmtime(Path(bms_cfg_preview.base_dir) / "User" / "Config" / f"{bms_cfg_preview.callsign}.ini")
            except Exception:
                pass
            app.state.brief_pages_ref = len(page_contents_ini_to_list(cfg_preview))
        except Exception as exc:
            logger.error("Failed to generate preview HTML: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to generate HTML: {exc}")
        return {"status": "ok", "output_file": str(output_file)}

    @app.post("/api/pdf")
    def generate_pdf(payload: PdfRequest) -> Dict[str, str]:
        if app.state.bms_cfg is None:
            raise HTTPException(status_code=500, detail="BMS config is not loaded. Reload and try again.")
        if HTML is None:
            raise HTTPException(status_code=500, detail="weasyprint is not installed. Install it to enable PDF generation.")
        cfg_pdf = copy_config_with_overrides(app.state.cfg, pages=payload.pages, bms=payload.bms, system=payload.system)
        try:
            bms_cfg_pdf = BmsConfig(cfg_pdf)
        except Exception as exc:
            logger.error("Failed to build PDF BMS config: %s", exc)
            raise HTTPException(status_code=500, detail=f"PDF config error: {exc}")
        ensure_dirs(cfg_pdf)
        try:
            generate_html_file(cfg_pdf, bms_cfg_pdf, "index")
            output_file = resolve_path(cfg_pdf["system"]["output_dir"]) / "index.html"
            app.state.last_brief_path = str(output_file)
            try:
                app.state.brief_mtime_ref = os.path.getmtime(Path(bms_cfg_pdf.base_dir) / "User" / "Briefings" / "briefing.txt")
                app.state.callsign_mtime_ref = os.path.getmtime(Path(bms_cfg_pdf.base_dir) / "User" / "Config" / f"{bms_cfg_pdf.callsign}.ini")
            except Exception:
                pass
            patched_html = apply_content_edits(output_file, payload.content or {})
            pdf_output_dir = resolve_path(cfg_pdf["system"]["pdf_output_dir"])
            pdf_output_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = pdf_output_dir / "kneeboard.pdf"
            pdf_doc = HTML(filename=str(patched_html), base_url=str(STATIC_ROOT)).render()
            app.state.pdf_page_count = len(pdf_doc.pages)
            app.state.brief_pages_ref = len(page_contents_ini_to_list(cfg_pdf))
            app.state.pdf_overflow = (
                app.state.brief_pages_ref is not None
                and app.state.pdf_page_count is not None
                and app.state.pdf_page_count > app.state.brief_pages_ref
            )
            pdf_doc.write_pdf(str(pdf_path))
            app.state.last_pdf_path = str(pdf_path)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Failed to generate PDF: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {exc}")
        return {"status": "ok", "pdf_file": str(pdf_path)}

    @app.post("/api/export")
    def export(payload: PreviewRequest = None) -> Dict[str, str]:
        cfg_export = copy_config_with_overrides(app.state.cfg,
                                                pages=getattr(payload, "pages", None),
                                                bms=getattr(payload, "bms", None),
                                                system=getattr(payload, "system", None))
        try:
            bms_cfg_export = BmsConfig(cfg_export)
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

    @app.get("/brief")
    def serve_brief() -> FileResponse:
        last_brief = getattr(app.state, "last_brief_path", None)
        output_file = Path(last_brief) if last_brief else resolve_path(app.state.cfg["system"]["output_dir"]) / "index.html"
        if not output_file.exists():
            raise HTTPException(status_code=404, detail="No generated briefing found. Run /api/generate first.")
        return FileResponse(output_file)

    @app.get("/pdf")
    def serve_pdf() -> FileResponse:
        last_pdf = getattr(app.state, "last_pdf_path", None)
        pdf_file = Path(last_pdf) if last_pdf else resolve_path(app.state.cfg["system"]["pdf_output_dir"]) / "kneeboard.pdf"
        if not pdf_file.exists():
            raise HTTPException(status_code=404, detail="No generated PDF found. Run /api/pdf first.")
        return FileResponse(pdf_file)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the BMS briefing server")
    parser.add_argument("-p", "--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the UI in a browser")
    args = parser.parse_args()

    if not args.no_browser:
        app.state.auto_open_url = f"http://127.0.0.1:{args.port}"

    uvicorn.run(app, host="127.0.0.1", port=args.port, reload=False, access_log=False, log_config = None)
