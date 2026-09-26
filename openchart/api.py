"""Versioned public library facade for OpenChart consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Mapping
import xml.etree.ElementTree as ET

from . import __version__ as _PACKAGE_VERSION
from .geometry import build_parking_charts
from .model_geometry import is_airport_surface_feature, is_building_feature
from .resvg_render import (
    PdfBackendError,
    PdfRenderOptions,
    inspect_pdf_backend,
    render_svg_pages_pdf,
)
from .render import (
    AirportRenderContext,
    build_airport_render_context,
    render_airport_chart_svg,
    render_airport_parking_chart_svg,
)
from .source import (
    AirfieldIndexEntry,
    AirportData,
    AirportDataError,
    AirportRepository,
)
from .topo_render import render_topographic_chart_svg
from .topography import TopographyError
from .vendor.opencam.campaign import CamFormatError
from .vendor.opencam.objectives import ObjRecordError
from .vendor.opencam.support import BmsSupportError
from .vendor.opencam.theater import TheaterDataError as BmsTheaterDataError
from .vendor.opentaxiway_bml import (
    find_chart_lod_model,
    find_highest_lod_model,
)


OPENCHART_API_VERSION = 1
OPENCHART_RENDERER_VERSION = _PACKAGE_VERSION
AIRFIELD_QUERY_MAX_DISTANCE_FT = 6076.115485564304
AIRFIELD_POSITION_TIE_TOLERANCE_FT = 1.0
_FACILITY_SUFFIXES = frozenset(
    ("ab", "afb", "airbase", "airport", "intl", "international")
)


class ChartKind(str, Enum):
    GROUND = "ground"
    PARKING = "parking"
    LOCAL = "local"


@dataclass(frozen=True)
class AirfieldQuery:
    """Factual airfield matching inputs in BMS theater feet."""

    name: str | None = None
    position_x: float | None = None
    position_y: float | None = None


@dataclass(frozen=True)
class ResolvedAirfield:
    key: str
    display_name: str
    icao: str | None
    _source_token: str = field(default="", repr=False, compare=False)
    _campaign_id: int = field(default=-1, repr=False, compare=False)


@dataclass(frozen=True)
class ChartDescriptor:
    airfield_key: str
    kind: ChartKind
    generation_signature: str
    renderer_version: str


@dataclass(frozen=True)
class ChartWarning:
    code: str
    message: str


@dataclass(frozen=True)
class ChartPage:
    ordinal: int
    label: str
    svg_bytes: bytes
    runway_designator: str | None = None


@dataclass(frozen=True)
class ChartDocument:
    airfield: ResolvedAirfield
    kind: ChartKind
    generation_signature: str
    renderer_version: str
    pages: tuple[ChartPage, ...]
    warnings: tuple[ChartWarning, ...] = ()


@dataclass(frozen=True)
class PdfChartDescriptor:
    airfield_key: str
    kind: ChartKind
    generation_signature: str
    renderer_version: str
    pdf_backend_version: str


@dataclass(frozen=True)
class PdfChartPage:
    ordinal: int
    label: str
    runway_designator: str | None = None


@dataclass(frozen=True)
class PdfChartDocument:
    airfield: ResolvedAirfield
    kind: ChartKind
    generation_signature: str
    renderer_version: str
    pdf_backend_version: str
    pages: tuple[PdfChartPage, ...]
    pdf_bytes: bytes
    warnings: tuple[ChartWarning, ...] = ()


class OpenChartError(RuntimeError):
    """Base class for stable public OpenChart failures."""

    default_code = "openchart_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = self.default_code if code is None else code
        self.details = dict(details or {})


class TheaterDataError(OpenChartError):
    default_code = "theater_data_error"


class AirfieldNotFoundError(OpenChartError):
    default_code = "airfield_not_found"


class AmbiguousAirfieldError(OpenChartError):
    default_code = "ambiguous_airfield"


class CampaignRequiredError(OpenChartError):
    default_code = "campaign_required"


class UnsupportedAirfieldError(OpenChartError):
    default_code = "unsupported_airfield"


class ChartRenderError(OpenChartError):
    default_code = "chart_render_error"


class PdfRenderError(OpenChartError):
    default_code = "pdf_render_error"


class OpenChartContractError(OpenChartError):
    default_code = "contract_error"


class TheaterSource:
    """Resolve and render one immutable theater or campaign snapshot."""

    def __init__(
        self,
        data_root: str | Path,
        campaign_path: str | Path | None = None,
    ) -> None:
        try:
            self._repository = AirportRepository(data_root, campaign_path)
        except (
            AirportDataError,
            BmsSupportError,
            BmsTheaterDataError,
            CamFormatError,
            ObjRecordError,
            OSError,
            ET.ParseError,
            ValueError,
        ) as exc:
            raise TheaterDataError(
                str(exc),
                code="source_load_failed",
                details={"data_root": str(data_root)},
            ) from exc
        except Exception as exc:
            raise TheaterDataError(
                str(exc),
                code="source_load_failed",
                details={"data_root": str(data_root)},
            ) from exc
        self.data_root = self._repository.data_root
        self.campaign_path = self._repository.campaign_path
        self._theater_identity = _theater_identity(self._repository)
        self._source_token = hashlib.sha256(
            f"{self.data_root}\0{self._theater_identity}".encode("utf-8")
        ).hexdigest()
        entries_by_key: dict[str, list[AirfieldIndexEntry]] = {}
        for entry in self._repository.entries:
            entries_by_key.setdefault(self._airfield_key(entry), []).append(entry)
        self._entries_by_key = {
            key: tuple(
                sorted(
                    entries,
                    key=lambda item: (item.campaign_id, item.name.casefold()),
                )
            )
            for key, entries in entries_by_key.items()
        }
        self._render_contexts: dict[int, AirportRenderContext] = {}
        self._source_manifests: dict[
            tuple[int, bool],
            tuple[tuple[str, str, int, int], ...],
        ] = {}

    def resolve_airfield(self, query: AirfieldQuery) -> ResolvedAirfield:
        """Resolve a query without silently selecting an ambiguous airfield."""

        name, position = _validate_query(query)
        candidates = list(self._repository.entries)
        if name is not None:
            normalized_name = _normalize_name(name)
            exact = [
                entry
                for entry in candidates
                if normalized_name in _airfield_aliases(entry)
            ]
            candidates = exact if exact else [
                entry
                for entry in candidates
                if _is_leading_alias_prefix(normalized_name, entry)
            ]
            if not candidates:
                raise AirfieldNotFoundError(
                    f"no airfield matches name {name!r}",
                    details={"name": name},
                )

        if position is not None:
            distances = [
                (
                    math.hypot(
                        entry.placement.position_x - position[0],
                        entry.placement.position_y - position[1],
                    ),
                    entry,
                )
                for entry in candidates
            ]
            distances = [
                item
                for item in distances
                if item[0] <= AIRFIELD_QUERY_MAX_DISTANCE_FT
            ]
            if not distances:
                raise AirfieldNotFoundError(
                    "no airfield matches the supplied theater position",
                    details={
                        "name": name,
                        "position_x": position[0],
                        "position_y": position[1],
                    },
                )
            minimum = min(distance for distance, _ in distances)
            candidates = [
                entry
                for distance, entry in distances
                if distance - minimum <= AIRFIELD_POSITION_TIE_TOLERANCE_FT
            ]

        keys = sorted({self._airfield_key(entry) for entry in candidates})
        if not keys:
            raise AirfieldNotFoundError("no airfield matches the query")
        if len(keys) != 1:
            summaries = tuple(
                self._entries_by_key[key][0].name for key in keys
            )
            raise AmbiguousAirfieldError(
                "airfield query matches multiple distinct airfields: "
                + ", ".join(summaries),
                details={"candidate_keys": tuple(keys)},
            )
        entry = self._entries_by_key[keys[0]][0]
        return ResolvedAirfield(
            key=keys[0],
            display_name=entry.name,
            icao=entry.icao,
            _source_token=self._source_token,
            _campaign_id=entry.campaign_id,
        )

    def describe_chart(
        self,
        airfield: ResolvedAirfield,
        kind: ChartKind,
    ) -> ChartDescriptor:
        airport = self._airport_for(airfield)
        chart_kind = _validate_chart_kind(kind)
        _validate_supported_kind(airport, chart_kind)
        try:
            signature = self._generation_signature(airport, chart_kind)
        except Exception as exc:
            raise TheaterDataError(
                f"cannot inspect source freshness for {airport.name}: {exc}",
                code="source_signature_failed",
                details={
                    "airfield_key": airfield.key,
                    "kind": chart_kind.value,
                },
            ) from exc
        return ChartDescriptor(
            airfield_key=airfield.key,
            kind=chart_kind,
            generation_signature=signature,
            renderer_version=OPENCHART_RENDERER_VERSION,
        )

    def render_chart(
        self,
        airfield: ResolvedAirfield,
        kind: ChartKind,
    ) -> ChartDocument:
        chart_kind = _validate_chart_kind(kind)
        airport = self._airport_for(airfield)
        _validate_supported_kind(airport, chart_kind)
        try:
            signature_before = self._generation_signature(airport, chart_kind)
            pages = _render_pages(
                airport,
                chart_kind,
                self._render_context_for(airport),
            )
            warnings = _chart_warnings(airport, chart_kind)
            signature_after = self._generation_signature(airport, chart_kind)
        except OpenChartError:
            raise
        except (
            AirportDataError,
            BmsSupportError,
            BmsTheaterDataError,
            TopographyError,
            OSError,
            ET.ParseError,
            ValueError,
        ) as exc:
            raise ChartRenderError(
                f"cannot render {chart_kind.value} chart for {airport.name}: {exc}",
                details={
                    "airfield_key": airfield.key,
                    "kind": chart_kind.value,
                },
            ) from exc
        except Exception as exc:
            raise ChartRenderError(
                f"cannot render {chart_kind.value} chart for {airport.name}: {exc}",
                details={
                    "airfield_key": airfield.key,
                    "kind": chart_kind.value,
                },
            ) from exc
        if signature_after != signature_before:
            raise ChartRenderError(
                "source data changed while the chart was being rendered",
                code="source_changed_during_render",
                details={
                    "airfield_key": airfield.key,
                    "kind": chart_kind.value,
                },
            )
        document = ChartDocument(
            airfield=airfield,
            kind=chart_kind,
            generation_signature=signature_after,
            renderer_version=OPENCHART_RENDERER_VERSION,
            pages=pages,
            warnings=warnings,
        )
        _validate_document(document)
        return document

    def describe_chart_pdf(
        self,
        airfield: ResolvedAirfield,
        kind: ChartKind,
        options: PdfRenderOptions | None = None,
        *,
        dpi: float | None = None,
    ) -> PdfChartDescriptor:
        """Describe the cached PDF result without rendering the chart pages."""

        descriptor = self.describe_chart(airfield, kind)
        airport = self._airport_for(airfield)
        _validate_pdf_page_availability(airport, descriptor.kind)
        try:
            settings = _resolve_pdf_options(options, dpi)
            backend = inspect_pdf_backend(settings)
        except PdfBackendError as exc:
            raise PdfRenderError(str(exc), code=exc.code) from exc
        return PdfChartDescriptor(
            airfield_key=descriptor.airfield_key,
            kind=descriptor.kind,
            generation_signature=_pdf_generation_signature(
                descriptor.generation_signature,
                backend.version,
            ),
            renderer_version=descriptor.renderer_version,
            pdf_backend_version=backend.version,
        )

    def render_chart_pdf(
        self,
        airfield: ResolvedAirfield,
        kind: ChartKind,
        options: PdfRenderOptions | None = None,
        *,
        dpi: float | None = None,
    ) -> PdfChartDocument:
        """Render one chart kind as a resvg-rasterized A4 PDF document."""

        svg_document = self.render_chart(airfield, kind)
        if not svg_document.pages:
            raise UnsupportedAirfieldError(
                f"{airfield.display_name}: no authored parking pages are available",
                code="parking_chart_unavailable",
                details={"airfield_key": airfield.key},
            )
        try:
            settings = _resolve_pdf_options(options, dpi)
            backend = inspect_pdf_backend(settings)
            pdf_bytes, backend = render_svg_pages_pdf(
                tuple(page.svg_bytes for page in svg_document.pages),
                settings,
                backend=backend,
            )
        except PdfBackendError as exc:
            raise PdfRenderError(
                f"cannot render {svg_document.kind.value} PDF for "
                f"{airfield.display_name}: {exc}",
                code=exc.code,
                details={
                    "airfield_key": airfield.key,
                    "kind": svg_document.kind.value,
                },
            ) from exc
        pages = tuple(
            PdfChartPage(
                ordinal=page.ordinal,
                label=page.label,
                runway_designator=page.runway_designator,
            )
            for page in svg_document.pages
        )
        return PdfChartDocument(
            airfield=airfield,
            kind=svg_document.kind,
            generation_signature=_pdf_generation_signature(
                svg_document.generation_signature,
                backend.version,
            ),
            renderer_version=svg_document.renderer_version,
            pdf_backend_version=backend.version,
            pages=pages,
            pdf_bytes=pdf_bytes,
            warnings=svg_document.warnings,
        )

    def _airport_for(self, airfield: ResolvedAirfield) -> AirportData:
        if not isinstance(airfield, ResolvedAirfield):
            raise OpenChartContractError(
                "airfield must be a ResolvedAirfield",
                code="invalid_airfield_handle",
            )
        if airfield._source_token != self._source_token:
            raise OpenChartContractError(
                "airfield was resolved by a different TheaterSource",
                code="foreign_airfield_handle",
                details={"airfield_key": airfield.key},
            )
        entries = self._entries_by_key.get(airfield.key)
        if entries is None or not any(
            entry.campaign_id == airfield._campaign_id for entry in entries
        ):
            raise OpenChartContractError(
                "airfield handle is not valid for this source",
                code="invalid_airfield_handle",
                details={"airfield_key": airfield.key},
            )
        try:
            return self._repository.airport(airfield._campaign_id)
        except Exception as exc:
            raise UnsupportedAirfieldError(
                str(exc),
                details={"airfield_key": airfield.key},
            ) from exc

    def _render_context_for(self, airport: AirportData) -> AirportRenderContext:
        context = self._render_contexts.get(airport.campaign_id)
        if context is None:
            context = build_airport_render_context(airport)
            self._render_contexts[airport.campaign_id] = context
        return context

    def _airfield_key(self, entry: AirfieldIndexEntry) -> str:
        placement = entry.placement
        logical_position = (
            round(placement.position_x / 10.0),
            round(placement.position_y / 10.0),
        )
        payload = (
            f"{self._theater_identity}\0{logical_position[0]}\0"
            f"{logical_position[1]}"
        )
        return "af-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def _generation_signature(
        self,
        airport: AirportData,
        kind: ChartKind,
    ) -> str:
        manifest = self._source_manifest(airport, kind)
        payload = {
            "api_version": OPENCHART_API_VERSION,
            "renderer_version": OPENCHART_RENDERER_VERSION,
            "theater": self._theater_identity,
            "airfield_key": self._airfield_key(
                next(
                    entry
                    for entry in self._repository.entries
                    if entry.campaign_id == airport.campaign_id
                )
            ),
            "icao": airport.icao,
            "kind": kind.value,
            "source_manifest": manifest,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _source_manifest(
        self,
        airport: AirportData,
        kind: ChartKind,
    ) -> tuple[tuple[str, str, int, int], ...]:
        cache_key = (airport.campaign_id, kind is ChartKind.LOCAL)
        cached = self._source_manifests.get(cache_key)
        if cached is not None:
            return cached

        if kind is ChartKind.LOCAL:
            base = self._source_manifest(airport, ChartKind.GROUND)
            base_paths = {item[0] for item in base}
            additions = tuple(
                _path_state(path)
                for path in _local_source_paths(self._repository, airport)
                if str(path) not in base_paths
            )
            manifest = tuple(
                sorted(base + additions, key=lambda item: item[0].casefold())
            )
        else:
            manifest = tuple(
                _path_state(path)
                for path in _relevant_source_paths(
                    self._repository,
                    airport,
                    ChartKind.GROUND,
                )
            )
        self._source_manifests[cache_key] = manifest
        return manifest


def _validate_query(
    query: AirfieldQuery,
) -> tuple[str | None, tuple[float, float] | None]:
    if not isinstance(query, AirfieldQuery):
        raise OpenChartContractError(
            "query must be an AirfieldQuery",
            code="invalid_airfield_query",
        )
    name = query.name.strip() if isinstance(query.name, str) else query.name
    if name == "":
        raise OpenChartContractError(
            "airfield query name must not be empty",
            code="invalid_airfield_query",
        )
    if name is not None and not isinstance(name, str):
        raise OpenChartContractError(
            "airfield query name must be a string or None",
            code="invalid_airfield_query",
        )
    if (query.position_x is None) != (query.position_y is None):
        raise OpenChartContractError(
            "airfield query must provide both position coordinates or neither",
            code="invalid_airfield_query",
        )
    position = None
    if query.position_x is not None and query.position_y is not None:
        position = (
            _finite_coordinate(query.position_x, "position_x"),
            _finite_coordinate(query.position_y, "position_y"),
        )
    if name is None and position is None:
        raise OpenChartContractError(
            "airfield query needs a name or theater position",
            code="invalid_airfield_query",
        )
    return name, position


def _finite_coordinate(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OpenChartContractError(
            f"{name} must be a finite number",
            code="invalid_airfield_query",
        )
    numeric = float(value)
    if not math.isfinite(numeric):
        raise OpenChartContractError(
            f"{name} must be a finite number",
            code="invalid_airfield_query",
        )
    return numeric


def _normalize_name(value: str) -> str:
    return " ".join(
        "".join(
            character if character.isalnum() else " "
            for character in value.casefold()
        ).split()
    )


def _airfield_aliases(entry: AirfieldIndexEntry) -> frozenset[str]:
    aliases = {_normalize_name(entry.name)}
    without_icao = re.sub(r"\([A-Z]{4}\)", "", entry.name).strip()
    aliases.add(_normalize_name(without_icao))
    if entry.icao:
        aliases.add(entry.icao.casefold())
    tokens = _normalize_name(without_icao).split()
    while tokens and tokens[-1] in _FACILITY_SUFFIXES:
        tokens.pop()
        if tokens:
            aliases.add(" ".join(tokens))
    return frozenset(alias for alias in aliases if alias)


def _is_leading_alias_prefix(normalized_name: str, entry: AirfieldIndexEntry) -> bool:
    """Match ATC callsigns that abbreviate a multi-word airfield name.

    BMS Comm Ladder tower callsigns are often just the leading word(s) of the
    full airfield name (e.g. "Tel" for "Tel Nof"), so an exact alias match can
    legitimately fail even though the airfield is unambiguous.
    """

    query_tokens = normalized_name.split()
    if not query_tokens:
        return False
    return any(
        _normalize_name(alias).split()[: len(query_tokens)] == query_tokens
        for alias in _airfield_aliases(entry)
    )


def _validate_chart_kind(kind: ChartKind) -> ChartKind:
    if not isinstance(kind, ChartKind):
        raise OpenChartContractError(
            "kind must be a ChartKind",
            code="invalid_chart_kind",
        )
    return kind


def _validate_supported_kind(airport: AirportData, kind: ChartKind) -> None:
    if kind is ChartKind.LOCAL and airport.terrain_height_source is None:
        raise UnsupportedAirfieldError(
            f"{airport.name}: theater has no terrain height map",
            code="local_chart_unavailable",
        )


def _validate_pdf_page_availability(airport: AirportData, kind: ChartKind) -> None:
    if kind is ChartKind.PARKING and not build_parking_charts(
        airport.layout,
        atc=airport.atc,
        magnetic_variation_degrees=airport.magnetic_variation_degrees,
    ):
        raise UnsupportedAirfieldError(
            f"{airport.name}: no authored parking pages are available",
            code="parking_chart_unavailable",
        )


def _render_pages(
    airport: AirportData,
    kind: ChartKind,
    context: AirportRenderContext,
) -> tuple[ChartPage, ...]:
    if kind is ChartKind.GROUND:
        return (
            ChartPage(
                0,
                "Ground",
                render_airport_chart_svg(airport, context=context),
            ),
        )
    if kind is ChartKind.LOCAL:
        return (
            ChartPage(
                0,
                "Local",
                render_topographic_chart_svg(airport, context=context),
            ),
        )
    charts = build_parking_charts(
        airport.layout,
        runways=context.runways,
        atc=airport.atc,
        magnetic_variation_degrees=airport.magnetic_variation_degrees,
    )
    return tuple(
        ChartPage(
            ordinal=ordinal,
            label=f"RWY {chart.designator}",
            svg_bytes=render_airport_parking_chart_svg(
                airport,
                chart,
                context=context,
            ),
            runway_designator=chart.designator,
        )
        for ordinal, chart in enumerate(charts)
    )


def _chart_warnings(
    airport: AirportData,
    kind: ChartKind,
) -> tuple[ChartWarning, ...]:
    warnings: list[ChartWarning] = []
    if airport.station is None:
        warnings.append(
            ChartWarning(
                "missing_station_data",
                "No station/ILS data is available for this airfield.",
            )
        )
    if airport.magnetic_variation_degrees is None:
        warnings.append(
            ChartWarning(
                "missing_magnetic_variation",
                "No magnetic-variation grid is available; true headings are used.",
            )
        )
    if kind is ChartKind.LOCAL and airport.terrain_land_cover_source is None:
        warnings.append(
            ChartWarning(
                "missing_land_cover",
                "No authored land-cover grid is available for local-chart "
                "water shading.",
            )
        )
    missing_models: set[int] = set()
    for feature in airport.layout.features:
        graphics_id = feature.graphics_normal
        if graphics_id is None:
            continue
        is_taxiway = is_airport_surface_feature(feature)
        if (
            is_taxiway
            and find_chart_lod_model(airport.models_dirs, graphics_id) is None
        ):
            missing_models.add(graphics_id)
        elif (
            kind is not ChartKind.LOCAL
            and is_building_feature(feature)
            and find_highest_lod_model(airport.models_dirs, graphics_id) is None
        ):
            missing_models.add(graphics_id)
    for graphics_id in sorted(missing_models):
        warnings.append(
            ChartWarning(
                "missing_graphics_model",
                f"Graphics model {graphics_id} is unavailable and was omitted.",
            )
        )
    return tuple(warnings)


def _validate_document(document: ChartDocument) -> None:
    expected_pages = 1 if document.kind in {ChartKind.GROUND, ChartKind.LOCAL} else None
    if expected_pages is not None and len(document.pages) != expected_pages:
        raise OpenChartContractError(
            f"{document.kind.value} chart returned {len(document.pages)} pages",
            code="invalid_page_count",
        )
    if tuple(page.ordinal for page in document.pages) != tuple(
        range(len(document.pages))
    ):
        raise OpenChartContractError(
            "chart page ordinals are not contiguous",
            code="invalid_page_order",
        )
    for page in document.pages:
        if document.kind is ChartKind.PARKING and not page.runway_designator:
            raise OpenChartContractError(
                "parking chart page has no runway designator",
                code="missing_runway_designator",
            )
        try:
            root = ET.fromstring(page.svg_bytes)
        except (ET.ParseError, TypeError) as exc:
            raise OpenChartContractError(
                f"chart page {page.ordinal} is not valid SVG XML",
                code="invalid_svg",
            ) from exc
        if not root.tag.endswith("}svg") and root.tag != "svg":
            raise OpenChartContractError(
                f"chart page {page.ordinal} has a non-SVG root",
                code="invalid_svg",
            )
        if root.attrib.get("width") != "210mm" or root.attrib.get("height") != "297mm":
            raise OpenChartContractError(
                f"chart page {page.ordinal} is not A4 portrait",
                code="invalid_page_size",
            )
        for element in root.iter():
            for attribute, value in element.attrib.items():
                if attribute.endswith("href") and not value.startswith(("data:", "#")):
                    raise OpenChartContractError(
                        f"chart page {page.ordinal} references an external resource",
                        code="external_svg_resource",
                    )


def _theater_identity(repository: AirportRepository) -> str:
    theater_data = repository.support.theater_data
    if theater_data is None:
        facts = (repository.theater_name, repository.data_root.name)
    else:
        metadata = theater_data.metadata
        facts = (
            repository.theater_name,
            metadata.name,
            metadata.size_km,
            metadata.map_size_pixels,
            metadata.center_latitude,
            metadata.center_longitude,
            metadata.projection_string,
            theater_data.paths.definition_path.name,
        )
    return hashlib.sha256(repr(facts).encode("utf-8")).hexdigest()


def _relevant_source_paths(
    repository: AirportRepository,
    airport: AirportData,
    kind: ChartKind,
) -> tuple[Path, ...]:
    paths = repository.support.paths
    candidates: set[Path] = {paths.ct_path, paths.fcd_path}
    for optional in (
        paths.camp_object_data_path,
        paths.stations_ils_path,
        None if airport.atc is None else airport.atc.source_path,
        repository.campaign_path,
    ):
        if optional is not None:
            candidates.add(optional)
    layout_dir = paths.objective_related_dir / f"OCD_{airport.layout.entity_idx:05d}"
    candidates.add(layout_dir)
    if layout_dir.is_dir():
        candidates.update(path for path in layout_dir.iterdir() if path.is_file())
    for feature in airport.layout.features:
        if feature.graphics_normal is None:
            continue
        for models_dir in paths.models_dirs:
            model_dir = models_dir / str(feature.graphics_normal)
            candidates.add(model_dir)
            if model_dir.is_dir():
                candidates.update(
                    path for path in model_dir.rglob("*") if path.is_file()
                )
    if kind is ChartKind.LOCAL:
        candidates.update(_local_source_paths(repository, airport))
    return tuple(sorted(candidates, key=lambda path: str(path).casefold()))


def _local_source_paths(
    repository: AirportRepository,
    airport: AirportData,
) -> tuple[Path, ...]:
    candidates: set[Path] = set()
    if airport.terrain_height_source is not None:
        candidates.add(airport.terrain_height_source.source_path)
    if airport.terrain_land_cover_source is not None:
        candidates.add(airport.terrain_land_cover_source.source_path)
    theater_paths = repository.support.paths.theater_data_paths
    if theater_paths is not None:
        for optional in (
            theater_paths.definition_path,
            theater_paths.metadata_path,
            theater_paths.land_cover_types_path,
            theater_paths.magnetic_variation_path,
        ):
            if optional is not None:
                candidates.add(optional)
    return tuple(sorted(candidates, key=lambda path: str(path).casefold()))


def _path_state(path: Path) -> tuple[str, str, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return str(path), "missing", 0, 0
    kind = "directory" if path.is_dir() else "file"
    return str(path), kind, stat.st_size, stat.st_mtime_ns


def _pdf_generation_signature(
    svg_generation_signature: str,
    backend_version: str,
) -> str:
    payload = {
        "backend_version": backend_version,
        "format": "application/pdf",
        "format_version": 1,
        "svg_generation_signature": svg_generation_signature,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_pdf_options(
    options: PdfRenderOptions | None,
    dpi: float | None,
) -> PdfRenderOptions | None:
    if dpi is None:
        return options
    if options is not None:
        raise PdfBackendError(
            "pass either PdfRenderOptions or dpi, not both",
            code="invalid_pdf_options",
        )
    return PdfRenderOptions(dpi=dpi)


__all__ = [
    "OPENCHART_API_VERSION",
    "OPENCHART_RENDERER_VERSION",
    "AirfieldQuery",
    "ResolvedAirfield",
    "ChartKind",
    "ChartDescriptor",
    "ChartWarning",
    "ChartPage",
    "ChartDocument",
    "PdfRenderOptions",
    "PdfChartDescriptor",
    "PdfChartPage",
    "PdfChartDocument",
    "OpenChartError",
    "TheaterDataError",
    "AirfieldNotFoundError",
    "AmbiguousAirfieldError",
    "CampaignRequiredError",
    "UnsupportedAirfieldError",
    "ChartRenderError",
    "PdfRenderError",
    "OpenChartContractError",
    "TheaterSource",
]
