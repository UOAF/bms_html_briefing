from __future__ import annotations

import logging
import multiprocessing
import time
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, NavigableString


logger = logging.getLogger("html_brief_log")


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


def apply_content_edits(
    html_path: Path,
    content: dict[str, Any],
    patched_path: Path | None = None,
) -> Path:
    """Apply stored contenteditable values and hide states to generated HTML."""
    started = time.perf_counter()
    stats = content_payload_stats(content)
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

    for tgt_id in ("tgt1Img", "tgt2Img", "tgt3Img"):
        data_key = tgt_id + "_src"
        if content.get(data_key):
            el = soup.find(id=tgt_id)
            if el:
                el["src"] = content[data_key]
                row = soup.find(id="refImageRow")
                if row:
                    # Ensure the row is visible for PDF.
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


def render_pdf_isolated(
    html_path: Path,
    base_url: Path,
    pdf_path: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
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


__all__ = [
    "apply_content_edits",
    "content_payload_stats",
    "render_pdf_isolated",
]
