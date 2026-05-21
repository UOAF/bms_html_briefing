from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pymupdf


KNEEBOARD_ORDER_SECTION = "kneeboard_order"
KNEEBOARD_ORDER_KEY = "pages"
RESERVED_BRIEF_PDF = "kneeboard.pdf"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
PDF_EXTENSION = ".pdf"


@dataclass(frozen=True)
class KneeboardPage:
    id: str
    kind: str
    label: str
    path: Path
    page_index: Optional[int] = None
    included: bool = True

    def with_included(self, included: bool) -> "KneeboardPage":
        return KneeboardPage(
            id=self.id,
            kind=self.kind,
            label=self.label,
            path=self.path,
            page_index=self.page_index,
            included=included,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "source": self.path.name,
            "page": None if self.page_index is None else self.page_index + 1,
            "included": self.included,
        }


def max_kneeboard_pages(airframe: str) -> int:
    return 16 if airframe == "F-15" else 32


def discover_kneeboard_pages(conf: configparser.ConfigParser, airframe: str) -> Tuple[List[KneeboardPage], List[str]]:
    src = Path(conf["system"]["pdf_output_dir"])
    max_pages = max_kneeboard_pages(airframe)
    pages: List[KneeboardPage] = []
    warnings: List[str] = []
    ignored_count = 0

    if not src.exists():
        return [], [f"Kneeboard order: PDF output folder does not exist: {src}"]

    try:
        file_names = sorted(
            (f.name for f in src.iterdir() if f.is_file() and _is_supported_source(f)),
            key=_source_sort_key,
        )
    except Exception as exc:
        return [], [f"Kneeboard order: failed to scan PDF output folder {src}: {exc}"]

    for file_name in file_names:
        path = src / file_name
        for page in _source_pages(path, warnings):
            if len(pages) < max_pages:
                pages.append(page)
            else:
                ignored_count += 1

    if ignored_count:
        warnings.append(
            f"Kneeboard order: ignored {ignored_count} page(s) after the first {max_pages} for {airframe}."
        )
    return pages, warnings


def resolve_kneeboard_order(conf: configparser.ConfigParser, airframe: str) -> Tuple[List[KneeboardPage], List[str]]:
    available, warnings = discover_kneeboard_pages(conf, airframe)
    available_by_id = {page.id: page for page in available}
    ordered: List[KneeboardPage] = []
    seen: set[str] = set()

    for page_id, included in parse_order_tokens(conf).items():
        page = available_by_id.get(page_id)
        if page is None:
            warnings.append(f"Kneeboard order: skipped missing page {page_id}.")
            continue
        if page_id in seen:
            continue
        seen.add(page_id)
        ordered.append(page.with_included(included))

    for page in available:
        if page.id not in seen:
            ordered.append(page)

    return _included_first(ordered), warnings


def serialize_order(pages: Iterable[Dict[str, Any]]) -> str:
    tokens: List[str] = []
    for page in pages:
        page_id = str(page.get("id") or "").strip()
        if not page_id:
            continue
        included = page.get("included", True)
        state = "on" if bool(included) else "off"
        tokens.append(f"{page_id}:{state}")
    return ", ".join(tokens)


def parse_order_tokens(conf: configparser.ConfigParser) -> Dict[str, bool]:
    if not conf.has_section(KNEEBOARD_ORDER_SECTION):
        return {}
    raw = conf[KNEEBOARD_ORDER_SECTION].get(KNEEBOARD_ORDER_KEY, "")
    parsed: Dict[str, bool] = {}
    for token in raw.split(","):
        item = token.strip()
        if not item:
            continue
        page_id, sep, state = item.rpartition(":")
        if not sep or state.lower() not in {"on", "off"} or not page_id:
            continue
        parsed[page_id] = state.lower() == "on"
    return parsed


def save_kneeboard_order(
    cfg: configparser.ConfigParser,
    pages: Iterable[Dict[str, Any]],
) -> None:
    if not cfg.has_section(KNEEBOARD_ORDER_SECTION):
        cfg[KNEEBOARD_ORDER_SECTION] = {}
    cfg[KNEEBOARD_ORDER_SECTION][KNEEBOARD_ORDER_KEY] = serialize_order(pages)


def _is_supported_source(path: Path) -> bool:
    ext = path.suffix.lower()
    return ext in IMAGE_EXTENSIONS or ext == PDF_EXTENSION


def _source_sort_key(file_name: str) -> tuple[int, str]:
    if file_name.lower() == RESERVED_BRIEF_PDF:
        return (0, file_name.lower())
    return (1, file_name.lower())


def _source_pages(path: Path, warnings: List[str]) -> List[KneeboardPage]:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return [
            KneeboardPage(
                id=f"image:{path.name}",
                kind="image",
                label=path.name,
                path=path,
            )
        ]
    if ext != PDF_EXTENSION:
        return []

    is_brief_pdf = path.name.lower() == RESERVED_BRIEF_PDF
    try:
        with pymupdf.open(path) as doc:
            page_count = len(doc)
    except Exception as exc:
        warnings.append(f"Kneeboard order: skipped unreadable PDF {path.name}: {exc}")
        return []

    if page_count <= 0:
        warnings.append(f"Kneeboard order: skipped empty PDF {path.name}.")
        return []

    pages: List[KneeboardPage] = []
    for page_index in range(page_count):
        page_number = page_index + 1
        if is_brief_pdf:
            page_id = f"brief:{page_number}"
            kind = "brief"
            label = f"Briefing PDF page {page_number}"
        else:
            page_id = f"pdf:{path.name}:{page_number}"
            kind = "pdf"
            label = f"{path.name} page {page_number}"
        pages.append(
            KneeboardPage(
                id=page_id,
                kind=kind,
                label=label,
                path=path,
                page_index=page_index,
            )
        )
    return pages


def _included_first(pages: List[KneeboardPage]) -> List[KneeboardPage]:
    included = [page for page in pages if page.included]
    excluded = [page for page in pages if not page.included]
    return included + excluded
