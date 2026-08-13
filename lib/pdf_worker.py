from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from pathlib import Path
from typing import Any, Sequence


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temp_path, path)


def _write_progress(path: Path, stage: str) -> None:
    try:
        _write_json_atomic(
            path,
            {
                "stage": stage,
                "pid": os.getpid(),
                "time": time.time(),
            },
        )
    except OSError:
        # Progress is diagnostic only; a transient Windows file lock must not
        # turn an otherwise valid render into a failed job.
        pass


def run_pdf_worker(
    html_path: Path,
    base_url: Path,
    pdf_path: Path,
    result_path: Path,
    progress_path: Path,
) -> int:
    try:
        _write_progress(progress_path, "worker_start")
        _write_progress(progress_path, "import_weasyprint_start")
        from weasyprint import HTML as WorkerHTML

        _write_progress(progress_path, "import_weasyprint_done")
        started = time.perf_counter()
        _write_progress(progress_path, "render_start")
        pdf_doc = WorkerHTML(filename=str(html_path), base_url=str(base_url)).render()
        render_elapsed_ms = (time.perf_counter() - started) * 1000.0
        page_count = len(pdf_doc.pages)
        _write_progress(progress_path, "render_done")

        started = time.perf_counter()
        _write_progress(progress_path, "write_pdf_start")
        pdf_doc.write_pdf(str(pdf_path))
        write_elapsed_ms = (time.perf_counter() - started) * 1000.0
        _write_progress(progress_path, "write_pdf_done")
        _write_json_atomic(
            result_path,
            {
                "ok": True,
                "pages": page_count,
                "render_elapsed_ms": render_elapsed_ms,
                "write_elapsed_ms": write_elapsed_ms,
                "pid": os.getpid(),
            },
        )
        return 0
    except BaseException as exc:
        try:
            _write_json_atomic(
                result_path,
                {
                    "ok": False,
                    "error": repr(exc),
                    "traceback": traceback.format_exc(limit=20),
                    "pid": os.getpid(),
                },
            )
        except Exception:
            pass
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render one HTML Brief PDF job")
    parser.add_argument("--html", required=True, type=Path)
    parser.add_argument("--base-url", required=True, type=Path)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--progress", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_pdf_worker(
        args.html,
        args.base_url,
        args.pdf,
        args.result,
        args.progress,
    )


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_pdf_worker"]
