from __future__ import annotations

import configparser
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterable, Mapping

import pymupdf

from lib.bms_paths import callsign_ini_path
from lib.parsers.parse_briefing_txt import Briefing
from lib.parsers.parse_callsign_ini import Callsign_ini
from lib.theater_paths import resolve_theater_data_root
from lib.progress import ProgressCallback

from .models import (
    ALL_SELECTIONS,
    ChartKind,
    ChartRole,
    ChartSelection,
    parse_chart_selections,
)

logger = logging.getLogger("html_brief_log")
logger_ui = logging.getLogger("ui_logger")

ARTIFACT_INDEX_SCHEMA = 1
SUPPORTED_OPENCHART_API_VERSION = 1
PARKING_SLOT_COUNT = 4
MANAGED_BRIEF_RELATIVE_PATH = Path(".html_brief") / "briefing.pdf"
CHART_ROLE_ORDER = {role: index for index, role in enumerate(ChartRole)}


@dataclass
class ChartTarget:
    airfield: Any
    airfield_key: str
    display_name: str
    icao: str | None
    kind: ChartKind
    roles: list[ChartRole]
    signature: str
    renderer_version: str
    pdf_backend_version: str | None
    relative_path: Path
    empty_parking: bool = False

    @property
    def id(self) -> str:
        return f"{self.airfield_key}|{self.kind.value}"


@dataclass(frozen=True)
class ChartPdfSelection:
    """One generated chart PDF and the enabled zero-based pages to append."""

    path: Path
    page_indices: tuple[int, ...]


@dataclass
class ChartPlan:
    theater: str
    theater_slug: str
    data_root: Path | None
    output_root: Path
    selected: tuple[ChartSelection, ...]
    targets: list[ChartTarget] = field(default_factory=list)
    selection_targets: dict[str, ChartTarget] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    unresolved_roles: set[ChartRole] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    source: Any | None = field(default=None, repr=False)

    @property
    def theater_root(self) -> Path:
        return self.output_root / "charts" / self.theater_slug

    @property
    def index_path(self) -> Path:
        return self.theater_root / "index.json"


def _safe_component(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return cleaned or fallback


def _target_folder(display_name: str, key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    return f"{_safe_component(display_name, 'airfield')}-{digest}"


def _ordered_target_roles(target: ChartTarget) -> tuple[ChartRole, ...]:
    return tuple(sorted(set(target.roles), key=CHART_ROLE_ORDER.__getitem__))


def _semantic_page_ids(target: ChartTarget, page_index: int) -> tuple[str, ...]:
    return tuple(
        f"chart:{role.value}:{target.kind.value}:{page_index + 1}"
        for role in _ordered_target_roles(target)
    )


def _read_lines(path: Path) -> list[str]:
    with path.open("r", encoding="latin1") as handle:
        return handle.readlines()


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _role_inputs(bms_cfg: Any) -> dict[ChartRole, tuple[str | None, tuple[float, float] | None]]:
    brief_path = Path(bms_cfg.base_dir) / "User" / "Briefings" / "briefing.txt"
    briefing = Briefing(_read_lines(brief_path))
    callsign = Callsign_ini(_read_lines(callsign_ini_path(bms_cfg)))

    names: dict[ChartRole, str | None] = {}
    airbases = list(getattr(briefing, "airbases", []) or [])
    for index, role in enumerate(ChartRole):
        name = getattr(airbases[index], "agency", "") if index < len(airbases) else ""
        names[role] = str(name).strip() or None

    steerpoints = list(getattr(callsign, "steerpoints", []) or [])
    takeoffs = [point for point in steerpoints if str(getattr(point, "action", "")) == "1"]
    landings = [point for point in steerpoints if str(getattr(point, "action", "")) in {"7", "27"}]
    role_points = {
        ChartRole.DEPARTURE: takeoffs[0] if takeoffs else None,
        ChartRole.ARRIVAL: landings[0] if landings else None,
        ChartRole.ALTERNATE: landings[1] if len(landings) > 1 else None,
    }
    result: dict[ChartRole, tuple[str | None, tuple[float, float] | None]] = {}
    for role, point in role_points.items():
        x = _float_or_none(getattr(point, "coord_x", None)) if point is not None else None
        y = _float_or_none(getattr(point, "coord_y", None)) if point is not None else None
        result[role] = (names[role], (x, y) if x is not None and y is not None else None)
    return result


def _load_index(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != ARTIFACT_INDEX_SCHEMA or not isinstance(data.get("artifacts"), dict):
            return {"schema_version": ARTIFACT_INDEX_SCHEMA, "artifacts": {}}
        return data
    except (OSError, ValueError, TypeError):
        return {"schema_version": ARTIFACT_INDEX_SCHEMA, "artifacts": {}}


def _atomic_write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".index-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _pdf_page_count(path: Path) -> int | None:
    try:
        with pymupdf.open(path) as document:
            return len(document)
    except Exception:
        return None


def _artifact_state(plan: ChartPlan, target: ChartTarget, entry: Mapping[str, Any] | None) -> str:
    if not isinstance(entry, Mapping) or not entry:
        return "missing"
    if (
        entry.get("generation_signature") != target.signature
        or entry.get("renderer_version") != target.renderer_version
        or entry.get("pdf_backend_version") != target.pdf_backend_version
    ):
        return "stale"
    try:
        expected_count = int(entry.get("page_count") or 0)
    except (TypeError, ValueError):
        return "missing"
    if expected_count == 0 and target.kind is ChartKind.PARKING:
        return "generated"
    path = plan.theater_root / str(entry.get("relative_path") or "")
    actual_count = _pdf_page_count(path)
    if actual_count is None or actual_count < expected_count or expected_count <= 0:
        return "missing"
    return "generated"


class ChartService:
    """Owns HTML Brief's side of the versioned OpenChart contract."""

    def __init__(
        self,
        openchart_api: Any | None = None,
        path_resolver: Callable[[str], Path] | None = None,
    ):
        if openchart_api is None:
            from openchart import api as openchart_api
        self.api = openchart_api
        self.path_resolver = path_resolver or Path
        self._source_cache: dict[str, Any] = {}
        self._source_cache_lock = Lock()
        api_version = getattr(openchart_api, "OPENCHART_API_VERSION", None)
        if api_version != SUPPORTED_OPENCHART_API_VERSION:
            raise RuntimeError(
                f"Unsupported OpenChart API version {api_version!r}; expected {SUPPORTED_OPENCHART_API_VERSION}."
            )

    def invalidate_sources(self) -> None:
        """Discard parsed OpenChart theater data after a BMS source change."""

        with self._source_cache_lock:
            self._source_cache.clear()

    def _theater_source(self, data_root: Path, *, fresh: bool = False) -> Any:
        cache_key = os.path.normcase(str(data_root.expanduser().resolve()))
        with self._source_cache_lock:
            if not fresh:
                cached = self._source_cache.get(cache_key)
                if cached is not None:
                    return cached
            source = self.api.TheaterSource(data_root)
            # Keep only the active source. BMS config changes explicitly clear
            # this cache, and chart generation replaces it with freshly parsed
            # theater data before rendering.
            self._source_cache = {cache_key: source}
            return source

    def build_plan(
        self,
        cfg: configparser.ConfigParser,
        bms_cfg: Any,
        *,
        all_selections: bool = False,
        fresh_source: bool = False,
    ) -> ChartPlan:
        selected, warnings = parse_chart_selections(cfg["pages"].get("charts", ""))
        for warning in warnings:
            logger_ui.warning(warning)
        theater = str(getattr(bms_cfg, "theater", "") or "unknown")
        output_root = self.path_resolver(cfg["system"]["pdf_output_dir"])
        plan = ChartPlan(
            theater=theater,
            theater_slug=_safe_component(theater, "theater"),
            data_root=resolve_theater_data_root(getattr(bms_cfg, "base_dir", None), theater),
            output_root=output_root,
            selected=selected,
            warnings=warnings,
        )
        requested = ALL_SELECTIONS if all_selections else selected
        if not requested:
            return plan
        if plan.data_root is None:
            message = f"Charts: could not resolve support-data root for theater {theater}."
            for selection in requested:
                plan.errors[selection.id] = message
            plan.warnings.append(message)
            return plan

        try:
            source = self._theater_source(plan.data_root, fresh=fresh_source)
            plan.source = source
            role_inputs = _role_inputs(bms_cfg)
        except Exception as exc:
            message = f"Charts: could not load theater or briefing inputs: {exc}"
            for selection in requested:
                plan.errors[selection.id] = message
            plan.warnings.append(message)
            return plan

        roles_needed = {selection.role for selection in requested}
        resolved_roles: dict[ChartRole, Any] = {}
        for role in ChartRole:
            if role not in roles_needed:
                continue
            name, position = role_inputs.get(role, (None, None))
            try:
                if position is not None:
                    query = self.api.AirfieldQuery(position_x=position[0], position_y=position[1])
                elif name:
                    query = self.api.AirfieldQuery(name=name)
                else:
                    raise ValueError(f"no route position or briefing name for {role.value}")
                resolved_roles[role] = source.resolve_airfield(query)
            except Exception as exc:
                message = f"Charts: {role.value} airfield is unavailable: {exc}"
                plan.unresolved_roles.add(role)
                plan.warnings.append(message)
                logger.debug(message)
                for selection in requested:
                    if selection.role is role:
                        plan.errors[selection.id] = message

        target_by_id: dict[str, ChartTarget] = {}
        for selection in requested:
            airfield = resolved_roles.get(selection.role)
            if airfield is None:
                continue
            target_id = f"{airfield.key}|{selection.kind.value}"
            target = target_by_id.get(target_id)
            if target is None:
                empty_parking = False
                try:
                    oc_kind = self.api.ChartKind(selection.kind.value)
                    descriptor = source.describe_chart_pdf(airfield, oc_kind)
                except Exception as exc:
                    if (
                        selection.kind is ChartKind.PARKING
                        and getattr(exc, "code", None) == "parking_chart_unavailable"
                    ):
                        descriptor = source.describe_chart(airfield, oc_kind)
                        empty_parking = True
                    else:
                        message = f"Charts: cannot inspect {selection.kind.value} chart for {airfield.display_name}: {exc}"
                        plan.errors[selection.id] = message
                        plan.warnings.append(message)
                        continue
                folder = _target_folder(airfield.display_name, airfield.key)
                relative_path = Path(folder) / f"{selection.kind.value}.pdf"
                target = ChartTarget(
                    airfield=airfield,
                    airfield_key=airfield.key,
                    display_name=airfield.display_name,
                    icao=airfield.icao,
                    kind=selection.kind,
                    roles=[selection.role],
                    signature=descriptor.generation_signature,
                    renderer_version=descriptor.renderer_version,
                    pdf_backend_version=getattr(
                        descriptor,
                        "pdf_backend_version",
                        None,
                    ),
                    relative_path=relative_path,
                    empty_parking=empty_parking,
                )
                target_by_id[target_id] = target
                plan.targets.append(target)
            elif selection.role not in target.roles:
                target.roles.append(selection.role)
            plan.selection_targets[selection.id] = target
        return plan

    def status(
        self,
        cfg: configparser.ConfigParser,
        bms_cfg: Any,
        *,
        failures: Mapping[str, str] | None = None,
        generating: Iterable[str] = (),
    ) -> dict[str, Any]:
        plan = self.build_plan(cfg, bms_cfg, all_selections=True)
        index = _load_index(plan.index_path)
        selected_ids = {selection.id for selection in plan.selected}
        generating_ids = set(generating)
        failure_map = dict(failures or {})
        rows: list[dict[str, Any]] = []
        for selection in ALL_SELECTIONS:
            target = plan.selection_targets.get(selection.id)
            message = plan.errors.get(selection.id)
            shared_with: list[str] = []
            if message:
                state = "failed"
            elif target is None:
                state = "missing"
            else:
                shared_with = sorted(
                    item.id for item in ALL_SELECTIONS
                    if item.id != selection.id and plan.selection_targets.get(item.id) is target
                )
                if target.id in generating_ids:
                    state = "generating"
                elif target.id in failure_map:
                    state = "failed"
                    message = failure_map[target.id]
                else:
                    entry = index["artifacts"].get(target.id)
                    state = _artifact_state(plan, target, entry)
            display_state = (
                "not detected"
                if selection.role in plan.unresolved_roles
                else state
            )
            rows.append({
                "id": selection.id,
                "role": selection.role.value,
                "kind": selection.kind.value,
                "selected": selection.id in selected_ids,
                "state": state,
                "display_state": display_state,
                "message": message,
                "airfield_key": target.airfield_key if target else None,
                "airfield": target.display_name if target else None,
                "shared_with": shared_with,
            })
        selected_rows = [row for row in rows if row["selected"]]
        return {
            "theater": plan.theater,
            "selections": rows,
            "needs_generation": [
                row["id"] for row in selected_rows if row["state"] in {"missing", "stale", "failed"}
            ],
            "warnings": plan.warnings,
        }

    def generate(
        self,
        cfg: configparser.ConfigParser,
        bms_cfg: Any,
        *,
        force: bool = False,
        prepared_plan: ChartPlan | None = None,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        # Explicit generation must parse current theater data. The route may
        # supply the fresh plan it already built for progress reporting.
        plan = prepared_plan or self.build_plan(cfg, bms_cfg, fresh_source=True)
        index = _load_index(plan.index_path)
        index.update({"schema_version": ARTIFACT_INDEX_SCHEMA, "theater": plan.theater})
        artifacts = index.setdefault("artifacts", {})
        generated: list[str] = []
        skipped: list[str] = []
        failures: dict[str, str] = {}
        warnings = list(plan.warnings)

        source = plan.source
        target_count = len(plan.targets)
        if progress is not None:
            progress(
                title="Generating charts",
                stage="chart_generate",
                message=(
                    f"Preparing to generate {target_count} chart{'s' if target_count != 1 else ''}..."
                    if target_count
                    else "No chart artifacts need generation."
                ),
                note="Only done once per chart. Only runs again when the source data or chart generator updates.",
                current=0 if target_count else None,
                total=target_count or None,
                can_cancel=False,
            )

        for target_index, target in enumerate(plan.targets):
            if progress is not None:
                progress(
                    stage="chart_generate",
                    message=(
                        f"Generating {target.kind.value} chart for {target.display_name} "
                        f"({target_index + 1} of {target_count})..."
                    ),
                    current=target_index,
                    total=target_count,
                )
            previous = artifacts.get(target.id)
            if not force and _artifact_state(plan, target, previous) == "generated":
                previous["roles"] = [role.value for role in target.roles]
                skipped.append(target.id)
                if progress is not None:
                    progress(
                        message=(
                            f"Chart {target_index + 1} of {target_count} is already current."
                        ),
                        current=target_index + 1,
                        total=target_count,
                    )
                continue
            if source is None:
                if progress is not None:
                    progress(current=target_index + 1, total=target_count)
                continue
            try:
                artifact_path = plan.theater_root / target.relative_path
                if target.empty_parking:
                    if artifact_path.is_file():
                        artifact_path.unlink()
                    artifacts[target.id] = {
                        "airfield_key": target.airfield_key,
                        "display_name": target.display_name,
                        "icao": target.icao,
                        "kind": target.kind.value,
                        "roles": [role.value for role in target.roles],
                        "relative_path": target.relative_path.as_posix(),
                        "page_count": 0,
                        "pages": [],
                        "generation_signature": target.signature,
                        "renderer_version": target.renderer_version,
                        "pdf_backend_version": target.pdf_backend_version,
                    }
                    generated.append(target.id)
                    continue
                document = source.render_chart_pdf(
                    target.airfield,
                    self.api.ChartKind(target.kind.value),
                )
                pages = list(document.pages)
                rendered_page_count = len(pages)
                if target.kind is ChartKind.PARKING and len(pages) > PARKING_SLOT_COUNT:
                    warning = (
                        f"Charts: OpenChart returned {len(pages)} parking pages for {target.display_name}; "
                        f"keeping the first {PARKING_SLOT_COUNT}."
                    )
                    warnings.append(warning)
                    logger_ui.warning(warning)
                    pages = pages[:PARKING_SLOT_COUNT]
                actual_count = self._write_chart_pdf(
                    artifact_path,
                    document.pdf_bytes,
                    expected_page_count=rendered_page_count,
                    page_limit=(
                        PARKING_SLOT_COUNT
                        if target.kind is ChartKind.PARKING
                        else None
                    ),
                )
                if actual_count != len(pages):
                    raise RuntimeError(
                        "OpenChart PDF page count does not match its page metadata"
                    )
                entry = {
                    "airfield_key": target.airfield_key,
                    "display_name": target.display_name,
                    "icao": target.icao,
                    "kind": target.kind.value,
                    "roles": [role.value for role in target.roles],
                    "relative_path": target.relative_path.as_posix(),
                    "page_count": len(pages),
                    "pages": [
                        {
                            "ordinal": int(page.ordinal),
                            "label": str(page.label),
                            "runway_designator": page.runway_designator,
                        }
                        for page in pages
                    ],
                    "generation_signature": document.generation_signature,
                    "renderer_version": document.renderer_version,
                    "pdf_backend_version": document.pdf_backend_version,
                }
                artifacts[target.id] = entry
                generated.append(target.id)
                for warning in document.warnings:
                    message = f"Charts: {target.display_name} {target.kind.value}: {warning.message}"
                    warnings.append(message)
                    logger_ui.warning(message)
            except Exception as exc:
                message = f"Charts: failed to generate {target.kind.value} chart for {target.display_name}: {exc}"
                failures[target.id] = message
                warnings.append(message)
                logger_ui.error(message)
            finally:
                if progress is not None:
                    progress(
                        current=target_index + 1,
                        total=target_count,
                    )

        _atomic_write_json(plan.index_path, index)
        return {
            "generated": generated,
            "skipped": skipped,
            "failures": failures,
            "warnings": warnings,
        }

    @staticmethod
    def _write_chart_pdf(
        path: Path,
        pdf_bytes: bytes,
        *,
        expected_page_count: int,
        page_limit: int | None = None,
    ) -> int:
        if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
            raise RuntimeError("OpenChart returned invalid PDF bytes")
        path.parent.mkdir(parents=True, exist_ok=True)
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as source:
            source_count = len(source)
            if source_count <= 0:
                raise RuntimeError("OpenChart returned an empty PDF")
            if source_count != expected_page_count:
                raise RuntimeError(
                    "OpenChart PDF page count does not match its page metadata"
                )
            output_bytes = pdf_bytes
            output_count = source_count
            if page_limit is not None and source_count > page_limit:
                with pymupdf.open() as truncated:
                    truncated.insert_pdf(source, from_page=0, to_page=page_limit - 1)
                    output_bytes = truncated.tobytes()
                output_count = page_limit
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.stem}-",
            suffix=".pdf",
            dir=path.parent,
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(output_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
        return output_count

    def current_artifacts(
        self,
        cfg: configparser.ConfigParser,
        bms_cfg: Any,
        *,
        included_page_ids: Iterable[str] | None = None,
    ) -> tuple[list[ChartPdfSelection], list[str]]:
        plan = self.build_plan(cfg, bms_cfg)
        index = _load_index(plan.index_path)
        enabled_ids = (
            None
            if included_page_ids is None
            else {str(page_id).strip() for page_id in included_page_ids if str(page_id).strip()}
        )
        selections: list[ChartPdfSelection] = []
        warnings = list(plan.warnings)
        for target in plan.targets:
            logical_count = PARKING_SLOT_COUNT if target.kind is ChartKind.PARKING else 1
            requested_indices = tuple(
                page_index
                for page_index in range(logical_count)
                if enabled_ids is None
                or any(page_id in enabled_ids for page_id in _semantic_page_ids(target, page_index))
            )
            if not requested_indices:
                continue
            entry = index["artifacts"].get(target.id)
            state = _artifact_state(plan, target, entry)
            if state != "generated":
                warnings.append(f"Charts: skipped {state} {target.kind.value} chart for {target.display_name}.")
                continue
            page_count = int(entry.get("page_count") or 0)
            page_indices = tuple(page_index for page_index in requested_indices if page_index < page_count)
            if not page_indices:
                continue
            path = plan.theater_root / entry["relative_path"]
            selections.append(ChartPdfSelection(path=path, page_indices=page_indices))
        return selections, warnings

    def kneeboard_slots(self, cfg: configparser.ConfigParser, bms_cfg: Any) -> tuple[list[dict[str, Any]], list[str]]:
        plan = self.build_plan(cfg, bms_cfg)
        index = _load_index(plan.index_path)
        slots: list[dict[str, Any]] = []
        for target in plan.targets:
            raw_entry = index["artifacts"].get(target.id)
            entry = raw_entry if isinstance(raw_entry, Mapping) else {}
            current = _artifact_state(plan, target, entry) == "generated"
            count = int(entry.get("page_count") or 0) if current and entry else 0
            slot_count = PARKING_SLOT_COUNT if target.kind is ChartKind.PARKING else (1 if count else 0)
            path = plan.theater_root / (entry.get("relative_path") if entry else target.relative_path)
            roles = _ordered_target_roles(target)
            for index_value in range(slot_count):
                available = index_value < count and path.is_file()
                label = f"{roles[0].value}:{target.kind.value}"
                if target.kind is ChartKind.PARKING:
                    label += f":{index_value + 1}"
                semantic_ids = _semantic_page_ids(target, index_value)
                slots.append({
                    "id": semantic_ids[0],
                    "kind": "chart",
                    "label": label,
                    "tooltip": target.display_name,
                    "path": path,
                    "page_index": index_value,
                    "available": available,
                    "parking_placeholder": target.kind is ChartKind.PARKING,
                    "aliases": list(semantic_ids[1:]),
                })
        return slots, plan.warnings

    def compose_pdf(
        self,
        brief_pdf: Path,
        output_pdf: Path,
        chart_pdfs: Iterable[Path | ChartPdfSelection],
    ) -> int:
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        combined = pymupdf.open()
        try:
            with pymupdf.open(brief_pdf) as brief:
                combined.insert_pdf(brief)
            for chart_ref in chart_pdfs:
                if isinstance(chart_ref, ChartPdfSelection):
                    chart_path = chart_ref.path
                    page_indices = chart_ref.page_indices
                else:
                    chart_path = chart_ref
                    page_indices = None
                with pymupdf.open(chart_path) as chart:
                    if page_indices is None:
                        combined.insert_pdf(chart)
                    else:
                        for page_index in page_indices:
                            combined.insert_pdf(
                                chart,
                                from_page=page_index,
                                to_page=page_index,
                            )
            fd, temp_name = tempfile.mkstemp(prefix=".kneeboard-", suffix=".pdf", dir=output_pdf.parent)
            os.close(fd)
            try:
                combined.save(temp_name)
                os.replace(temp_name, output_pdf)
            except Exception:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
                raise
            return len(combined)
        finally:
            combined.close()

    @staticmethod
    def persist_brief_pdf(rendered_pdf: Path, output_root: Path) -> Path:
        target = output_root / MANAGED_BRIEF_RELATIVE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".briefing-", suffix=".pdf", dir=target.parent)
        os.close(fd)
        try:
            shutil.copyfile(rendered_pdf, temp_name)
            os.replace(temp_name, target)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
        return target


__all__ = [
    "ARTIFACT_INDEX_SCHEMA",
    "ChartPdfSelection",
    "ChartPlan",
    "ChartService",
    "ChartTarget",
    "MANAGED_BRIEF_RELATIVE_PATH",
    "PARKING_SLOT_COUNT",
]
