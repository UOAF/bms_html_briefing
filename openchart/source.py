"""Load deterministic airport facts through OpenChart's embedded readers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re

from .vendor.opencam.campaign import CamContainer, detect_container_version
from .vendor.opencam.objectives import Objective, parse_objectives
from .vendor.opencam.support import (
    AtcAirbaseData,
    CampaignObjectiveData,
    ClassTableEntry,
    ObjectiveFeatureDefinition,
    ObjectiveFeatureLayout,
    ObjectivePointDefinition,
    ObjectivePointHeader,
    SupportData,
    StationIlsEntry,
    load_objective_feature_layout,
    load_support_data,
    resolve_support_paths,
)
from .icao import infer_icao


DEFAULT_CAMPAIGN_IDS = (995, 1784, 1486, 983)
ICAO_PATTERN = re.compile(r"\(([A-Z]{4})\)")
NAVIGATION_AID_PATTERN = re.compile(
    r"\b(VORTAC|VOR[/ -]DME|TACAN|NDB|VOR)\b",
    re.I,
)
NAVIGATION_IDENTIFIER_PATTERN = re.compile(r"\(([A-Z0-9]+)\)")
LOCAL_NAVIGATION_FEATURE_NAMES = frozenset(("beacon vordme", "beacon vor/dme"))
NAVIGATION_OBJECTIVE_CLASSIFICATION = (3, 4, 16)
OBJECTIVE_DOMAIN = 3
OBJECTIVE_CLASS = 4
AIRFIELD_TYPES = frozenset((1, 2))
WATER_LAND_COVER_NAMES = frozenset(("water", "river"))
THEATER_TEXT_NAME_PATTERN = re.compile(r"^\s*Theater\s+name\s*=\s*(.+?)\s*$", re.I)
THEATER_DEFINITION_NAME_PATTERN = re.compile(r"^\s*name\s+(.+?)\s*$", re.I)


class AirportDataError(RuntimeError):
    """Raised when an airport cannot be joined to matching theater data."""


@dataclass(frozen=True)
class NavigationAidData:
    campaign_id: int
    name: str
    kind: str
    identifier: str | None
    channel: int
    band: str
    range_nm: int
    offset_x: float
    offset_y: float


@dataclass(frozen=True)
class NavigationObjectiveData:
    campaign_id: int
    name: str
    kind: str
    identifier: str | None
    channel: int
    band: str
    range_nm: int
    position_x: float
    position_y: float


@dataclass(frozen=True)
class TerrainHeightSource:
    """The terrain-grid facts OpenChart needs for local bulk reads."""

    source_path: Path
    extent_ft: float
    map_size_pixels: int


@dataclass(frozen=True)
class TerrainLandCoverSource:
    """The authored type-ID grid facts OpenChart needs for bulk reads."""

    source_path: Path
    extent_ft: float
    map_size_pixels: int
    water_type_ids: tuple[int, ...]


@dataclass(frozen=True)
class AirportData:
    campaign_id: int
    name: str
    icao: str | None
    objective_type: int
    feature_status_count: int
    placement: CampaignObjectiveData
    layout: ObjectiveFeatureLayout
    station: StationIlsEntry | None
    atc: AtcAirbaseData | None
    navigation_aids: tuple[NavigationAidData, ...]
    navigation_objectives: tuple[NavigationObjectiveData, ...]
    theater_name: str | None
    terrain_height_source: TerrainHeightSource | None
    terrain_land_cover_source: TerrainLandCoverSource | None
    elevation_ft: int | None
    magnetic_variation_degrees: float | None
    models_dir: Path
    shared_models_dir: Path | None = None
    projection_string: str | None = None

    @property
    def models_dirs(self) -> tuple[Path, ...]:
        """Model roots in theater-override then shared-data order."""

        if self.shared_models_dir is None:
            return (self.models_dir,)
        return (self.models_dir, self.shared_models_dir)

    @property
    def display_code(self) -> str:
        return self.icao or "ICAO N/A"


@dataclass(frozen=True)
class AirfieldIndexEntry:
    """Internal lightweight airfield identity before its layout is loaded."""

    campaign_id: int
    name: str
    icao: str | None
    objective_type: int
    feature_status_count: int | None
    placement: CampaignObjectiveData


class AirportRepository:
    """Reusable theater support-data index with optional campaign validation."""

    def __init__(
        self,
        data_root: str | Path,
        campaign_path: str | Path | None = None,
    ) -> None:
        self.data_root = Path(data_root).expanduser().resolve()
        self.campaign_path = (
            None
            if campaign_path is None
            else Path(campaign_path).expanduser().resolve()
        )
        self.theater_name = _load_theater_name(self.data_root)
        self.support = load_support_data(resolve_support_paths(self.data_root))
        self._class_tables_by_entity_idx = _objective_class_tables_by_entity_idx(
            self.support
        )
        objectives = self._load_campaign_objectives()
        self.entries = _airfield_index_entries(
            self.support,
            self._class_tables_by_entity_idx,
            objectives,
        )
        self._entries_by_campaign_id = {
            entry.campaign_id: entry for entry in self.entries
        }
        self._navigation_objectives = (
            _navigation_objectives(self.support, objectives)
            if objectives is not None
            else _navigation_objectives_from_support(
                self.support,
                self._class_tables_by_entity_idx,
            )
        )
        self._airports: dict[int, AirportData] = {}

    def airport(self, campaign_id: int) -> AirportData:
        """Load one indexed airport's complete chart facts."""

        cached = self._airports.get(campaign_id)
        if cached is not None:
            return cached
        entry = self._entries_by_campaign_id.get(campaign_id)
        if entry is None:
            source = (
                str(self.data_root)
                if self.campaign_path is None
                else str(self.campaign_path)
            )
            raise AirportDataError(
                f"campaign ID {campaign_id} is not an airfield in {source}"
            )
        airport = self._load_airport(entry)
        self._airports[campaign_id] = airport
        return airport

    def _load_campaign_objectives(self) -> tuple[Objective, ...] | None:
        if self.campaign_path is None:
            return None
        container = CamContainer.from_path(self.campaign_path)
        obj_entries = [
            entry
            for entry in container.entries
            if entry.name.casefold().endswith(".obj")
        ]
        if len(obj_entries) != 1:
            raise AirportDataError(
                f"{self.campaign_path}: expected one .obj entry, "
                f"found {len(obj_entries)}"
            )
        return parse_objectives(
            obj_entries[0],
            container_version=detect_container_version(container),
            support=self.support,
        )

    def _load_airport(self, entry: AirfieldIndexEntry) -> AirportData:
        support = self.support
        theater_data = support.theater_data
        layout = load_objective_feature_layout(
            support,
            entry.objective_type,
            expected_count=entry.feature_status_count,
            strict_model_dimensions=False,
        )
        if layout is None:
            count = (
                ""
                if entry.feature_status_count is None
                else f" and {entry.feature_status_count} features"
            )
            raise AirportDataError(
                f"{entry.name}: no exact feature layout matches objective type "
                f"{entry.objective_type}{count}"
            )
        if entry.placement.ocd_index != layout.entity_idx:
            raise AirportDataError(
                f"{entry.name}: CampObjData OCD {entry.placement.ocd_index} "
                f"does not match class-table layout OCD {layout.entity_idx}"
            )
        station = support.stations_ils_by_campaign_id.get(entry.campaign_id)
        return AirportData(
            campaign_id=entry.campaign_id,
            name=entry.name,
            icao=entry.icao,
            objective_type=entry.objective_type,
            feature_status_count=len(layout.features),
            placement=entry.placement,
            layout=layout,
            station=station,
            atc=support.atc_airbases_by_campaign_id.get(entry.campaign_id),
            navigation_aids=_navigation_aids(
                support,
                entry.placement,
                layout,
                station,
            ),
            navigation_objectives=self._navigation_objectives,
            theater_name=self.theater_name,
            terrain_height_source=(
                None
                if theater_data is None or theater_data.height_map is None
                else TerrainHeightSource(
                    source_path=theater_data.height_map.source_path,
                    extent_ft=theater_data.height_map.metadata.extent_ft,
                    map_size_pixels=theater_data.height_map.metadata.map_size_pixels,
                )
            ),
            terrain_land_cover_source=(
                None
                if theater_data is None or theater_data.land_cover_map is None
                else TerrainLandCoverSource(
                    source_path=theater_data.land_cover_map.source_path,
                    extent_ft=theater_data.land_cover_map.metadata.extent_ft,
                    map_size_pixels=(
                        theater_data.land_cover_map.metadata.map_size_pixels
                    ),
                    water_type_ids=tuple(
                        sorted(
                            item.id
                            for item in theater_data.land_cover_map.type_definitions
                            if item.name.partition("(")[0].strip().casefold()
                            in WATER_LAND_COVER_NAMES
                        )
                    ),
                )
            ),
            elevation_ft=(
                None
                if theater_data is None or theater_data.height_map is None
                else theater_data.height_map.elevation_ft(
                    entry.placement.position_x,
                    entry.placement.position_y,
                )
            ),
            magnetic_variation_degrees=(
                None
                if theater_data is None
                or theater_data.magnetic_variation is None
                else theater_data.magnetic_variation.variation_at_campaign_position(
                    entry.placement.position_x,
                    entry.placement.position_y,
                )
            ),
            models_dir=support.paths.models_dir,
            shared_models_dir=support.paths.shared_models_dir,
            projection_string=(
                None
                if theater_data is None
                else theater_data.metadata.projection_string
            ),
        )


def load_airports(
    data_root: str | Path,
    campaign_path: str | Path | None = None,
    campaign_ids: tuple[int, ...] = DEFAULT_CAMPAIGN_IDS,
    repository: AirportRepository | None = None,
) -> tuple[AirportData, ...]:
    """Load selected airfields, optionally validating a campaign snapshot."""

    if not campaign_ids:
        raise AirportDataError("at least one campaign ID is required")
    if len(set(campaign_ids)) != len(campaign_ids):
        raise AirportDataError("campaign IDs must be unique")

    repository = repository or AirportRepository(data_root, campaign_path)
    return tuple(repository.airport(campaign_id) for campaign_id in campaign_ids)


def _objective_class_tables_by_entity_idx(
    support: SupportData,
) -> dict[int, tuple[ClassTableEntry, ...]]:
    entries: dict[int, list[ClassTableEntry]] = {}
    for item in support.ct_by_number.values():
        if item.domain != OBJECTIVE_DOMAIN or item.class_ != OBJECTIVE_CLASS:
            continue
        entries.setdefault(item.entity_idx, []).append(item)
    return {
        entity_idx: tuple(sorted(items, key=lambda item: item.number))
        for entity_idx, items in entries.items()
    }


def _airfield_index_entries(
    support: SupportData,
    class_tables_by_entity_idx: dict[int, tuple[ClassTableEntry, ...]],
    objectives: tuple[Objective, ...] | None,
) -> tuple[AirfieldIndexEntry, ...]:
    entries: list[AirfieldIndexEntry] = []
    projection_string = (
        None
        if support.theater_data is None
        else support.theater_data.metadata.projection_string
    )
    if objectives is not None:
        for objective in objectives:
            class_table = objective.class_table_entry
            if (
                class_table is None
                or _class_table_airfield_kind(class_table) is None
            ):
                continue
            placement = objective.campaign_objective_data
            if placement is None:
                continue
            entries.append(
                _airfield_index_entry(
                    placement,
                    objective.objective_type,
                    objective.name,
                    len(objective.features),
                    projection_string,
                )
            )
    else:
        for placement in support.campaign_objectives_by_id.values():
            candidates = tuple(
                item
                for item in class_tables_by_entity_idx.get(
                    placement.ocd_index, ()
                )
                if _class_table_airfield_kind(item) is not None
            )
            if not candidates:
                continue
            if len(candidates) != 1:
                numbers = ", ".join(str(item.number) for item in candidates)
                raise AirportDataError(
                    f"{placement.name}: OCD {placement.ocd_index} matches "
                    f"multiple airfield class-table rows: {numbers}"
                )
            entries.append(
                _airfield_index_entry(
                    placement,
                    candidates[0].number + 100,
                    placement.name,
                    None,
                    projection_string,
                )
            )
    return tuple(
        sorted(entries, key=lambda item: (item.campaign_id, item.name.casefold()))
    )


def _airfield_index_entry(
    placement: CampaignObjectiveData,
    objective_type: int,
    name: str,
    feature_status_count: int | None,
    projection_string: str | None,
) -> AirfieldIndexEntry:
    icao_match = ICAO_PATTERN.search(name)
    icao = (
        icao_match.group(1)
        if icao_match is not None
        else infer_icao(
            name,
            placement.position_x,
            placement.position_y,
            projection_string,
        )
    )
    return AirfieldIndexEntry(
        campaign_id=placement.camp_id,
        name=name,
        icao=icao,
        objective_type=objective_type,
        feature_status_count=feature_status_count,
        placement=placement,
    )


def _class_table_airfield_kind(entry: ClassTableEntry) -> str | None:
    if entry.domain != OBJECTIVE_DOMAIN or entry.class_ != OBJECTIVE_CLASS:
        return None
    if entry.type_ not in AIRFIELD_TYPES:
        return None
    if entry.type_ == 1 and entry.specific == 7:
        return None
    return {1: "airbase", 2: "airstrip"}[entry.type_]


def _load_theater_name(theater_dir: str | Path) -> str | None:
    """Read the chart label from a theater terrain file or definition."""

    root = Path(theater_dir)
    theater_text_candidates = sorted(
        (
            *root.glob("TerrData/*/NewTerrain/Theater.txt"),
            *root.glob("Terrdata/*/NewTerrain/Theater.txt"),
        ),
        key=lambda path: str(path).casefold(),
    )
    for path in theater_text_candidates:
        name = _first_matching_value(path, THEATER_TEXT_NAME_PATTERN)
        if name:
            return name

    definition_candidates = sorted(
        (
            *root.glob("TerrData/TheaterDefinition/*.tdf"),
            *root.glob("Terrdata/theaterdefinition/*.tdf"),
            *root.glob("TheaterDefinition/*.tdf"),
            *root.glob("Theaterdefinition/*.tdf"),
        ),
        key=lambda path: str(path).casefold(),
    )
    for path in definition_candidates:
        name = _first_matching_value(path, THEATER_DEFINITION_NAME_PATTERN)
        if name:
            return name
    return None


def _first_matching_value(path: Path, pattern: re.Pattern[str]) -> str | None:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line)
        if match is not None:
            return match.group(1).strip()
    return None


def _navigation_aids(
    support: SupportData,
    airport: CampaignObjectiveData,
    layout: ObjectiveFeatureLayout,
    airport_station: StationIlsEntry | None,
) -> tuple[NavigationAidData, ...]:
    aids: list[NavigationAidData] = []
    if (
        airport_station is not None
        and airport_station.tacan_range > 0
        and airport_station.tacan_channel > 0
    ):
        for feature in layout.features:
            name = (feature.name or "").casefold()
            if name not in LOCAL_NAVIGATION_FEATURE_NAMES:
                continue
            aids.append(
                NavigationAidData(
                    campaign_id=airport.camp_id,
                    name=feature.name or "VOR/DME",
                    kind="VOR/DME",
                    identifier=None,
                    channel=airport_station.tacan_channel,
                    band=airport_station.tacan_band,
                    range_nm=airport_station.tacan_range,
                    offset_x=feature.offset_x,
                    offset_y=feature.offset_y,
                )
            )

    bounds = _layout_bounds(layout)
    if bounds is None:
        return tuple(aids)
    min_x, max_x, min_y, max_y = bounds
    for candidate in support.campaign_objectives_by_id.values():
        match = NAVIGATION_AID_PATTERN.search(candidate.name)
        if match is None or candidate.camp_id == airport.camp_id:
            continue
        station = support.stations_ils_by_campaign_id.get(candidate.camp_id)
        if (
            station is None
            or station.tacan_range <= 0
            or station.tacan_channel <= 0
        ):
            continue
        offset_x, offset_y = _campaign_delta_to_layout_offset(
            candidate.position_x - airport.position_x,
            candidate.position_y - airport.position_y,
            airport.heading,
        )
        if not min_x <= offset_x <= max_x or not min_y <= offset_y <= max_y:
            continue
        identifier_match = NAVIGATION_IDENTIFIER_PATTERN.search(candidate.name)
        aids.append(
            NavigationAidData(
                campaign_id=candidate.camp_id,
                name=candidate.name,
                kind=_navigation_kind(match.group(1)),
                identifier=(
                    None
                    if identifier_match is None
                    else identifier_match.group(1)
                ),
                channel=station.tacan_channel,
                band=station.tacan_band,
                range_nm=station.tacan_range,
                offset_x=offset_x,
                offset_y=offset_y,
            )
        )
    return tuple(
        sorted(
            aids,
            key=lambda item: (
                math.hypot(item.offset_x, item.offset_y),
                item.campaign_id,
            ),
        )
    )


def _navigation_objectives(
    support: SupportData,
    objectives: tuple[Objective, ...],
) -> tuple[NavigationObjectiveData, ...]:
    """Return explicitly classified Air Nav Beacon campaign objectives."""

    aids: list[NavigationObjectiveData] = []
    for objective in objectives:
        class_table = objective.class_table_entry
        placement = objective.campaign_objective_data
        if class_table is None or placement is None:
            continue
        classification = (
            class_table.domain,
            class_table.class_,
            class_table.type_,
        )
        if classification != NAVIGATION_OBJECTIVE_CLASSIFICATION:
            continue
        match = NAVIGATION_AID_PATTERN.search(objective.name)
        if match is None:
            continue
        station = support.stations_ils_by_campaign_id.get(objective.camp_id)
        identifier_match = NAVIGATION_IDENTIFIER_PATTERN.search(objective.name)
        aids.append(
            NavigationObjectiveData(
                campaign_id=objective.camp_id,
                name=objective.name,
                kind=_navigation_kind(match.group(1)),
                identifier=(
                    None
                    if identifier_match is None
                    else identifier_match.group(1)
                ),
                channel=0 if station is None else station.tacan_channel,
                band="" if station is None else station.tacan_band,
                range_nm=0 if station is None else station.tacan_range,
                position_x=placement.position_x,
                position_y=placement.position_y,
            )
        )
    return tuple(
        sorted(
            aids,
            key=lambda item: (item.campaign_id, item.name.casefold()),
        )
    )


def _navigation_objectives_from_support(
    support: SupportData,
    class_tables_by_entity_idx: dict[int, tuple[ClassTableEntry, ...]],
) -> tuple[NavigationObjectiveData, ...]:
    """Return classified navigation objectives without loading a campaign."""

    aids: list[NavigationObjectiveData] = []
    for placement in support.campaign_objectives_by_id.values():
        if not any(
            (entry.domain, entry.class_, entry.type_)
            == NAVIGATION_OBJECTIVE_CLASSIFICATION
            for entry in class_tables_by_entity_idx.get(placement.ocd_index, ())
        ):
            continue
        match = NAVIGATION_AID_PATTERN.search(placement.name)
        if match is None:
            continue
        station = support.stations_ils_by_campaign_id.get(placement.camp_id)
        identifier_match = NAVIGATION_IDENTIFIER_PATTERN.search(placement.name)
        aids.append(
            NavigationObjectiveData(
                campaign_id=placement.camp_id,
                name=placement.name,
                kind=_navigation_kind(match.group(1)),
                identifier=(
                    None
                    if identifier_match is None
                    else identifier_match.group(1)
                ),
                channel=0 if station is None else station.tacan_channel,
                band="" if station is None else station.tacan_band,
                range_nm=0 if station is None else station.tacan_range,
                position_x=placement.position_x,
                position_y=placement.position_y,
            )
        )
    return tuple(
        sorted(aids, key=lambda item: (item.campaign_id, item.name.casefold()))
    )


def _navigation_kind(value: str) -> str:
    normalized = value.upper().replace("-", "/").replace(" ", "/")
    return "VOR/DME" if normalized == "VOR/DME" else normalized


def _layout_bounds(
    layout: ObjectiveFeatureLayout,
) -> tuple[float, float, float, float] | None:
    points = tuple(
        (item.offset_x, item.offset_y)
        for item in (*layout.features, *layout.points)
    )
    if not points:
        return None
    return (
        min(point[0] for point in points),
        max(point[0] for point in points),
        min(point[1] for point in points),
        max(point[1] for point in points),
    )


def _campaign_delta_to_layout_offset(
    delta_x: float,
    delta_y: float,
    heading: float,
) -> tuple[float, float]:
    angle = math.radians(heading)
    return (
        -delta_x * math.sin(angle) + delta_y * math.cos(angle),
        delta_x * math.cos(angle) + delta_y * math.sin(angle),
    )


__all__ = [
    "AirfieldIndexEntry",
    "AirportData",
    "AirportDataError",
    "AirportRepository",
    "DEFAULT_CAMPAIGN_IDS",
    "NavigationAidData",
    "NavigationObjectiveData",
    "ObjectiveFeatureLayout",
    "ObjectivePointDefinition",
    "ObjectivePointHeader",
    "TerrainHeightSource",
    "TerrainLandCoverSource",
    "load_airports",
]
