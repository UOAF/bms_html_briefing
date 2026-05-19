from __future__ import annotations

import logging
import multiprocessing
import os
import base64
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString


logger = logging.getLogger("html_brief_log")

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
    def __init__(self, timeout_seconds: int, last_stage: str, pid: int | None):
        self.timeout_seconds = timeout_seconds
        self.last_stage = last_stage
        self.pid = pid
        super().__init__(
            f"WeasyPrint did not finish within {timeout_seconds}s"
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


def _queue_progress(progress_queue: Any, stage: str) -> None:
    try:
        progress_queue.put({"stage": stage, "pid": os.getpid(), "time": time.time()})
    except Exception:
        pass


def _render_pdf_worker(html_filename: str, base_url: str, pdf_filename: str, result_queue: Any, progress_queue: Any) -> None:
    """Run WeasyPrint in a child process so a native Windows layout hang is killable."""
    try:
        _queue_progress(progress_queue, "import_weasyprint_start")
        from weasyprint import HTML as WorkerHTML

        _queue_progress(progress_queue, "import_weasyprint_done")
        started = time.perf_counter()
        _queue_progress(progress_queue, "render_start")
        pdf_doc = WorkerHTML(filename=html_filename, base_url=base_url).render()
        render_elapsed_ms = (time.perf_counter() - started) * 1000.0
        page_count = len(pdf_doc.pages)
        started = time.perf_counter()
        _queue_progress(progress_queue, "write_pdf_start")
        pdf_doc.write_pdf(pdf_filename)
        write_elapsed_ms = (time.perf_counter() - started) * 1000.0
        _queue_progress(progress_queue, "write_pdf_done")
        result_queue.put(
            {
                "ok": True,
                "pages": page_count,
                "render_elapsed_ms": render_elapsed_ms,
                "write_elapsed_ms": write_elapsed_ms,
                "pid": os.getpid(),
            }
        )
    except Exception as exc:
        try:
            result_queue.put({"ok": False, "error": repr(exc), "pid": os.getpid()})
        except Exception:
            pass


def _drain_progress(progress_queue: Any, last_stage: str) -> str:
    while True:
        try:
            event = progress_queue.get_nowait()
        except Exception:
            return last_stage
        stage = event.get("stage") if isinstance(event, dict) else None
        if stage:
            last_stage = str(stage)


def render_pdf_isolated(
    html_path: Path,
    base_url: Path,
    pdf_path: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue(maxsize=1)
    progress_queue = ctx.Queue()
    process = ctx.Process(
        target=_render_pdf_worker,
        args=(str(html_path), str(base_url), str(pdf_path), result_queue, progress_queue),
        name="html-brief-weasyprint",
    )
    process.start()
    logger.debug(
        "WeasyPrint worker process started: pid=%s parent_pid=%s timeout_s=%d",
        process.pid,
        os.getpid(),
        timeout_seconds,
    )
    deadline = time.monotonic() + timeout_seconds
    last_stage = "process_started"
    while process.is_alive():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        process.join(min(0.25, remaining))
        last_stage = _drain_progress(progress_queue, last_stage)
    last_stage = _drain_progress(progress_queue, last_stage)
    if process.is_alive():
        logger.error(
            "WeasyPrint worker timeout: pid=%s last_stage=%s timeout_s=%d",
            process.pid,
            last_stage,
            timeout_seconds,
        )
        process.terminate()
        process.join(10)
        if process.is_alive():
            logger.error("WeasyPrint worker still alive after terminate; killing pid=%s", process.pid)
            process.kill()
            process.join(5)
        raise PdfRenderTimeout(timeout_seconds, last_stage, process.pid)
    logger.debug(
        "WeasyPrint worker process exited: pid=%s exitcode=%s last_stage=%s",
        process.pid,
        process.exitcode,
        last_stage,
    )
    if process.exitcode not in (0, None) and result_queue.empty():
        raise RuntimeError(f"WeasyPrint worker exited with code {process.exitcode}")
    try:
        result = result_queue.get_nowait()
    except Exception as exc:
        raise RuntimeError("WeasyPrint worker finished without a result") from exc
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "WeasyPrint worker failed")
    return result


__all__ = [
    "content_payload_stats",
    "finalize_print_html",
    "materialize_pdf_artifacts",
    "PdfExportJob",
    "PdfImageArtifact",
    "PdfRenderTimeout",
    "render_pdf_isolated",
    "write_data_url_artifact",
]
