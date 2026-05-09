from __future__ import annotations

import configparser
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

try:
    from weasyprint import HTML
except Exception:  # pragma: no cover - optional dependency
    HTML = None

from lib.bms_config import BmsConfig
from lib.html_gen import generate_html_file, page_contents_ini_to_list
from lib.pdf_export import apply_content_edits, content_payload_stats, render_pdf_isolated
from lib.server.render_routes import resolve_brief_render_state

logger = logging.getLogger("html_brief_log")
logger_ui = logging.getLogger("ui_logger")


def _pages_include_map(pages: Optional[Dict[str, str]], cfg: configparser.ConfigParser) -> bool:
    if isinstance(pages, dict):
        for value in pages.values():
            sections = [part.strip() for part in str(value or "").split(",")]
            if "map" in sections:
                return True
        return False
    try:
        return any("map" in page for page in page_contents_ini_to_list(cfg))
    except Exception:
        return False


class PdfRequest(BaseModel):
    content: Optional[Dict[str, Any]] = None
    pages: Optional[Dict[str, str]] = None
    bms: Optional[Dict[str, str]] = None
    system: Optional[Dict[str, str]] = None
    theater: Optional[Dict[str, Any]] = None
    selected_package_index: Optional[int] = None


def register_pdf_routes(
    app: FastAPI,
    *,
    ensure_dirs: Callable[[configparser.ConfigParser], None],
    resolve_path: Callable[[str], Path],
    copy_config_with_overrides: Callable[..., configparser.ConfigParser],
    static_root: Path,
    pdf_render_timeout_seconds: int,
) -> None:
    """Register PDF generation endpoint."""

    @app.post("/api/pdf")
    def generate_pdf(payload: PdfRequest) -> Dict[str, str]:
        if app.state.bms_cfg is None:
            raise HTTPException(status_code=500, detail="BMS config is not loaded. Reload and try again.")
        if HTML is None:
            raise HTTPException(status_code=500, detail="weasyprint is not installed. Install it to enable PDF generation.")
        pdf_trace = uuid.uuid4().hex[:8]
        req_started = time.perf_counter()
        pdf_lock = app.state.pdf_lock
        if not pdf_lock.acquire(blocking=False):
            logger.debug("PDF[%s] lock busy: rejecting concurrent request", pdf_trace)
            raise HTTPException(status_code=429, detail="PDF generation already in progress. Wait for the current export to finish.")
        logger.debug("PDF[%s] lock acquired", pdf_trace)
        app.state.pdf_busy = True
        output_file: Optional[Path] = None
        patched_html: Optional[Path] = None
        pdf_temp_path: Optional[Path] = None
        pdf_path: Optional[Path] = None
        try:
            payload_stats = content_payload_stats(payload.content)
            if _pages_include_map(payload.pages, app.state.cfg) and payload_stats["map_image_len"] <= 0:
                raise HTTPException(status_code=400, detail="Map capture failed; PDF generation requires a captured map image when the map page is enabled.")
            logger.debug(
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
            cfg_pdf = copy_config_with_overrides(
                app.state.cfg,
                pages=payload.pages,
                bms=payload.bms,
                system=payload.system,
            )
            try:
                bms_cfg_pdf = BmsConfig(cfg_pdf, theater_ini_pattern=app.state.theater_ini_pattern)
            except Exception as exc:
                logger.error("Failed to build PDF BMS config: %s", exc)
                raise HTTPException(status_code=500, detail=f"PDF config error: {exc}") from exc
            ensure_dirs(cfg_pdf)
            step_started = time.perf_counter()
            brief_summary, selected_package_index = resolve_brief_render_state(
                app,
                payload.selected_package_index,
            )
            logger.debug(
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
                logger.debug(
                    "PDF[%s] html generated: file=%s size=%dB elapsed_ms=%.1f",
                    pdf_trace,
                    output_file,
                    output_size,
                    (time.perf_counter() - step_started) * 1000.0,
                )
                try:
                    app.state.brief_mtime_ref = os.path.getmtime(
                        Path(bms_cfg_pdf.base_dir) / "User" / "Briefings" / "briefing.txt"
                    )
                    app.state.callsign_mtime_ref = os.path.getmtime(
                        Path(bms_cfg_pdf.base_dir) / "User" / "Config" / f"{bms_cfg_pdf.callsign}.ini"
                    )
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
                logger.debug(
                    "PDF[%s] patched html ready: file=%s size=%dB elapsed_ms=%.1f",
                    pdf_trace,
                    patched_html,
                    patched_size,
                    (time.perf_counter() - step_started) * 1000.0,
                )
                pdf_path = pdf_output_dir / "kneeboard.pdf"
                pdf_temp_path = temp_dir / f"kneeboard_{pdf_trace}.pdf"

                logger.debug("PDF[%s] WeasyPrint render start", pdf_trace)
                logger.debug(
                    "PDF[%s] WeasyPrint worker start: timeout_s=%d output=%s",
                    pdf_trace,
                    pdf_render_timeout_seconds,
                    pdf_temp_path,
                )
                worker_result = render_pdf_isolated(
                    patched_html,
                    static_root,
                    pdf_temp_path,
                    pdf_render_timeout_seconds,
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
                logger.debug(
                    "PDF[%s] WeasyPrint render done: pages=%d brief_pages=%r overflow=%r elapsed_ms=%.1f",
                    pdf_trace,
                    app.state.pdf_page_count,
                    app.state.brief_pages_ref,
                    app.state.pdf_overflow,
                    render_elapsed_ms,
                )
                logger.debug(
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
                logger.debug(
                    "PDF[%s] write_pdf done: path=%s size=%dB elapsed_ms=%.1f total_elapsed_ms=%.1f",
                    pdf_trace,
                    pdf_path,
                    pdf_size,
                    write_elapsed_ms,
                    (time.perf_counter() - req_started) * 1000.0,
                )
                logger.debug(
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
            logger.debug("PDF[%s] lock released", pdf_trace)
        return {"status": "ok", "pdf_file": str(pdf_path)}


__all__ = ["PdfRequest", "register_pdf_routes"]
