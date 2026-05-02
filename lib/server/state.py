from __future__ import annotations

import configparser
import logging
import uuid
from collections import deque
from itertools import count
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from fastapi import FastAPI

from lib.bms_config import BmsConfig

logger_ui = logging.getLogger("ui_logger")


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


def initialize_app_state(
    app: FastAPI,
    *,
    cfg: configparser.ConfigParser,
    bms_cfg: Optional[BmsConfig],
    config_path: Path,
    theater_ini_pattern: Optional[str],
) -> None:
    ui_handler = create_ui_log_handler()
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


def create_ui_log_handler() -> MemoryUIHandler:
    ui_handler = MemoryUIHandler()
    ui_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    ui_handler.setFormatter(ui_formatter)
    logger_ui.addHandler(ui_handler)
    return ui_handler


def _attach_handler_once(logger_obj: logging.Logger, handler: logging.Handler) -> None:
    if any(existing is handler for existing in logger_obj.handlers):
        return
    logger_obj.addHandler(handler)


def configure_weasyprint_logging(ui_handler: logging.Handler) -> None:
    weasy_logger = logging.getLogger("weasyprint")
    progress_logger = logging.getLogger("weasyprint.progress")

    weasy_logger.setLevel(logging.INFO)
    progress_logger.setLevel(logging.INFO)

    # Let the root logger keep writing these messages to debug.log when enabled.
    weasy_logger.propagate = True
    progress_logger.propagate = True

    # Mirror WeasyPrint and its progress messages in the in-app UI log.
    _attach_handler_once(weasy_logger, ui_handler)
    _attach_handler_once(progress_logger, ui_handler)


__all__ = ["MemoryUIHandler", "initialize_app_state"]
