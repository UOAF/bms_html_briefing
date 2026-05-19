from __future__ import annotations

import configparser
import logging
import time
from typing import Any

from lib.bms_config import BmsConfig
from lib.html_gen import generate_html_file
from lib.pdf_export import PdfExportJob, finalize_print_html

logger = logging.getLogger("html_brief_log")


def render_print_html(
    *,
    cfg: configparser.ConfigParser,
    bms_cfg: BmsConfig,
    job: PdfExportJob,
    content: dict[str, Any],
    pdf_artifacts: dict[str, str],
    brief_summary: dict[str, Any] | None,
    selected_package_index: int | None,
) -> None:
    """Render the dedicated PDF HTML input for WeasyPrint."""
    started = time.perf_counter()
    generate_html_file(
        cfg,
        bms_cfg,
        job.render_name,
        brief_summary=brief_summary,
        selected_package_index=selected_package_index,
        template_name="print_index.html",
        pdf_mode=True,
        pdf_artifacts=pdf_artifacts,
    )
    job.timings_ms["print_html_render"] = (time.perf_counter() - started) * 1000.0
    logger.debug(
        "PDF[%s] print html rendered: file=%s elapsed_ms=%.1f",
        job.trace_id,
        job.source_html_path,
        job.timings_ms["print_html_render"],
    )

    started = time.perf_counter()
    job.print_html_path = finalize_print_html(
        job.source_html_path,
        content,
        output_path=job.print_html_path,
    )
    job.timings_ms["print_html_finalize"] = (time.perf_counter() - started) * 1000.0
    logger.debug(
        "PDF[%s] print html finalized: file=%s elapsed_ms=%.1f",
        job.trace_id,
        job.print_html_path,
        job.timings_ms["print_html_finalize"],
    )


__all__ = ["render_print_html"]
