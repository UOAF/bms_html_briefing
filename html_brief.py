import configparser
import logging
import os
import sys
import time
import multiprocessing
from contextlib import asynccontextmanager
from threading import Thread
from pathlib import Path
from typing import Dict, Optional
import webbrowser

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from lib.bms_config import BmsConfig
from lib.server.cam_routes import register_cam_routes
from lib.server.config_routes import register_config_routes
from lib.server.export_routes import register_export_routes
from lib.server.file_routes import register_file_routes
from lib.server.pdf_routes import register_pdf_routes
from lib.server.render_routes import (
    register_render_routes,
)
from lib.server.runtime import run_cli
from lib.server.state import initialize_app_state

logger = logging.getLogger("html_brief_log")
logger_ui = logging.getLogger("ui_logger")
logger.addHandler(logging.NullHandler())
logger_ui.addHandler(logging.NullHandler())

IS_FROZEN = getattr(sys, "frozen", False)
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))  # where bundled assets live
RUN_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else BUNDLE_DIR  # writable location beside the entrypoint
STATIC_ROOT = BUNDLE_DIR if (BUNDLE_DIR / "assets").exists() else RUN_DIR

os.environ.setdefault("BMS_BRIEF_HOME", str(STATIC_ROOT))

PDF_RENDER_TIMEOUT_SECONDS = int(os.environ.get("BMS_HTML_BRIEF_PDF_TIMEOUT", "240"))

DEFAULT_CONFIG_PATH = RUN_DIR / "config.ini"
WEB_DIR = STATIC_ROOT / "web"
KNEEBOARDS_DIR = RUN_DIR / "kneeboards"


def config_bool(cfg: configparser.ConfigParser, section: str, key: str, default: bool = False) -> bool:
    try:
        return cfg.getboolean(section, key, fallback=default)
    except ValueError:
        return default


def configure_debug_file_logging(cfg: configparser.ConfigParser, *, reset: bool = False) -> None:
    debug_enabled = config_bool(cfg, "system", "debug_log", False)
    root_logger = logging.getLogger()

    for handler in list(root_logger.handlers):
        if getattr(handler, "_html_brief_debug_file", False):
            root_logger.removeHandler(handler)
            handler.close()

    logger.setLevel(logging.DEBUG if debug_enabled else logging.INFO)
    logger_ui.setLevel(logging.INFO)

    if not debug_enabled:
        return

    debug_path = RUN_DIR / "debug.log"
    mode = "w" if reset and multiprocessing.current_process().name == "MainProcess" else "a"
    file_handler = logging.FileHandler(debug_path, mode=mode, encoding="utf-8")
    file_handler._html_brief_debug_file = True
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root_logger.addHandler(file_handler)
    root_logger.setLevel(logging.DEBUG)
    logger.debug("Debug file logging enabled: %s", debug_path)


def build_default_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg["system"] = {
        "output_dir": str(RUN_DIR / "output"),
        "pdf_output_dir": str(KNEEBOARDS_DIR),
        "wine_prefix": "",
        "auto_export_on_change": "False",
        "auto_export_pdf_only": "False",
        "debug_log": "False",
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


def get_runtime_template_path(name: str) -> Path:
    root = RUN_DIR if IS_FROZEN else Path(os.environ.get("BMS_BRIEF_HOME", str(STATIC_ROOT)))
    return root / "templates" / name


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


def create_app(config_path: Path = DEFAULT_CONFIG_PATH, theater_ini_pattern: Optional[str] = None) -> FastAPI:
    cfg = load_config(config_path)
    configure_debug_file_logging(cfg, reset=True)
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

    initialize_app_state(
        app,
        cfg=cfg,
        bms_cfg=bms_cfg,
        config_path=config_path,
        theater_ini_pattern=theater_ini_pattern,
    )

    register_file_routes(
        app,
        static_root=STATIC_ROOT,
        web_dir=WEB_DIR,
        kneeboards_dir=KNEEBOARDS_DIR,
        resolve_path=resolve_path,
    )

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

    register_config_routes(
        app,
        ensure_dirs=ensure_dirs,
        load_config=load_config,
        save_config=save_config,
        configure_debug_file_logging=configure_debug_file_logging,
        get_runtime_template_path=get_runtime_template_path,
    )
    register_cam_routes(app, ensure_dirs=ensure_dirs, resolve_path=resolve_path)
    register_render_routes(
        app,
        ensure_dirs=ensure_dirs,
        resolve_path=resolve_path,
        copy_config_with_overrides=copy_config_with_overrides,
    )
    register_pdf_routes(
        app,
        ensure_dirs=ensure_dirs,
        resolve_path=resolve_path,
        copy_config_with_overrides=copy_config_with_overrides,
        static_root=STATIC_ROOT,
        pdf_render_timeout_seconds=PDF_RENDER_TIMEOUT_SECONDS,
    )
    register_export_routes(
        app,
        ensure_dirs=ensure_dirs,
        copy_config_with_overrides=copy_config_with_overrides,
    )

    return app


app = create_app()


if __name__ == "__main__":
    run_cli(
        create_app=create_app,
        default_config_path=DEFAULT_CONFIG_PATH,
        static_root=STATIC_ROOT,
        is_frozen=IS_FROZEN,
    )
