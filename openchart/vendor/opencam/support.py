"""Load the BMS support records required to draw an airport chart.

This module is adapted from OpenCAM commit
e4dbcb54a9f4751f3045e1fd96f8627c5bf78115.  It deliberately excludes the
unit, weapon, aircraft, mission-planning, and mutation support catalogs that
OpenChart never reads.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .theater import (
    TheaterData,
    TheaterDataPaths,
    load_theater_definition_directives,
    load_theater_data,
    resolve_theater_definition_path,
    resolve_theater_data_paths,
)


class BmsSupportError(RuntimeError):
    """Raised when required BMS support data is absent or malformed."""


@dataclass(frozen=True)
class BmsSupportPaths:
    theater_dir: Path
    ct_path: Path
    fcd_path: Path
    objective_related_dir: Path
    models_dir: Path
    camp_object_data_path: Path | None
    stations_ils_path: Path | None
    theater_data_paths: TheaterDataPaths | None
    shared_models_dir: Path | None = None
    atc_dir: Path | None = None

    @property
    def models_dirs(self) -> tuple[Path, ...]:
        """Model roots in theater-override then shared-data order."""

        if self.shared_models_dir is None:
            return (self.models_dir,)
        return (self.models_dir, self.shared_models_dir)


@dataclass(frozen=True)
class ClassTableEntry:
    number: int
    domain: int
    class_: int
    type_: int
    subtype: int
    specific: int
    entity_type: int
    entity_idx: int
    graphics_normal: int
    source_path: Path | None = None


@dataclass(frozen=True)
class FeatureClassEntry:
    number: int
    ct_idx: int
    name: str
    hit_points: int
    source_path: Path | None = None


@dataclass(frozen=True)
class ModelDimensions:
    """Exact bounds from one graphics model's ``Parent.dat`` file."""

    source_path: Path
    radius: float
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float

    @property
    def size_x(self) -> float:
        return abs(self.max_x - self.min_x)

    @property
    def size_y(self) -> float:
        return abs(self.max_y - self.min_y)

    @property
    def size_z(self) -> float:
        return abs(self.max_z - self.min_z)


@dataclass(frozen=True)
class ObjectiveFeatureDefinition:
    index: int
    feature_ct_idx: int
    feature_class: FeatureClassEntry | None
    value: int | None
    offset_x: float
    offset_y: float
    offset_z: float
    heading: float
    model_dimensions: ModelDimensions | None = None
    graphics_normal: int | None = None
    class_table: ClassTableEntry | None = None

    @property
    def feature_class_number(self) -> int | None:
        return None if self.feature_class is None else self.feature_class.number

    @property
    def name(self) -> str | None:
        return None if self.feature_class is None else self.feature_class.name

    @property
    def hit_points(self) -> int | None:
        return None if self.feature_class is None else self.feature_class.hit_points


@dataclass(frozen=True)
class ObjectivePointDefinition:
    """One authored PDX point with optional fields preserved as written."""

    index: int
    offset_x: float
    offset_y: float
    offset_z: float
    type_: int | None
    flags: int | None = None
    heading: float | None = None
    max_height: float | None = None
    max_width: float | None = None
    max_length: float | None = None
    branch_index: int | None = None
    root_index: int | None = None
    taxiway_letter: int | None = None
    runway_number: int | None = None
    runway_side: int | None = None
    crossing_point: int | None = None
    parking_point_group: int | None = None


@dataclass(frozen=True)
class ObjectivePointHeader:
    """One authored PHD slice over an objective's PDX points."""

    index: int
    objective_index: int
    type_: int
    point_count: int
    feature_dependency_indices: tuple[int, ...]
    data: float
    first_point_index: int
    runway_texture: int
    runway_number: int
    landing_pattern: int

    @property
    def end_point_index(self) -> int:
        return self.first_point_index + self.point_count


@dataclass(frozen=True)
class ObjectiveFeatureLayout:
    support_ct_number: int
    entity_idx: int
    objective_name: str
    features: tuple[ObjectiveFeatureDefinition, ...]
    point_headers: tuple[ObjectivePointHeader, ...] = ()
    points: tuple[ObjectivePointDefinition, ...] = ()

    def points_for(
        self,
        header: ObjectivePointHeader,
    ) -> tuple[ObjectivePointDefinition, ...]:
        if not isinstance(header, ObjectivePointHeader):
            raise TypeError("header must be an ObjectivePointHeader")
        return self.points[header.first_point_index : header.end_point_index]


@dataclass(frozen=True)
class StationIlsEntry:
    """One non-comment row from ``Campaign/Stations+Ils.dat``."""

    campaign_id: int
    tacan_channel: int
    tacan_band: str
    callsign: int
    tacan_range: int
    tacan_type: int
    tower_uhf: int
    tower_vhf: int
    runway_ils_frequencies: tuple[int, int, int, int]
    ops_uhf: int
    ground_uhf: int
    approach_uhf: int
    lso_uhf: int
    atis_vhf: int
    tower_fragment: int
    ground_fragment: int
    approach_fragment: int
    atis_station_fragment: int


@dataclass(frozen=True)
class AtcRunwayEntry:
    """One runway-direction block from ``TerrData/ATC/*.dat``."""

    runway_number: int
    heading_true: float
    qfu: int
    source_line: int


@dataclass(frozen=True)
class AtcAirbaseData:
    """The runway facts and validation state from one ATC airbase file."""

    campaign_id: int
    declared_runway_count: int
    runways: tuple[AtcRunwayEntry, ...]
    source_path: Path
    issues: tuple[str, ...] = ()

    @property
    def actual_runway_count(self) -> int:
        return len(self.runways)

    @property
    def runway_count_matches(self) -> bool:
        return self.declared_runway_count == self.actual_runway_count


@dataclass(frozen=True)
class CampaignObjectiveData:
    """One objective placement from ``Campaign/CampObjData.XML``."""

    camp_id: int
    name: str
    ocd_index: int
    heading: float
    position_x: float
    position_y: float
    position_z: float


@dataclass(frozen=True)
class SupportData:
    paths: BmsSupportPaths
    ct_by_number: dict[int, ClassTableEntry]
    fcd_by_ct_idx: dict[int, FeatureClassEntry]
    campaign_objectives_by_id: dict[int, CampaignObjectiveData]
    stations_ils_by_campaign_id: dict[int, StationIlsEntry]
    theater_data: TheaterData | None
    atc_airbases_by_campaign_id: dict[int, AtcAirbaseData]


def resolve_support_paths(theater_dir: str | Path) -> BmsSupportPaths:
    theater_path = Path(theater_dir).expanduser().resolve()
    if not theater_path.is_dir():
        raise BmsSupportError(f"theater directory does not exist: {theater_path}")

    base_data_dir = (
        theater_path
        if theater_path.name.casefold() == "data"
        else theater_path.parent
        if theater_path.parent.name.casefold() == "data"
        else theater_path
    )
    local_objects_dir = _casefold_path(theater_path, "TerrData", "Objects")
    base_objects_dir = _casefold_path(base_data_dir, "TerrData", "Objects")
    local_models_dir = _casefold_path(local_objects_dir, "Models")
    base_models_dir = _casefold_path(base_objects_dir, "Models")
    definition_path = resolve_theater_definition_path(theater_path)
    directives = (
        {}
        if definition_path is None
        else load_theater_definition_directives(definition_path)
    )
    declared_3d_dir = (
        None
        if not (value := directives.get("3ddatadir"))
        else _windows_relative_path(base_data_dir, value)
    )
    declared_models_dir = (
        None
        if declared_3d_dir is None
        else _casefold_path(declared_3d_dir, "Models")
    )
    models_dir = (
        declared_models_dir
        if declared_models_dir is not None and declared_models_dir.is_dir()
        else local_models_dir
        if local_models_dir.is_dir()
        else base_models_dir
    )

    def support_file(*relative_parts: str) -> Path:
        local = _casefold_path(theater_path, *relative_parts)
        if local.is_file() or theater_path == base_data_dir:
            return local
        return _casefold_path(base_data_dir, *relative_parts)

    local_atc_dir = _casefold_path(theater_path, "TerrData", "ATC")
    base_atc_dir = _casefold_path(base_data_dir, "TerrData", "ATC")
    atc_dir = (
        local_atc_dir
        if local_atc_dir.is_dir()
        else base_atc_dir
        if base_atc_dir.is_dir()
        else None
    )

    paths = BmsSupportPaths(
        theater_dir=theater_path,
        ct_path=support_file("TerrData", "Objects", "Falcon4_CT.xml"),
        fcd_path=support_file("TerrData", "Objects", "Falcon4_FCD.xml"),
        objective_related_dir=(
            _casefold_path(local_objects_dir, "ObjectiveRelatedData")
            if _casefold_path(local_objects_dir, "ObjectiveRelatedData").is_dir()
            else _casefold_path(base_objects_dir, "ObjectiveRelatedData")
        ),
        models_dir=models_dir,
        shared_models_dir=(
            base_models_dir
            if models_dir != base_models_dir and base_models_dir.is_dir()
            else None
        ),
        camp_object_data_path=_optional_file(
            support_file("Campaign", "CampObjData.XML")
        ),
        stations_ils_path=_optional_file(
            support_file("Campaign", "Stations+Ils.dat")
        ),
        theater_data_paths=resolve_theater_data_paths(theater_path),
        atc_dir=atc_dir,
    )
    _require_files(paths.ct_path, paths.fcd_path)
    _require_dirs(paths.objective_related_dir, paths.models_dir)
    return paths


def load_support_data(paths: BmsSupportPaths) -> SupportData:
    feature_classes = load_feature_classes(paths.fcd_path)
    return SupportData(
        paths=paths,
        ct_by_number=load_class_table(paths.ct_path),
        fcd_by_ct_idx={
            entry.ct_idx: entry for entry in feature_classes.values()
        },
        campaign_objectives_by_id=load_campaign_object_data(
            paths.camp_object_data_path
        ),
        stations_ils_by_campaign_id=load_stations_ils(paths.stations_ils_path),
        theater_data=(
            None
            if paths.theater_data_paths is None
            else load_theater_data(paths.theater_data_paths)
        ),
        atc_airbases_by_campaign_id=load_atc_airbases(paths.atc_dir),
    )


def load_class_table(path: str | Path) -> dict[int, ClassTableEntry]:
    source_path = Path(path)
    entries: dict[int, ClassTableEntry] = {}
    for node in _xml_root(source_path).findall("CT"):
        number = _safe_int(node.attrib.get("Num"), default=-1)
        if number < 0:
            continue
        entries[number] = ClassTableEntry(
            number=number,
            domain=_safe_int(node.findtext("Domain")),
            class_=_safe_int(node.findtext("Class")),
            type_=_safe_int(node.findtext("Type")),
            subtype=_safe_int(node.findtext("SubType")),
            specific=_safe_int(node.findtext("Specific")),
            entity_type=_safe_int(node.findtext("EntityType")),
            entity_idx=_safe_int(node.findtext("EntityIdx"), default=-1),
            graphics_normal=_safe_int(node.findtext("GraphicsNormal")),
            source_path=source_path,
        )
    return entries


def load_feature_classes(path: str | Path) -> dict[int, FeatureClassEntry]:
    source_path = Path(path)
    entries: dict[int, FeatureClassEntry] = {}
    for node in _xml_root(source_path).findall("FCD"):
        number = _safe_int(node.attrib.get("Num"), default=-1)
        if number < 0:
            continue
        entries[number] = FeatureClassEntry(
            number=number,
            ct_idx=_safe_int(node.findtext("CtIdx"), default=-1),
            name=(node.findtext("Name") or "").strip(),
            hit_points=_safe_int(node.findtext("HitPoints")),
            source_path=source_path,
        )
    return entries


def load_campaign_object_data(
    path: str | Path | None,
) -> dict[int, CampaignObjectiveData]:
    if path is None:
        return {}
    xml_path = Path(path)
    root = _xml_root(xml_path)
    if root.tag != "CampObjData":
        raise BmsSupportError(
            f"{xml_path}: expected CampObjData root, got {root.tag!r}"
        )

    entries: dict[int, CampaignObjectiveData] = {}
    for index, node in enumerate(root.findall("CampObj")):
        context = f"{xml_path}: CampObj row {index}"
        camp_id = _required_xml_int(node.attrib.get("CampId"), context, "CampId")
        if camp_id in entries:
            raise BmsSupportError(f"{context}: duplicate CampId {camp_id}")
        entries[camp_id] = CampaignObjectiveData(
            camp_id=camp_id,
            name=_required_xml_text(node, "CampName", context),
            ocd_index=_required_xml_int(
                node.findtext("OcdIndex"), context, "OcdIndex"
            ),
            heading=_required_xml_float(
                node.findtext("Heading"), context, "Heading"
            ),
            position_x=_required_xml_float(
                node.findtext("PositionX"), context, "PositionX"
            ),
            position_y=_required_xml_float(
                node.findtext("PositionY"), context, "PositionY"
            ),
            position_z=_required_xml_float(
                node.findtext("PositionZ"), context, "PositionZ"
            ),
        )
    return entries


def load_model_dimensions(path: str | Path) -> ModelDimensions:
    source_path = Path(path)
    if not source_path.is_file():
        raise BmsSupportError(f"model Parent.dat does not exist: {source_path}")
    rows: list[tuple[int, str]] = []
    for line_number, raw_line in enumerate(
        source_path.read_text(encoding="latin-1", errors="strict").splitlines(),
        start=1,
    ):
        match = re.fullmatch(
            r"\s*Dimensions\s*=\s*(.*?)\s*",
            raw_line,
            flags=re.IGNORECASE,
        )
        if match is not None:
            rows.append((line_number, match.group(1)))
    if len(rows) != 1:
        raise BmsSupportError(
            f"{source_path}: expected exactly one Dimensions row, found {len(rows)}"
        )
    line_number, payload = rows[0]
    fields = payload.split()
    if len(fields) != 7:
        raise BmsSupportError(
            f"{source_path}:{line_number}: expected 7 Dimensions values, "
            f"got {len(fields)}"
        )
    try:
        values = tuple(float(field) for field in fields)
    except ValueError as exc:
        raise BmsSupportError(
            f"{source_path}:{line_number}: Dimensions contains a non-number"
        ) from exc
    if not all(math.isfinite(value) for value in values):
        raise BmsSupportError(
            f"{source_path}:{line_number}: Dimensions values must be finite"
        )
    radius, min_x, max_x, min_y, max_y, min_z, max_z = values
    if radius < 0.0:
        raise BmsSupportError(
            f"{source_path}:{line_number}: Dimensions radius must be nonnegative"
        )
    return ModelDimensions(
        source_path,
        radius,
        min_x,
        max_x,
        min_y,
        max_y,
        min_z,
        max_z,
    )


def load_stations_ils(
    path: str | Path | None,
) -> dict[int, StationIlsEntry]:
    if path is None:
        return {}
    source_path = Path(path)
    entries: dict[int, StationIlsEntry] = {}
    for line_number, raw_line in enumerate(
        source_path.read_text(encoding="utf-8-sig", errors="strict").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        context = f"{source_path}:{line_number}"
        if len(fields) != 21:
            raise BmsSupportError(
                f"{context}: expected 21 Stations+Ils fields, got {len(fields)}"
            )
        tacan_band = fields[2]
        if len(tacan_band) != 1:
            raise BmsSupportError(
                f"{context}: TACAN band must be one character, got {tacan_band!r}"
            )
        try:
            integers = [
                int(value) for index, value in enumerate(fields) if index != 2
            ]
        except ValueError as exc:
            raise BmsSupportError(f"{context}: non-integer station field") from exc
        campaign_id = integers[0]
        if campaign_id in entries:
            # Some authored theaters repeat a CampID. BMS consumers cannot
            # distinguish those rows by ID either, so preserve the first valid
            # definition deterministically instead of rejecting the theater.
            continue
        entries[campaign_id] = StationIlsEntry(
            campaign_id=campaign_id,
            tacan_channel=integers[1],
            tacan_band=tacan_band,
            callsign=integers[2],
            tacan_range=integers[3],
            tacan_type=integers[4],
            tower_uhf=integers[5],
            tower_vhf=integers[6],
            runway_ils_frequencies=tuple(integers[7:11]),
            ops_uhf=integers[11],
            ground_uhf=integers[12],
            approach_uhf=integers[13],
            lso_uhf=integers[14],
            atis_vhf=integers[15],
            tower_fragment=integers[16],
            ground_fragment=integers[17],
            approach_fragment=integers[18],
            atis_station_fragment=integers[19],
        )
    return entries


def load_atc_airbase(path: str | Path) -> AtcAirbaseData:
    """Read one label-oriented ATC file, including surplus runway blocks.

    The declared count is intentionally not used to truncate the file.  Some
    stock theaters contain useful blocks beyond that count, so a mismatch is
    exposed through ``issues`` while every complete block is preserved.
    """

    source_path = Path(path)
    lines = source_path.read_text(
        encoding="latin-1",
        errors="strict",
    ).splitlines()
    campaign_id, _ = _atc_value_after_label(
        source_path,
        lines,
        re.compile(r"^#\s*CampID\b", re.IGNORECASE),
    )
    declared_count, _ = _atc_value_after_label(
        source_path,
        lines,
        re.compile(r"^#\s*Number of active runways\b", re.IGNORECASE),
    )
    try:
        parsed_campaign_id = int(campaign_id)
        parsed_declared_count = int(declared_count)
    except ValueError as exc:
        raise BmsSupportError(
            f"{source_path}: CampID and active-runway count must be integers"
        ) from exc
    if parsed_declared_count < 0:
        raise BmsSupportError(
            f"{source_path}: active-runway count must be nonnegative"
        )

    block_pattern = re.compile(
        r'^#\s*Database Runway\s+"Number"\s*\(Runway Id\)\s*$',
        re.IGNORECASE,
    )
    heading_pattern = re.compile(
        r"^#\s*Runway axis\s*\(True Heading\)\s*$",
        re.IGNORECASE,
    )
    qfu_pattern = re.compile(
        r"^#\s*QFU Marking\s*\(Numerals Only\s*-\s*no letters reqd\)\s*$",
        re.IGNORECASE,
    )
    runway_entries: list[AtcRunwayEntry] = []
    for index, line in enumerate(lines):
        if block_pattern.fullmatch(line.strip()) is None:
            continue
        runway_text, runway_line = _atc_data_line(source_path, lines, index + 1)
        heading_text, heading_line = _atc_value_after_label(
            source_path,
            lines,
            heading_pattern,
            start=runway_line,
        )
        qfu_text, qfu_line = _atc_value_after_label(
            source_path,
            lines,
            qfu_pattern,
            start=heading_line,
        )
        try:
            runway_number = int(runway_text)
            heading_true = float(heading_text)
            qfu = int(qfu_text)
        except ValueError as exc:
            raise BmsSupportError(
                f"{source_path}:{runway_line + 1}: invalid ATC runway values"
            ) from exc
        if runway_number < 0:
            raise BmsSupportError(
                f"{source_path}:{runway_line + 1}: runway ID must be nonnegative"
            )
        if not math.isfinite(heading_true):
            raise BmsSupportError(
                f"{source_path}:{heading_line + 1}: heading must be finite"
            )
        if not 1 <= qfu <= 36:
            raise BmsSupportError(
                f"{source_path}:{qfu_line + 1}: QFU must be between 1 and 36"
            )
        runway_entries.append(
            AtcRunwayEntry(
                runway_number=runway_number,
                heading_true=heading_true % 360.0,
                qfu=qfu,
                source_line=index + 1,
            )
        )

    issues: list[str] = []
    if parsed_declared_count != len(runway_entries):
        issues.append(
            "declared "
            f"{parsed_declared_count} active runways but contains "
            f"{len(runway_entries)} runway blocks"
        )
    return AtcAirbaseData(
        campaign_id=parsed_campaign_id,
        declared_runway_count=parsed_declared_count,
        runways=tuple(runway_entries),
        source_path=source_path,
        issues=tuple(issues),
    )


def load_atc_airbases(
    directory: str | Path | None,
) -> dict[int, AtcAirbaseData]:
    """Load every ATC airbase file, preserving the first duplicate CampID.

    ATC data is a best-effort supplement (callers fall back to ``None`` per
    airbase), so a malformed or non-conforming file is skipped rather than
    aborting every other airbase's chart generation.
    """

    if directory is None:
        return {}
    source_dir = Path(directory)
    if not source_dir.is_dir():
        return {}
    entries: dict[int, AtcAirbaseData] = {}
    for path in sorted(
        source_dir.iterdir(),
        key=lambda item: item.name.casefold(),
    ):
        if not path.is_file() or path.suffix.casefold() != ".dat":
            continue
        try:
            entry = load_atc_airbase(path)
        except BmsSupportError:
            continue
        entries.setdefault(entry.campaign_id, entry)
    return entries


def _atc_value_after_label(
    source_path: Path,
    lines: list[str],
    pattern: re.Pattern[str],
    *,
    start: int = 0,
) -> tuple[str, int]:
    for index in range(start, len(lines)):
        if pattern.search(lines[index].strip()) is None:
            continue
        return _atc_data_line(source_path, lines, index + 1)
    raise BmsSupportError(
        f"{source_path}: missing ATC field matching {pattern.pattern!r}"
    )


def _atc_data_line(
    source_path: Path,
    lines: list[str],
    start: int,
) -> tuple[str, int]:
    for index in range(start, len(lines)):
        value = lines[index].strip()
        if not value or value.startswith("#"):
            continue
        return value, index
    raise BmsSupportError(f"{source_path}: ATC field has no value")


def load_objective_feature_layout(
    support: SupportData,
    objective_type: int,
    *,
    expected_count: int | None = None,
) -> ObjectiveFeatureLayout | None:
    support_ct_number = objective_type - 100
    ct_entry = support.ct_by_number.get(support_ct_number)
    if ct_entry is None or ct_entry.entity_idx < 0:
        return None

    directory = support.paths.objective_related_dir / f"OCD_{ct_entry.entity_idx:05d}"
    stem = f"{ct_entry.entity_idx:05d}"
    ocd_path = directory / f"OCD_{stem}.XML"
    fed_path = directory / f"FED_{stem}.XML"
    phd_path = directory / f"PHD_{stem}.XML"
    pdx_path = directory / f"PDX_{stem}.XML"
    if not ocd_path.is_file() or not fed_path.is_file():
        return None

    objective_name, objective_ct_idx = _load_objective_data(ocd_path)
    if objective_ct_idx != support_ct_number:
        return None
    features = _load_objective_feature_definitions(support, fed_path)
    if tuple(feature.index for feature in features) != tuple(range(len(features))):
        return None
    if expected_count is not None and len(features) != expected_count:
        return None

    point_headers: tuple[ObjectivePointHeader, ...] = ()
    points: tuple[ObjectivePointDefinition, ...] = ()
    if phd_path.is_file() and pdx_path.is_file():
        point_headers, points = load_objective_point_data(phd_path, pdx_path)
    return ObjectiveFeatureLayout(
        support_ct_number,
        ct_entry.entity_idx,
        objective_name,
        features,
        point_headers,
        points,
    )


def load_objective_point_data(
    header_path: str | Path,
    point_path: str | Path,
) -> tuple[
    tuple[ObjectivePointHeader, ...],
    tuple[ObjectivePointDefinition, ...],
]:
    phd_path = Path(header_path)
    pdx_path = Path(point_path)
    header_root = _xml_root(phd_path)
    point_root = _xml_root(pdx_path)
    if header_root.tag != "PHDRecords":
        raise BmsSupportError(
            f"{phd_path}: expected PHDRecords root, got {header_root.tag!r}"
        )
    if point_root.tag != "PDRecords":
        raise BmsSupportError(
            f"{pdx_path}: expected PDRecords root, got {point_root.tag!r}"
        )

    points: list[ObjectivePointDefinition] = []
    for row_index, node in enumerate(point_root.findall("PD")):
        context = f"{pdx_path}: PD row {row_index}"
        index = _required_xml_int(node.attrib.get("Num"), context, "Num")
        if index != row_index:
            raise BmsSupportError(
                f"{context}: expected contiguous Num {row_index}, got {index}"
            )
        points.append(
            ObjectivePointDefinition(
                index=index,
                offset_x=_required_xml_float(
                    node.findtext("OffsetX"), context, "OffsetX"
                ),
                offset_y=_required_xml_float(
                    node.findtext("OffsetY"), context, "OffsetY"
                ),
                offset_z=_required_xml_float(
                    node.findtext("OffsetZ"), context, "OffsetZ"
                ),
                type_=_optional_xml_int(node, "Type", context),
                flags=_optional_xml_int(node, "Flags", context),
                heading=_optional_xml_float(node, "Heading", context),
                max_height=_optional_xml_float(node, "MaxHeight", context),
                max_width=_optional_xml_float(node, "MaxWidth", context),
                max_length=_optional_xml_float(node, "MaxLength", context),
                branch_index=_optional_xml_int(node, "BranchIdx", context),
                root_index=_optional_xml_int(node, "RootIdx", context),
                taxiway_letter=_optional_xml_int(
                    node, "TaxiwayLetter", context
                ),
                runway_number=_optional_xml_int(node, "RunwayNumber", context),
                runway_side=_optional_xml_int(node, "RunwaySide", context),
                crossing_point=_optional_xml_boolean_int(
                    node, "CrossingPoint", context
                ),
                parking_point_group=_optional_xml_int(
                    node, "ParkingPointGroup", context
                ),
            )
        )

    headers: list[ObjectivePointHeader] = []
    for row_index, node in enumerate(header_root.findall("PHD")):
        context = f"{phd_path}: PHD row {row_index}"
        index = _required_xml_int(node.attrib.get("Num"), context, "Num")
        if index != row_index:
            raise BmsSupportError(
                f"{context}: expected contiguous Num {row_index}, got {index}"
            )
        dependencies = _numbered_xml_ints(
            node, "FeatureDependencyIdx_", context
        )
        header = ObjectivePointHeader(
            index=index,
            objective_index=_required_xml_int(
                node.findtext("ObjIdx"), context, "ObjIdx"
            ),
            type_=_required_xml_int(node.findtext("Type"), context, "Type"),
            point_count=_required_xml_int(
                node.findtext("PointCount"), context, "PointCount"
            ),
            feature_dependency_indices=tuple(
                dependencies[item] for item in sorted(dependencies)
            ),
            data=_required_xml_float(node.findtext("Data"), context, "Data"),
            first_point_index=_required_xml_int(
                node.findtext("FirstPtIdx"), context, "FirstPtIdx"
            ),
            runway_texture=_required_xml_int(
                node.findtext("RunwayTexture"), context, "RunwayTexture"
            ),
            runway_number=_required_xml_int(
                node.findtext("RunwayNumber"), context, "RunwayNumber"
            ),
            landing_pattern=_required_xml_int(
                node.findtext("LandingPattern"), context, "LandingPattern"
            ),
        )
        if header.point_count < 0 or header.first_point_index < 0:
            raise BmsSupportError(
                f"{context}: point count and first point index must be nonnegative"
            )
        if header.end_point_index > len(points):
            raise BmsSupportError(
                f"{context}: point slice {header.first_point_index}:"
                f"{header.end_point_index} exceeds {len(points)} PDX points"
            )
        headers.append(header)
    return tuple(headers), tuple(points)


def _load_objective_data(path: Path) -> tuple[str, int]:
    objective_data = _xml_root(path).find("OCD")
    if objective_data is None:
        return "", -1
    return (
        (objective_data.findtext("Name") or "").strip(),
        _safe_int(objective_data.findtext("CtIdx"), default=-1),
    )


def _load_objective_feature_definitions(
    support: SupportData,
    path: Path,
) -> tuple[ObjectiveFeatureDefinition, ...]:
    features: list[ObjectiveFeatureDefinition] = []
    for node in _xml_root(path).findall("FED"):
        index_text = node.attrib.get("Num")
        if index_text is None:
            continue
        feature_ct_idx = _safe_int(node.findtext("FeatureCtIdx"), default=-1)
        value_text = node.findtext("Value")
        class_table = support.ct_by_number.get(feature_ct_idx)
        model_dimensions = None
        if class_table is not None:
            for models_dir in support.paths.models_dirs:
                parent_path = _casefold_path(
                    models_dir,
                    str(class_table.graphics_normal),
                    "Parent.dat",
                )
                if parent_path.is_file():
                    model_dimensions = load_model_dimensions(parent_path)
                    break
        features.append(
            ObjectiveFeatureDefinition(
                index=_safe_int(index_text, default=len(features)),
                feature_ct_idx=feature_ct_idx,
                feature_class=support.fcd_by_ct_idx.get(feature_ct_idx),
                value=None if value_text is None else _safe_int(value_text),
                offset_x=_safe_float(node.findtext("OffsetX")),
                offset_y=_safe_float(node.findtext("OffsetY")),
                offset_z=_safe_float(node.findtext("OffsetZ")),
                heading=_safe_float(node.findtext("Heading")),
                model_dimensions=model_dimensions,
                graphics_normal=(
                    None if class_table is None else class_table.graphics_normal
                ),
                class_table=class_table,
            )
        )
    return tuple(features)


def _casefold_path(base: Path, *parts: str) -> Path:
    current = base
    for part in parts:
        expected = current / part
        if expected.exists() or not current.is_dir():
            current = expected
            continue
        matches = [
            child
            for child in current.iterdir()
            if child.name.casefold() == part.casefold()
        ]
        current = matches[0] if len(matches) == 1 else expected
    return current


def _windows_relative_path(root: Path, value: str) -> Path:
    parts = (part for part in value.replace("/", "\\").split("\\") if part)
    return _casefold_path(root, *parts)


def _require_files(*paths: Path) -> None:
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise BmsSupportError(
            "missing required support files: "
            + ", ".join(str(path) for path in missing)
        )


def _require_dirs(*paths: Path) -> None:
    missing = [path for path in paths if not path.is_dir()]
    if missing:
        raise BmsSupportError(
            "missing required support directories: "
            + ", ".join(str(path) for path in missing)
        )


def _optional_file(path: Path) -> Path | None:
    return path if path.is_file() else None


def _xml_root(path: str | Path) -> ET.Element:
    return ET.parse(Path(path)).getroot()


def _safe_int(text: str | None, *, default: int = 0) -> int:
    if text is None:
        return default
    try:
        return int(text.strip())
    except ValueError:
        return default


def _safe_float(text: str | None, *, default: float = 0.0) -> float:
    if text is None:
        return default
    try:
        return float(text.strip())
    except ValueError:
        return default


def _numbered_xml_ints(
    node: ET.Element,
    prefix: str,
    context: str,
) -> dict[int, int]:
    values: dict[int, int] = {}
    for child in node:
        if not child.tag.startswith(prefix):
            continue
        suffix = child.tag[len(prefix) :]
        if not suffix.isdigit():
            raise BmsSupportError(
                f"{context}: invalid numbered field {child.tag!r}"
            )
        index = int(suffix)
        if index in values:
            raise BmsSupportError(f"{context}: duplicate field {child.tag}")
        values[index] = _required_xml_int(child.text, context, child.tag)
    return values


def _required_xml_text(node: ET.Element, name: str, context: str) -> str:
    child = node.find(name)
    if child is None or child.text is None:
        raise BmsSupportError(f"{context}: missing {name}")
    return child.text.strip()


def _required_xml_int(text: str | None, context: str, name: str) -> int:
    if text is None:
        raise BmsSupportError(f"{context}: missing {name}")
    try:
        return int(text.strip())
    except ValueError as exc:
        raise BmsSupportError(f"{context}: invalid {name} {text!r}") from exc


def _required_xml_float(text: str | None, context: str, name: str) -> float:
    if text is None:
        raise BmsSupportError(f"{context}: missing {name}")
    try:
        value = float(text.strip())
    except ValueError as exc:
        raise BmsSupportError(f"{context}: invalid {name} {text!r}") from exc
    if not math.isfinite(value):
        raise BmsSupportError(f"{context}: non-finite {name} {text!r}")
    return value


def _optional_xml_int(
    node: ET.Element,
    name: str,
    context: str,
) -> int | None:
    text = node.findtext(name)
    return None if text is None else _required_xml_int(text, context, name)


def _optional_xml_boolean_int(
    node: ET.Element,
    name: str,
    context: str,
) -> int | None:
    text = node.findtext(name)
    if text is None:
        return None
    normalized = text.strip().casefold()
    if normalized in {"true", "false"}:
        return int(normalized == "true")
    return _required_xml_int(text, context, name)


def _optional_xml_float(
    node: ET.Element,
    name: str,
    context: str,
) -> float | None:
    text = node.findtext(name)
    return None if text is None else _required_xml_float(text, context, name)
