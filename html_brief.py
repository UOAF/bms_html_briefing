import argparse
import configparser
import json
import logging
import os
import sys
import tempfile
import time
import uuid
import multiprocessing
from contextlib import asynccontextmanager
from collections import deque
from itertools import count
from threading import Event, Lock, Thread
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
try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None
try:
    import pystray
except Exception:  # pragma: no cover - optional dependency
    pystray = None

from lib.bms_config import BmsConfig
from lib.campaign_paths import campaign_dirs
from lib.cam_integration import CamIntegrationError, extract_cam_brief_data
from lib.html_gen import generate_html_file, page_contents_ini_to_list
from lib.kneeboard_export import export_kneeboards

logger = logging.getLogger("html_brief_log")
logger_ui = logging.getLogger("ui_logger")
logging.basicConfig(
    filename="debug.log",
    filemode="w" if multiprocessing.current_process().name == "MainProcess" else "a",
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

PDF_RENDER_TIMEOUT_SECONDS = int(os.environ.get("BMS_HTML_BRIEF_PDF_TIMEOUT", "240"))

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


def _attach_handler_once(logger_obj: logging.Logger, handler: logging.Handler) -> None:
    if any(existing is handler for existing in logger_obj.handlers):
        return
    logger_obj.addHandler(handler)


def configure_weasyprint_logging(ui_handler: logging.Handler) -> None:
    weasy_logger = logging.getLogger("weasyprint")
    progress_logger = logging.getLogger("weasyprint.progress")

    weasy_logger.setLevel(logging.INFO)
    progress_logger.setLevel(logging.INFO)

    # Let the root logger keep writing these messages to debug.log.
    weasy_logger.propagate = True
    progress_logger.propagate = True

    # Mirror WeasyPrint and its progress messages in the in-app UI log.
    _attach_handler_once(weasy_logger, ui_handler)
    _attach_handler_once(progress_logger, ui_handler)


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
    selected_package_index: Optional[int] = None


class PreviewRequest(BaseModel):
    pages: Optional[Dict[str, str]] = None
    bms: Optional[Dict[str, str]] = None
    system: Optional[Dict[str, str]] = None
    theater: Optional[Dict[str, Any]] = None
    selected_package_index: Optional[int] = None


class TheaterUpdate(BaseModel):
    target_folder: Optional[str] = None
    map_file: Optional[str] = None
    copy_to_kto: Optional[bool] = None


class CamLoadLocalRequest(BaseModel):
    path: str


class CustomChecklistSaveRequest(BaseModel):
    values: Dict[str, Any]


def build_default_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg["system"] = {
        "output_dir": str(RUN_DIR / "output"),
        "pdf_output_dir": str(KNEEBOARDS_DIR),
        "wine_prefix": "",
        "auto_export_on_change": "False",
        "auto_export_pdf_only": "False",
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


def append_sanitized_html(el: Any, raw: Any) -> None:
    fragment = BeautifulSoup("" if raw is None else str(raw), "html.parser")
    for node in list(fragment.contents):
        if getattr(node, "name", None) in {"script", "style"}:
            continue
        el.append(node)


def _render_pdf_worker(html_filename: str, base_url: str, pdf_filename: str, result_queue: Any) -> None:
    """Run WeasyPrint in a child process so a native Windows layout hang is killable."""
    try:
        from weasyprint import HTML as WorkerHTML

        started = time.perf_counter()
        pdf_doc = WorkerHTML(filename=html_filename, base_url=base_url).render()
        render_elapsed_ms = (time.perf_counter() - started) * 1000.0
        page_count = len(pdf_doc.pages)
        started = time.perf_counter()
        pdf_doc.write_pdf(pdf_filename)
        write_elapsed_ms = (time.perf_counter() - started) * 1000.0
        result_queue.put(
            {
                "ok": True,
                "pages": page_count,
                "render_elapsed_ms": render_elapsed_ms,
                "write_elapsed_ms": write_elapsed_ms,
            }
        )
    except Exception as exc:
        try:
            result_queue.put({"ok": False, "error": repr(exc)})
        except Exception:
            pass


def render_pdf_isolated(html_path: Path, base_url: Path, pdf_path: Path, timeout_seconds: int) -> Dict[str, Any]:
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue(maxsize=1)
    process = ctx.Process(
        target=_render_pdf_worker,
        args=(str(html_path), str(base_url), str(pdf_path), result_queue),
        name="html-brief-weasyprint",
    )
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join(5)
        raise TimeoutError(f"WeasyPrint did not finish within {timeout_seconds}s")
    if process.exitcode not in (0, None) and result_queue.empty():
        raise RuntimeError(f"WeasyPrint worker exited with code {process.exitcode}")
    try:
        result = result_queue.get_nowait()
    except Exception as exc:
        raise RuntimeError("WeasyPrint worker finished without a result") from exc
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "WeasyPrint worker failed")
    return result


def get_runtime_template_path(name: str) -> Path:
    root = RUN_DIR if IS_FROZEN else Path(os.environ.get("BMS_BRIEF_HOME", str(STATIC_ROOT)))
    return root / "templates" / name


def serialize_config(cfg: configparser.ConfigParser) -> Dict[str, Dict[str, str]]:
    return {section: dict(cfg[section]) for section in cfg.sections()}


def ensure_dirs(cfg: configparser.ConfigParser) -> None:
    resolve_path(cfg["system"]["output_dir"]).mkdir(parents=True, exist_ok=True)
    resolve_path(cfg["system"]["pdf_output_dir"]).mkdir(parents=True, exist_ok=True)
    # Static /kneeboards mount requires the directory to exist even if the configured
    # PDF output path points somewhere else.
    KNEEBOARDS_DIR.mkdir(parents=True, exist_ok=True)


def _content_payload_stats(content: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(content, dict):
        return {
            "keys": 0,
            "map_image_len": 0,
            "target_image_keys": 0,
            "display_keys": 0,
            "text_keys": 0,
            "total_text_len": 0,
        }
    keys = len(content)
    map_image = content.get("map_image")
    map_image_len = len(map_image) if isinstance(map_image, str) else 0
    target_image_keys = 0
    display_keys = 0
    text_keys = 0
    total_text_len = 0
    for key, value in content.items():
        if key.endswith("_src") and isinstance(value, str):
            target_image_keys += 1
        elif key.endswith("_display"):
            display_keys += 1
        elif isinstance(value, str):
            text_keys += 1
            total_text_len += len(value)
    return {
        "keys": keys,
        "map_image_len": map_image_len,
        "target_image_keys": target_image_keys,
        "display_keys": display_keys,
        "text_keys": text_keys,
        "total_text_len": total_text_len,
    }


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


def apply_content_edits(html_path: Path, content: Dict[str, Any], patched_path: Optional[Path] = None) -> Path:
    """Apply stored contenteditable values and hide states to generated HTML."""
    started = time.perf_counter()
    stats = _content_payload_stats(content)
    logger.info(
        "PDF apply_content_edits start: html=%s keys=%d map_image_len=%d target_image_keys=%d display_keys=%d text_keys=%d total_text_len=%d",
        html_path,
        stats["keys"],
        stats["map_image_len"],
        stats["target_image_keys"],
        stats["display_keys"],
        stats["text_keys"],
        stats["total_text_len"],
    )
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")

    def normalize_text(val: Any) -> str:
        text = BeautifulSoup("" if val is None else str(val), "html.parser").get_text("\n")
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def append_editable_content(el: Any, val: Any) -> None:
        raw = "" if val is None else str(val)
        fragment = BeautifulSoup(raw, "html.parser")
        if fragment.find() is not None:
            for node in list(fragment.contents):
                if getattr(node, "name", None) in {"script", "style"}:
                    continue
                el.append(node)
            return
        lines = normalize_text(raw).split("\n")
        for idx, line in enumerate(lines):
            el.append(NavigableString(line))
            if idx != len(lines) - 1:
                el.append(soup.new_tag("br"))
    # Replace map with captured image if provided
    if content.get("map_image"):
        map_container = soup.find(id="image-map")
        if map_container:
            img_tag = soup.new_tag("img", id="map-image-print")
            img_tag["src"] = content["map_image"]
            img_tag["style"] = "display:block;max-width:100%;width:auto;max-height:960px;height:auto;margin:0 auto;"
            map_container.attrs.pop("class", None)
            map_container["style"] = "width:100%;height:auto;max-height:960px;text-align:center;overflow:hidden;"
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
                display_value = str(value).strip().lower()
                if display_value in {"none", "block", "inline", "inline-block", "table", "table-row", "table-cell", "flex"}:
                    rules.append(f"display:{display_value}")
                if rules:
                    el["style"] = ";".join(rules)
                else:
                    el.attrs.pop("style", None)
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
        append_editable_content(el, value)

    for script in soup.find_all("script"):
        script.decompose()
    for link in soup.find_all("link"):
        href = str(link.get("href", ""))
        media = str(link.get("media", "")).strip().lower()
        rel = " ".join(link.get("rel", []) if isinstance(link.get("rel"), list) else [str(link.get("rel", ""))]).lower()
        if "stylesheet" not in rel or media == "screen" or "leaflet" in href:
            # BeautifulSoup's html.parser can treat self-closing <link /> tags as
            # containers. Preserve any following inline style/script nodes that
            # were accidentally parsed as children.
            link.unwrap()
    for style_tag in soup.find_all("style"):
        style_text = style_tag.get_text()
        if "leaflet-" in style_text or "Map Overlay Mono" in style_text:
            style_tag.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith("on"):
                del tag.attrs[attr]

    patched = patched_path or (html_path.parent / "index_print.html")
    patched.write_text(str(soup), encoding="utf-8")
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    try:
        patched_size = patched.stat().st_size
    except Exception:
        patched_size = -1
    logger.info(
        "PDF apply_content_edits done: patched=%s size=%dB elapsed_ms=%.1f",
        patched,
        patched_size,
        elapsed_ms,
    )
    return patched


def create_app(config_path: Path = DEFAULT_CONFIG_PATH, theater_ini_pattern: Optional[str] = None) -> FastAPI:
    cfg = load_config(config_path)
    ensure_dirs(cfg)
    try:
        bms_cfg = BmsConfig(cfg, theater_ini_pattern=theater_ini_pattern)
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
    configure_weasyprint_logging(ui_handler)

    app.state.cfg = cfg
    app.state.bms_cfg = bms_cfg
    app.state.config_path = config_path
    app.state.theater_ini_pattern = theater_ini_pattern
    app.state.ui_handler = ui_handler
    app.state.brief_mtime_ref: Optional[float] = None
    app.state.callsign_mtime_ref: Optional[float] = None
    app.state.brief_pages_ref: Optional[int] = None
    app.state.pdf_page_count: Optional[int] = None
    app.state.pdf_overflow: Optional[bool] = None
    app.state.auto_open_url: Optional[str] = None
    app.state.last_pdf_path: Optional[str] = None
    app.state.last_brief_path: Optional[str] = None
    app.state.last_brief_summary_path: Optional[str] = None
    app.state.last_brief_summary: Optional[Dict[str, Any]] = None
    app.state.last_selected_package_index: Optional[int] = None
    app.state.instance_id = uuid.uuid4().hex
    app.state.pdf_busy = False
    app.state.pdf_lock = Lock()
    app.state.shutdown_callback = None
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
            "center_latitude": getattr(bms, "theater_center_latitude", None),
            "center_longitude": getattr(bms, "theater_center_longitude", None),
            "center_source": getattr(bms, "theater_center_source", ""),
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
                append_sanitized_html(el, value)
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
        app.state.bms_cfg = BmsConfig(app.state.cfg, theater_ini_pattern=app.state.theater_ini_pattern)
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
            app.state.bms_cfg = BmsConfig(app.state.cfg, theater_ini_pattern=app.state.theater_ini_pattern)
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
        return {"status": "ok", "base_dir": getattr(app.state.bms_cfg, 'base_dir', ""), "theater": getattr(app.state.bms_cfg, 'theater', "")}

    @app.post("/api/quit")
    def quit_app() -> Dict[str, str]:
        shutdown_callback = getattr(app.state, "shutdown_callback", None)
        if shutdown_callback is None:
            raise HTTPException(status_code=503, detail="Quit is not available")

        def delayed_shutdown() -> None:
            time.sleep(0.2)
            try:
                shutdown_callback()
            except Exception:
                logger.exception("Failed to shut down application from UI request")

        Thread(target=delayed_shutdown, name="html-brief-ui-quit", daemon=True).start()
        return {"status": "ok"}

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

    cam_suffixes = {".cam", ".trn", ".tac"}

    def _resolve_cam_context() -> tuple[Optional[str], Optional[str], Optional[str], list[Path]]:
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

    def _path_within(path: Path, base: Path) -> bool:
        try:
            path.relative_to(base)
            return True
        except ValueError:
            return False

    def _resolve_brief_render_state(request_index: Optional[int]) -> tuple[Optional[Dict[str, Any]], Optional[int]]:
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

    @app.get("/api/cam/saves")
    def list_cam_saves() -> Dict[str, Any]:
        _, _, _, campaign_dirs = _resolve_cam_context()
        saves: list[dict[str, Any]] = []
        seen: set[Path] = set()
        for directory in campaign_dirs:
            try:
                for candidate in directory.iterdir():
                    if not candidate.is_file():
                        continue
                    suffix = candidate.suffix.lower()
                    if suffix not in cam_suffixes:
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
            "campaign_dirs": [str(path) for path in campaign_dirs],
            "allowed_extensions": sorted(cam_suffixes),
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
        if suffix not in cam_suffixes:
            raise HTTPException(status_code=400, detail="Only .cam/.trn/.tac files are supported")

        bms_base_dir, theater_target_folder, theater_name, campaign_dirs = _resolve_cam_context()
        if not campaign_dirs:
            raise HTTPException(status_code=400, detail="No campaign directories resolved from BMS config")
        if not any(_path_within(source_path, directory) for directory in campaign_dirs):
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
        except CamIntegrationError as exc:
            logger.error("CAM integration error: %s", exc)
            raise HTTPException(status_code=500, detail=f"CAM integration failed: {exc}") from exc
        except Exception as exc:
            logger.error("CAM parsing failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Failed to parse CAM file: {exc}") from exc

        json_path = output_dir / "summary.json"
        json_path.write_text(json.dumps(cam_data, indent=2), encoding="utf-8")

        app.state.last_brief_summary_path = str(json_path)
        app.state.last_brief_summary = cam_data
        packages = cam_data.get("packages")
        app.state.last_selected_package_index = 0 if isinstance(packages, list) and packages else None

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

    @app.post("/api/generate")
    def generate(payload: PreviewRequest = None) -> Dict[str, str]:
        if app.state.bms_cfg is None:
            raise HTTPException(status_code=500, detail="BMS config is not loaded. Reload and try again.")
        overrides = payload.model_dump(exclude_none=True) if payload else {}
        cfg_generate = copy_config_with_overrides(app.state.cfg, pages=overrides.get("pages"), bms=overrides.get("bms"), system=overrides.get("system"))
        try:
            bms_cfg_generate = BmsConfig(cfg_generate, theater_ini_pattern=app.state.theater_ini_pattern)
        except Exception as exc:
            logger.error("Failed to build generate BMS config: %s", exc)
            raise HTTPException(status_code=500, detail=f"Generate config error: {exc}")
        ensure_dirs(cfg_generate)
        try:
            brief_summary, selected_package_index = _resolve_brief_render_state(getattr(payload, "selected_package_index", None) if payload else None)
            generate_html_file(
                cfg_generate,
                bms_cfg_generate,
                "index",
                brief_summary=brief_summary,
                selected_package_index=selected_package_index,
            )
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
            bms_cfg_preview = BmsConfig(cfg_preview, theater_ini_pattern=app.state.theater_ini_pattern)
        except Exception as exc:
            logger.error("Failed to build preview BMS config: %s", exc)
            raise HTTPException(status_code=500, detail=f"Preview config error: {exc}")
        ensure_dirs(cfg_preview)
        try:
            brief_summary, selected_package_index = _resolve_brief_render_state(payload.selected_package_index)
            generate_html_file(
                cfg_preview,
                bms_cfg_preview,
                "index",
                brief_summary=brief_summary,
                selected_package_index=selected_package_index,
            )
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
        pdf_trace = uuid.uuid4().hex[:8]
        req_started = time.perf_counter()
        output_file: Optional[Path] = None
        patched_html: Optional[Path] = None
        pdf_temp_path: Optional[Path] = None
        pdf_path: Optional[Path] = None
        payload_stats = _content_payload_stats(payload.content)
        logger.info(
            "PDF[%s] request start: selected_package_index=%r cam_loaded=%s payload_keys=%d map_image_len=%d target_image_keys=%d display_keys=%d text_keys=%d total_text_len=%d",
            pdf_trace,
            payload.selected_package_index,
            isinstance(app.state.last_brief_summary, dict),
            payload_stats["keys"],
            payload_stats["map_image_len"],
            payload_stats["target_image_keys"],
            payload_stats["display_keys"],
            payload_stats["text_keys"],
            payload_stats["total_text_len"],
        )
        logger_ui.info(
            "PDF[%s] start: selected_package_index=%r map_image_len=%d keys=%d",
            pdf_trace,
            payload.selected_package_index,
            payload_stats["map_image_len"],
            payload_stats["keys"],
        )
        cfg_pdf = copy_config_with_overrides(app.state.cfg, pages=payload.pages, bms=payload.bms, system=payload.system)
        try:
            bms_cfg_pdf = BmsConfig(cfg_pdf, theater_ini_pattern=app.state.theater_ini_pattern)
        except Exception as exc:
            logger.error("Failed to build PDF BMS config: %s", exc)
            raise HTTPException(status_code=500, detail=f"PDF config error: {exc}")
        pdf_lock = app.state.pdf_lock
        if not pdf_lock.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="PDF generation already in progress. Wait for the current export to finish.")
        app.state.pdf_busy = True
        ensure_dirs(cfg_pdf)
        try:
            step_started = time.perf_counter()
            brief_summary, selected_package_index = _resolve_brief_render_state(payload.selected_package_index)
            logger.info(
                "PDF[%s] render state resolved: selected_package_index=%r package_count=%d elapsed_ms=%.1f",
                pdf_trace,
                selected_package_index,
                len(brief_summary.get("packages", [])) if isinstance(brief_summary, dict) and isinstance(brief_summary.get("packages"), list) else 0,
                (time.perf_counter() - step_started) * 1000.0,
            )

            pdf_output_dir = resolve_path(cfg_pdf["system"]["pdf_output_dir"])
            pdf_output_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix=f"html_brief_pdf_{pdf_trace}_",
                dir=str(pdf_output_dir),
            ) as temp_dir_str:
                temp_dir = Path(temp_dir_str)
                cfg_pdf_render = copy_config_with_overrides(
                    cfg_pdf,
                    system={"output_dir": str(temp_dir)},
                )

                step_started = time.perf_counter()
                render_name = f"index_pdf_{pdf_trace}"
                generate_html_file(
                    cfg_pdf_render,
                    bms_cfg_pdf,
                    render_name,
                    brief_summary=brief_summary,
                    selected_package_index=selected_package_index,
                )
                output_file = temp_dir / f"{render_name}.html"
                try:
                    output_size = output_file.stat().st_size
                except Exception:
                    output_size = -1
                logger.info(
                    "PDF[%s] html generated: file=%s size=%dB elapsed_ms=%.1f",
                    pdf_trace,
                    output_file,
                    output_size,
                    (time.perf_counter() - step_started) * 1000.0,
                )
                try:
                    app.state.brief_mtime_ref = os.path.getmtime(Path(bms_cfg_pdf.base_dir) / "User" / "Briefings" / "briefing.txt")
                    app.state.callsign_mtime_ref = os.path.getmtime(Path(bms_cfg_pdf.base_dir) / "User" / "Config" / f"{bms_cfg_pdf.callsign}.ini")
                except Exception:
                    pass

                step_started = time.perf_counter()
                patched_html = apply_content_edits(
                    output_file,
                    payload.content or {},
                    patched_path=temp_dir / f"{render_name}_print.html",
                )
                try:
                    patched_size = patched_html.stat().st_size
                except Exception:
                    patched_size = -1
                logger.info(
                    "PDF[%s] patched html ready: file=%s size=%dB elapsed_ms=%.1f",
                    pdf_trace,
                    patched_html,
                    patched_size,
                    (time.perf_counter() - step_started) * 1000.0,
                )
                pdf_path = pdf_output_dir / "kneeboard.pdf"
                pdf_temp_path = temp_dir / f"kneeboard_{pdf_trace}.pdf"

                logger_ui.info("PDF[%s] WeasyPrint render start", pdf_trace)
                logger.info(
                    "PDF[%s] WeasyPrint worker start: timeout_s=%d output=%s",
                    pdf_trace,
                    PDF_RENDER_TIMEOUT_SECONDS,
                    pdf_temp_path,
                )
                worker_result = render_pdf_isolated(
                    patched_html,
                    STATIC_ROOT,
                    pdf_temp_path,
                    PDF_RENDER_TIMEOUT_SECONDS,
                )
                render_elapsed_ms = float(worker_result.get("render_elapsed_ms", 0.0))
                write_elapsed_ms = float(worker_result.get("write_elapsed_ms", 0.0))
                app.state.pdf_page_count = int(worker_result["pages"])
                app.state.brief_pages_ref = len(page_contents_ini_to_list(cfg_pdf))
                app.state.pdf_overflow = (
                    app.state.brief_pages_ref is not None
                    and app.state.pdf_page_count is not None
                    and app.state.pdf_page_count > app.state.brief_pages_ref
                )
                logger.info(
                    "PDF[%s] WeasyPrint render done: pages=%d brief_pages=%r overflow=%r elapsed_ms=%.1f",
                    pdf_trace,
                    app.state.pdf_page_count,
                    app.state.brief_pages_ref,
                    app.state.pdf_overflow,
                    render_elapsed_ms,
                )
                logger_ui.info(
                    "PDF[%s] render done: pages=%d elapsed_ms=%.1f",
                    pdf_trace,
                    app.state.pdf_page_count,
                    render_elapsed_ms,
                )

                step_started = time.perf_counter()
                os.replace(pdf_temp_path, pdf_path)
                replace_elapsed_ms = (time.perf_counter() - step_started) * 1000.0
                app.state.last_pdf_path = str(pdf_path)
                try:
                    pdf_size = pdf_path.stat().st_size
                except Exception:
                    pdf_size = -1
                logger.info(
                    "PDF[%s] write_pdf done: path=%s size=%dB elapsed_ms=%.1f total_elapsed_ms=%.1f",
                    pdf_trace,
                    pdf_path,
                    pdf_size,
                    write_elapsed_ms,
                    (time.perf_counter() - req_started) * 1000.0,
                )
                logger.info(
                    "PDF[%s] replace done: elapsed_ms=%.1f",
                    pdf_trace,
                    replace_elapsed_ms,
                )
                logger_ui.info(
                    "PDF[%s] done: size=%dB total_elapsed_ms=%.1f",
                    pdf_trace,
                    pdf_size,
                    (time.perf_counter() - req_started) * 1000.0,
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("PDF[%s] failed after %.1fms", pdf_trace, (time.perf_counter() - req_started) * 1000.0)
            logger_ui.error("PDF[%s] failed: %s", pdf_trace, exc)
            raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {exc}")
        finally:
            app.state.pdf_busy = False
            pdf_lock.release()
        return {"status": "ok", "pdf_file": str(pdf_path)}

    @app.post("/api/export")
    def export(payload: PreviewRequest = None) -> Dict[str, str]:
        cfg_export = copy_config_with_overrides(app.state.cfg,
                                                pages=getattr(payload, "pages", None),
                                                bms=getattr(payload, "bms", None),
                                                system=getattr(payload, "system", None))
        try:
            bms_cfg_export = BmsConfig(cfg_export, theater_ini_pattern=app.state.theater_ini_pattern)
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


class ServerController:
    def __init__(self, app: FastAPI, host: str, port: int):
        import uvicorn

        self.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=host,
                port=port,
                reload=False,
                access_log=False,
                log_config=None,
            )
        )
        self._stopped = Event()
        self._thread = Thread(target=self._run, name="html-brief-server", daemon=True)

    def _run(self) -> None:
        try:
            self.server.run()
        except Exception:
            logger.exception("Uvicorn server stopped unexpectedly")
            raise
        finally:
            self._stopped.set()

    def start(self) -> None:
        self._thread.start()

    def run_foreground(self) -> None:
        self._run()

    def request_stop(self) -> None:
        self.server.should_exit = True

    def stop(self, timeout: float = 10.0) -> None:
        self.request_stop()
        self._thread.join(timeout=timeout)

    def wait(self, timeout: Optional[float] = None) -> bool:
        return self._stopped.wait(timeout=timeout)


def load_tray_icon_image() -> Any:
    if Image is None:
        raise RuntimeError("Pillow is not available for tray icon support")
    icon_path = STATIC_ROOT / "assets" / "icon.png"
    if not icon_path.exists():
        raise FileNotFoundError(f"Tray icon not found: {icon_path}")
    with Image.open(icon_path) as image:
        return image.copy()


def run_with_tray(app: FastAPI, host: str, port: int) -> None:
    if pystray is None:
        raise RuntimeError("pystray is not installed")

    icon_image = load_tray_icon_image()
    server = ServerController(app, host, port)
    shutting_down = Event()
    app_url = getattr(app.state, "auto_open_url", None) or f"http://{host}:{port}"
    logger.info(
        "Tray backend initialized: module=%s HAS_MENU=%s HAS_DEFAULT_ACTION=%s",
        getattr(pystray.Icon, "__module__", "unknown"),
        getattr(pystray.Icon, "HAS_MENU", None),
        getattr(pystray.Icon, "HAS_DEFAULT_ACTION", None),
    )

    def request_shutdown(icon: Any) -> None:
        if shutting_down.is_set():
            return
        shutting_down.set()
        logger.info("Tray quit requested")
        server.request_stop()
        icon.stop()

    def open_in_browser(icon: Any, item: Any) -> None:
        del icon, item
        logger.info("Tray default action triggered; opening %s", app_url)
        Thread(target=webbrowser.open, args=(app_url,), daemon=True).start()

    def on_quit(icon: Any, item: Any) -> None:
        del item
        logger.info("Tray menu action triggered: Quit")
        Thread(target=request_shutdown, args=(icon,), daemon=True).start()

    tray_icon = pystray.Icon(
        "html_brief",
        icon=icon_image,
        title="Falcon BMS HTML Briefings",
        menu=pystray.Menu(
            pystray.MenuItem("Open in Browser", open_in_browser, default=True),
            pystray.MenuItem("Quit", on_quit),
        ),
    )
    app.state.shutdown_callback = lambda: request_shutdown(tray_icon)

    def stop_tray_when_server_exits() -> None:
        server.wait()
        request_shutdown(tray_icon)

    server.start()
    Thread(target=stop_tray_when_server_exits, name="html-brief-tray-watch", daemon=True).start()
    try:
        tray_icon.run()
    finally:
        app.state.shutdown_callback = None
        server.stop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="Run the BMS briefing server")
    parser.add_argument(
        "-c",
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to config ini (default: ./config.ini beside executable)",
    )
    parser.add_argument(
        "-t",
        "--theaters",
        default=None,
        help="Theater ini path or pattern. Supports {version}, e.g. /path/theaters_{version}.ini",
    )
    parser.add_argument("-p", "--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the UI in a browser")
    tray_group = parser.add_mutually_exclusive_group()
    tray_group.add_argument("--tray", action="store_true", help="Run in the system tray")
    tray_group.add_argument("--no-tray", action="store_true", help="Disable the system tray")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = (Path.cwd() / config_path).resolve()
    app = create_app(config_path=config_path, theater_ini_pattern=args.theaters)

    if not args.no_browser:
        app.state.auto_open_url = f"http://127.0.0.1:{args.port}"

    use_tray = args.tray or (IS_FROZEN and not args.no_tray)

    if use_tray:
        run_with_tray(app, host="127.0.0.1", port=args.port)
    else:
        server = ServerController(app, host="127.0.0.1", port=args.port)
        app.state.shutdown_callback = server.request_stop
        try:
            server.run_foreground()
        finally:
            app.state.shutdown_callback = None
