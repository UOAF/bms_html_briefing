from __future__ import annotations

import logging
import os
import base64
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Callable

from bs4 import BeautifulSoup, NavigableString


logger = logging.getLogger("html_brief_log")

PDF_WORKER_FLAG = "--html-brief-pdf-worker"
PDF_WORKER_START_TIMEOUT_SECONDS = 30.0

DATA_URL_RE = re.compile(r"^data:(image/(?:png|jpeg|jpg|gif|webp));base64,(.*)$", re.IGNORECASE | re.DOTALL)
TARGET_REF_CELLS = {
    "tgt1Img_src": "tgt1Ref",
    "tgt2Img_src": "tgt2Ref",
    "tgt3Img_src": "tgt3Ref",
}


@dataclass
class PdfImageArtifact:
    key: str
    path: Path
    uri: str
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None


@dataclass
class PdfExportJob:
    trace_id: str
    pdf_output_dir: Path
    temp_dir: Path
    render_name: str
    started_at: float = field(default_factory=time.perf_counter)
    source_html_path: Path | None = None
    print_html_path: Path | None = None
    pdf_temp_path: Path | None = None
    pdf_final_path: Path | None = None
    artifacts: dict[str, PdfImageArtifact] = field(default_factory=dict)
    timings_ms: dict[str, float] = field(default_factory=dict)

    @classmethod
    def create(cls, trace_id: str, pdf_output_dir: Path, temp_dir: Path) -> "PdfExportJob":
        render_name = f"index_pdf_{trace_id}"
        return cls(
            trace_id=trace_id,
            pdf_output_dir=pdf_output_dir,
            temp_dir=temp_dir,
            render_name=render_name,
            source_html_path=temp_dir / f"{render_name}.html",
            print_html_path=temp_dir / f"{render_name}_print.html",
            pdf_temp_path=temp_dir / f"kneeboard_{trace_id}.pdf",
            pdf_final_path=pdf_output_dir / "kneeboard.pdf",
        )


class PdfRenderTimeout(TimeoutError):
    def __init__(self, timeout_seconds: float, last_stage: str, pid: int | None):
        self.timeout_seconds = timeout_seconds
        self.last_stage = last_stage
        self.pid = pid
        super().__init__(
            f"WeasyPrint did not finish within {timeout_seconds}s"
            f" (last stage: {last_stage}, pid: {pid or 'unknown'})"
        )


class PdfRenderCancelled(RuntimeError):
    def __init__(self, last_stage: str, pid: int | None):
        self.last_stage = last_stage
        self.pid = pid
        super().__init__(
            f"WeasyPrint render was cancelled"
            f" (last stage: {last_stage}, pid: {pid or 'unknown'})"
        )


def content_payload_stats(content: dict[str, Any] | None) -> dict[str, Any]:
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


def _normalize_text(val: Any) -> str:
    text = BeautifulSoup("" if val is None else str(val), "html.parser").get_text("\n")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _append_editable_content(soup: BeautifulSoup, el: Any, val: Any) -> None:
    raw = "" if val is None else str(val)
    fragment = BeautifulSoup(raw, "html.parser")
    if fragment.find() is not None:
        for node in list(fragment.contents):
            if getattr(node, "name", None) in {"script", "style"}:
                continue
            el.append(node)
        return
    lines = _normalize_text(raw).split("\n")
    for idx, line in enumerate(lines):
        el.append(NavigableString(line))
        if idx != len(lines) - 1:
            el.append(soup.new_tag("br"))


def _image_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.size
    except Exception:
        return None, None


def write_data_url_artifact(data_url: str, artifact_dir: Path, key: str) -> PdfImageArtifact:
    match = DATA_URL_RE.match(data_url.strip())
    if not match:
        raise ValueError(f"Unsupported image data URL for {key}")
    mime_type = match.group(1).lower()
    encoded = match.group(2)
    ext = "jpg" if mime_type in {"image/jpeg", "image/jpg"} else mime_type.rsplit("/", 1)[1]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", key).strip("._") or "image"
    path = artifact_dir / f"{safe_key}.{ext}"
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError(f"Invalid base64 image data for {key}") from exc
    path.write_bytes(raw)
    width, height = _image_dimensions(path)
    artifact = PdfImageArtifact(
        key=key,
        path=path,
        uri=path.resolve().as_uri(),
        mime_type=mime_type,
        size_bytes=path.stat().st_size,
        width=width,
        height=height,
    )
    logger.debug(
        "PDF image artifact: key=%s path=%s mime=%s size=%dB dimensions=%sx%s",
        artifact.key,
        artifact.path,
        artifact.mime_type,
        artifact.size_bytes,
        artifact.width if artifact.width is not None else "?",
        artifact.height if artifact.height is not None else "?",
    )
    return artifact


def _replace_data_url_images_in_html(raw: str, artifact_dir: Path, key: str, artifacts: dict[str, PdfImageArtifact]) -> str:
    fragment = BeautifulSoup(raw, "html.parser")
    changed = False
    for idx, img in enumerate(fragment.find_all("img")):
        src = str(img.get("src", "")).strip()
        if not DATA_URL_RE.match(src):
            continue
        artifact_key = f"{key}_img_{idx + 1}"
        artifact = write_data_url_artifact(src, artifact_dir, artifact_key)
        artifacts[artifact_key] = artifact
        img["src"] = artifact.uri
        changed = True
    return str(fragment) if changed else raw


def materialize_pdf_artifacts(content: dict[str, Any] | None, job: PdfExportJob) -> tuple[dict[str, Any], dict[str, str]]:
    artifact_dir = job.temp_dir / "artifacts"
    source = dict(content or {})
    materialized: dict[str, Any] = {}
    pdf_artifacts: dict[str, str] = {}

    map_image = source.get("map_image")
    if isinstance(map_image, str) and map_image.strip():
        artifact = write_data_url_artifact(map_image, artifact_dir, "map_image")
        job.artifacts["map_image"] = artifact
        pdf_artifacts["map_image_uri"] = artifact.uri

    for key, value in source.items():
        if key == "map_image":
            continue
        if key in TARGET_REF_CELLS and isinstance(value, str) and DATA_URL_RE.match(value.strip()):
            artifact = write_data_url_artifact(value, artifact_dir, key)
            job.artifacts[key] = artifact
            materialized[TARGET_REF_CELLS[key]] = (
                f'<img src="{artifact.uri}" alt="" '
                'style="max-width: 100%; height: auto; width: auto; display: block; margin: 0 auto;">'
            )
            continue
        if isinstance(value, str) and "<img" in value.lower() and "data:image" in value.lower():
            materialized[key] = _replace_data_url_images_in_html(value, artifact_dir, key, job.artifacts)
            continue
        materialized[key] = value

    return materialized, pdf_artifacts


def finalize_print_html(
    html_path: Path,
    content: dict[str, Any],
    output_path: Path | None = None,
) -> Path:
    """Apply stored edits to print HTML and enforce a non-interactive PDF input."""
    started = time.perf_counter()
    stats = content_payload_stats(content)
    logger.info(
        "PDF finalize_print_html start: html=%s keys=%d map_image_len=%d target_image_keys=%d display_keys=%d text_keys=%d total_text_len=%d",
        html_path,
        stats["keys"],
        stats["map_image_len"],
        stats["target_image_keys"],
        stats["display_keys"],
        stats["text_keys"],
        stats["total_text_len"],
    )
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")

    for key, value in content.items():
        if key == "map_image" or key in TARGET_REF_CELLS:
            continue
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
                if str(value).strip().lower() == "none":
                    header_table = header.find_parent("table")
                    if header_table:
                        header_table["style"] = "display:none"
                    else:
                        header["style"] = "display:none"
            continue

        el = soup.find(id=key)
        if el is None:
            continue
        el.clear()
        _append_editable_content(soup, el, value)

    for script in soup.find_all("script"):
        script.decompose()
    for tag_name in ("button", "input", "select", "textarea", "option"):
        for tag in soup.find_all(tag_name):
            tag.decompose()
    for link in soup.find_all("link"):
        href = str(link.get("href", ""))
        rel = " ".join(link.get("rel", []) if isinstance(link.get("rel"), list) else [str(link.get("rel", ""))]).lower()
        if "stylesheet" not in rel or "leaflet" in href.lower():
            link.unwrap()
    for style_tag in soup.find_all("style"):
        style_text = style_tag.get_text()
        if "leaflet-" in style_text or "Map Overlay Mono" in style_text:
            style_tag.decompose()
    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            if attr.lower().startswith("on"):
                del tag.attrs[attr]
            elif attr.lower() == "contenteditable":
                del tag.attrs[attr]

    rendered = str(soup)
    lower_rendered = rendered.lower()
    if "<script" in lower_rendered:
        raise RuntimeError("Print HTML still contains a script tag")
    if "leaflet" in lower_rendered:
        raise RuntimeError("Print HTML still contains Leaflet references")
    if "data:image" in lower_rendered:
        raise RuntimeError("Print HTML still contains inline image data")

    patched = output_path or html_path
    patched.write_text(str(soup), encoding="utf-8")
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    try:
        patched_size = patched.stat().st_size
    except Exception:
        patched_size = -1
    logger.info(
        "PDF finalize_print_html done: patched=%s size=%dB elapsed_ms=%.1f",
        patched,
        patched_size,
        elapsed_ms,
    )
    return patched


class PdfWorkerProcess:
    """Small compatibility wrapper used by the route's existing cancel logic."""

    def __init__(self, process: subprocess.Popen[Any]):
        self._process = process

    @property
    def pid(self) -> int | None:
        return self._process.pid

    @property
    def exitcode(self) -> int | None:
        return self._process.poll()

    def is_alive(self) -> bool:
        return self._process.poll() is None

    def join(self, timeout: float | None = None) -> None:
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass

    def terminate(self) -> None:
        if self.is_alive():
            self._process.terminate()

    def kill(self) -> None:
        if self.is_alive():
            self._process.kill()


def _pdf_worker_command(
    html_path: Path,
    base_url: Path,
    pdf_path: Path,
    result_path: Path,
    progress_path: Path,
) -> list[str]:
    worker_args = [
        "--html",
        str(html_path),
        "--base-url",
        str(base_url),
        "--pdf",
        str(pdf_path),
        "--result",
        str(result_path),
        "--progress",
        str(progress_path),
    ]
    if getattr(sys, "frozen", False):
        return [sys.executable, PDF_WORKER_FLAG, *worker_args]
    return [sys.executable, str(Path(__file__).with_name("pdf_worker.py")), *worker_args]


def _launch_pdf_worker(command: list[str]) -> PdfWorkerProcess:
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creation_flags,
    )
    return PdfWorkerProcess(process)


def _stop_worker_process(process: Any, *, reason: str) -> None:
    pid = getattr(process, "pid", None)
    try:
        if not process.is_alive():
            return
        logger.warning("Stopping PDF worker: pid=%s reason=%s", pid, reason)
        process.terminate()
        process.join(10)
        if process.is_alive():
            logger.error("PDF worker still alive after terminate; killing pid=%s", pid)
            process.kill()
            process.join(5)
    except Exception as exc:
        logger.warning("Could not stop PDF worker pid=%s reason=%s: %s", pid, reason, exc)


def _launch_worker_with_watchdog(
    command: list[str],
    timeout_seconds: float,
    is_cancel_requested: Callable[[], bool] | None,
) -> PdfWorkerProcess:
    launch_done = Event()
    abandoned = Event()
    cleanup_lock = Lock()
    state: dict[str, Any] = {}
    cleanup_claimed = False

    def cleanup_late_process() -> None:
        nonlocal cleanup_claimed
        with cleanup_lock:
            if cleanup_claimed:
                return
            process = state.get("process")
            if process is None:
                return
            cleanup_claimed = True
        _stop_worker_process(process, reason="abandoned process launch")

    def launch() -> None:
        try:
            state["process"] = _launch_pdf_worker(command)
        except BaseException as exc:
            state["error"] = exc
        finally:
            launch_done.set()
        if abandoned.is_set():
            cleanup_late_process()

    Thread(target=launch, name="html-brief-pdf-worker-launch", daemon=True).start()
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while not launch_done.is_set():
        if is_cancel_requested is not None and is_cancel_requested():
            abandoned.set()
            if launch_done.is_set():
                cleanup_late_process()
            raise PdfRenderCancelled("process_start", None)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            abandoned.set()
            if launch_done.is_set():
                cleanup_late_process()
            raise PdfRenderTimeout(timeout_seconds, "process_start", None)
        launch_done.wait(min(0.1, remaining))

    if is_cancel_requested is not None and is_cancel_requested():
        abandoned.set()
        cleanup_late_process()
        raise PdfRenderCancelled("process_start", getattr(state.get("process"), "pid", None))
    if "error" in state:
        error = state["error"]
        if isinstance(error, Exception):
            raise error
        raise RuntimeError(f"PDF worker launch failed: {error!r}")
    process = state.get("process")
    if process is None:
        raise RuntimeError("PDF worker launch finished without a process")
    return process


def _read_worker_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _read_worker_progress(path: Path, last_stage: str) -> str:
    event = _read_worker_json(path)
    stage = event.get("stage") if event else None
    return str(stage) if stage else last_stage


def render_pdf_isolated(
    html_path: Path,
    base_url: Path,
    pdf_path: Path,
    timeout_seconds: int,
    *,
    on_process_start: Callable[[PdfWorkerProcess], None] | None = None,
    on_process_done: Callable[[], None] | None = None,
    is_cancel_requested: Callable[[], bool] | None = None,
    process_start_timeout_seconds: float = PDF_WORKER_START_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    result_path = pdf_path.with_name(f".{pdf_path.name}.worker-result.json")
    progress_path = pdf_path.with_name(f".{pdf_path.name}.worker-progress.json")
    for marker_path in (result_path, progress_path):
        try:
            marker_path.unlink(missing_ok=True)
        except OSError:
            pass
    command = _pdf_worker_command(html_path, base_url, pdf_path, result_path, progress_path)
    process: PdfWorkerProcess | None = None
    try:
        process = _launch_worker_with_watchdog(
            command,
            process_start_timeout_seconds,
            is_cancel_requested,
        )
        if on_process_start is not None:
            try:
                on_process_start(process)
            except Exception:
                _stop_worker_process(process, reason="process registration failed")
                raise
        logger.debug(
            "WeasyPrint worker process started: pid=%s parent_pid=%s start_timeout_s=%s render_timeout_s=%d",
            process.pid,
            os.getpid(),
            process_start_timeout_seconds,
            timeout_seconds,
        )
        last_stage = "process_started"
        ready_stages = {"import_weasyprint_done", "render_start", "render_done", "write_pdf_start", "write_pdf_done"}
        bootstrap_deadline = time.monotonic() + process_start_timeout_seconds
        while process.is_alive() and last_stage not in ready_stages:
            if is_cancel_requested is not None and is_cancel_requested():
                _stop_worker_process(process, reason="PDF cancellation during worker bootstrap")
                raise PdfRenderCancelled(last_stage, process.pid)
            remaining = bootstrap_deadline - time.monotonic()
            if remaining <= 0:
                logger.error(
                    "WeasyPrint worker bootstrap timeout: pid=%s last_stage=%s timeout_s=%s",
                    process.pid,
                    last_stage,
                    process_start_timeout_seconds,
                )
                _stop_worker_process(process, reason=f"{process_start_timeout_seconds}s bootstrap timeout")
                raise PdfRenderTimeout(process_start_timeout_seconds, last_stage, process.pid)
            process.join(min(0.1, remaining))
            last_stage = _read_worker_progress(progress_path, last_stage)

        deadline = time.monotonic() + timeout_seconds
        while process.is_alive():
            if is_cancel_requested is not None and is_cancel_requested():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            process.join(min(0.25, remaining))
            last_stage = _read_worker_progress(progress_path, last_stage)
        last_stage = _read_worker_progress(progress_path, last_stage)
        if is_cancel_requested is not None and is_cancel_requested():
            logger.warning(
                "WeasyPrint worker cancellation requested: pid=%s last_stage=%s",
                process.pid,
                last_stage,
            )
            _stop_worker_process(process, reason="PDF cancellation")
            raise PdfRenderCancelled(last_stage, process.pid)
        if process.is_alive():
            logger.error(
                "WeasyPrint worker timeout: pid=%s last_stage=%s timeout_s=%d",
                process.pid,
                last_stage,
                timeout_seconds,
            )
            _stop_worker_process(process, reason=f"{timeout_seconds}s render timeout")
            raise PdfRenderTimeout(timeout_seconds, last_stage, process.pid)
        logger.debug(
            "WeasyPrint worker process exited: pid=%s exitcode=%s last_stage=%s",
            process.pid,
            process.exitcode,
            last_stage,
        )
        result = _read_worker_json(result_path)
        if result is None:
            raise RuntimeError(f"WeasyPrint worker exited with code {process.exitcode} without a result")
        if not result.get("ok"):
            worker_traceback = result.get("traceback")
            if worker_traceback:
                logger.debug("WeasyPrint worker traceback:\n%s", worker_traceback)
            raise RuntimeError(result.get("error") or "WeasyPrint worker failed")
        return result
    finally:
        if on_process_done is not None:
            on_process_done()


__all__ = [
    "content_payload_stats",
    "finalize_print_html",
    "materialize_pdf_artifacts",
    "PdfExportJob",
    "PdfImageArtifact",
    "PdfRenderCancelled",
    "PdfRenderTimeout",
    "PdfWorkerProcess",
    "render_pdf_isolated",
    "write_data_url_artifact",
]
