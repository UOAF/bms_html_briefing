"""Falcon BMS support-file resolution and lightweight indexes."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
import xml.etree.ElementTree as ET

from .cam_container import CamContainer
from .aircraft_data import (
    AircraftDataError, AircraftSimulationData, parse_aircraft_simulation_data,
)
from .rack_data import AircraftRackCatalog, parse_rack_catalog


class BmsSupportError(RuntimeError):
    """Raised when the live BMS support file layout cannot be resolved."""


@dataclass(frozen=True)
class BmsSupportPaths:
    theater_dir: Path
    campaign_dir: Path
    objects_dir: Path
    strings_path: Path
    ct_path: Path
    ucd_path: Path
    vcd_path: Path


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
    mover_definition_data: int = -1


@dataclass(frozen=True)
class UnitClassEntry:
    number: int
    ct_idx: int
    name: str
    vehicle_ct_indices: tuple[int, ...]


@dataclass(frozen=True)
class VehicleClassEntry:
    number: int
    ct_idx: int
    name: str
    callsign_idx: int
    callsign_slots: int


@dataclass(frozen=True)
class WeaponClassEntry:
    """Weight-related projection of WCD; IDs and CT indices are distinct."""
    number: int
    ct_idx: int
    name: str
    flags: int
    strength: int
    rack_group: int
    weight: int
    drag: int

    @property
    def weight_lb(self) -> int:
        """Authored store/hardware weight, excluding fuel contents."""
        return self.weight

    @property
    def drag_index(self) -> int:
        return self.drag

    @property
    def is_fuel_tank(self) -> bool:
        return bool(self.flags & 0x02)  # WEAP_FUEL

    @property
    def fuel_capacity_lb(self) -> int:
        """Tank Strength is capacity; non-tank Strength has another meaning."""
        return self.strength if self.is_fuel_tank else 0


@dataclass(frozen=True)
class AircraftClassEntry:
    number: int
    airframe_dat_index: int
    source_path: Path



@dataclass(frozen=True)
class AircraftTypeEntry:
    index: int
    name: str
    acdata_path: Path



@dataclass(frozen=True)
class ResolvedAircraftData:
    vehicle: VehicleClassEntry
    class_table: ClassTableEntry
    aircraft_class: AircraftClassEntry
    aircraft_type: AircraftTypeEntry
    simulation_data: AircraftSimulationData

    @property
    def has_cft(self) -> bool:
        return self.simulation_data.has_cft

    @property
    def cft_fuel_lb(self) -> int:
        return self.simulation_data.cft_fuel_lb

    @property
    def cft_fuel_rate(self) -> float:
        return self.simulation_data.cft_fuel_rate

    def to_view(self) -> dict[str, object]:
        return {
            "vehicle_number": self.vehicle.number,
            "ct_index": self.class_table.number,
            "aircraft_class_number": self.aircraft_class.number,
            "airframe_dat_index": self.aircraft_type.index,
            "aircraft_type_name": self.aircraft_type.name,
            "simulation_data": self.simulation_data.to_view(),
        }



@dataclass(frozen=True)
class SupportData:
    paths: BmsSupportPaths
    strings_by_id: dict[int, str]
    ct_by_number: dict[int, ClassTableEntry]
    ucd_by_number: dict[int, UnitClassEntry]
    ucd_by_ct_idx: dict[int, UnitClassEntry]
    vcd_by_number: dict[int, VehicleClassEntry]
    vcd_by_ct_idx: dict[int, VehicleClassEntry]
    aircraft_data_by_vehicle_number: dict[int, ResolvedAircraftData] = field(
        default_factory=dict, compare=False, repr=False
    )

    # These optional catalogs must not prevent ordinary CAM briefing extraction.
    @cached_property
    def acd_by_number(self) -> dict[int, AircraftClassEntry]:
        return load_aircraft_classes(_casefold_path(self.paths.objects_dir, "Falcon4_ACD.xml"))

    @cached_property
    def ac_types(self) -> tuple[AircraftTypeEntry, ...]:
        return load_aircraft_types(
            _aircraft_file(self.paths.theater_dir, "AcTypes.lst"),
            theater_dir=self.paths.theater_dir,
        )

    @cached_property
    def wcd_by_number(self) -> dict[int, WeaponClassEntry]:
        return load_weapon_classes(_casefold_path(self.paths.objects_dir, "Falcon4_WCD.xml"))

    @cached_property
    def wcd_by_ct_idx(self) -> dict[int, WeaponClassEntry]:
        return {entry.ct_idx: entry for entry in self.wcd_by_number.values()}

    @cached_property
    def rack_catalog(self) -> AircraftRackCatalog:
        path = _casefold_path(self.paths.objects_dir, "BmsRack.dat")
        if not path.is_file() and self.paths.theater_dir.parent.name.casefold() == "data":
            path = _casefold_path(self.paths.theater_dir.parent, "TerrData", "Objects", "BmsRack.dat")
        return load_aircraft_rack_catalog(path)

    def resolve_aircraft_for_vehicle(
        self,
        vehicle_number: int,
    ) -> ResolvedAircraftData:
        """Strictly resolve VCD -> CT -> ACD -> AcTypes -> Acdata."""

        if type(vehicle_number) is not int or vehicle_number < 0:
            raise BmsSupportError(
                f"vehicle number must be a nonnegative integer, got {vehicle_number!r}"
            )
        cached = self.aircraft_data_by_vehicle_number.get(vehicle_number)
        if cached is not None:
            return cached
        vehicle = self.vcd_by_number.get(vehicle_number)
        if vehicle is None:
            raise BmsSupportError(f"VCD Num {vehicle_number} does not exist")
        class_table = self.ct_by_number.get(vehicle.ct_idx)
        if class_table is None:
            raise BmsSupportError(
                f"VCD Num {vehicle_number} CtIdx {vehicle.ct_idx} has no CT row"
            )
        acd_number = class_table.mover_definition_data
        aircraft_class = self.acd_by_number.get(acd_number)
        if aircraft_class is None:
            raise BmsSupportError(
                f"VCD Num {vehicle_number} -> CT Num {class_table.number} "
                f"MoverDefinitionData {acd_number} has no ACD row"
            )
        ac_type_index = aircraft_class.airframe_dat_index
        ac_types_by_index = {entry.index: entry for entry in self.ac_types}
        aircraft_type = ac_types_by_index.get(ac_type_index)
        if aircraft_type is None:
            raise BmsSupportError(
                f"VCD Num {vehicle_number} -> CT Num {class_table.number} -> "
                f"ACD Num {aircraft_class.number} AirframeDatIdx {ac_type_index} "
                f"does not select one of {len(self.ac_types)} AcTypes entries"
            )
        try:
            simulation_data = load_aircraft_simulation_data(
                aircraft_type.acdata_path
            )
        except BmsSupportError as exc:
            raise BmsSupportError(
                f"VCD Num {vehicle_number} -> CT Num {class_table.number} -> "
                f"ACD Num {aircraft_class.number} -> AcTypes index "
                f"{ac_type_index} ({aircraft_type.name!r}): {exc}"
            ) from exc
        resolved = ResolvedAircraftData(
            vehicle=vehicle,
            class_table=class_table,
            aircraft_class=aircraft_class,
            aircraft_type=aircraft_type,
            simulation_data=simulation_data,
        )
        self.aircraft_data_by_vehicle_number[vehicle_number] = resolved
        return resolved



def resolve_support_paths(theater_dir: str | Path) -> BmsSupportPaths:
    theater_path = Path(theater_dir).expanduser().resolve()
    if not theater_path.is_dir():
        raise BmsSupportError(f"theater directory does not exist: {theater_path}")

    campaign_dir = _casefold_path(theater_path, "Campaign")
    objects_dir = _casefold_path(theater_path, "TerrData", "Objects")
    paths = BmsSupportPaths(
        theater_dir=theater_path,
        campaign_dir=campaign_dir,
        objects_dir=objects_dir,
        strings_path=_casefold_path(campaign_dir, "Strings.txt"),
        ct_path=_casefold_path(objects_dir, "Falcon4_CT.xml"),
        ucd_path=_casefold_path(objects_dir, "Falcon4_UCD.xml"),
        vcd_path=_casefold_path(objects_dir, "Falcon4_VCD.xml"),
    )
    _require_files(paths.strings_path, paths.ct_path, paths.ucd_path, paths.vcd_path)
    return paths


def detect_container_version(container: CamContainer) -> int | None:
    for entry in container.entries:
        if not entry.name.lower().endswith(".ver"):
            continue
        text = entry.decoded.decode("ascii", errors="replace").strip("\x00\r\n\t ")
        if text.isdigit():
            return int(text)
    return None


def load_support_data(paths: BmsSupportPaths) -> SupportData:
    ct_by_number = load_class_table(paths.ct_path)
    ucd_by_number = load_unit_classes(paths.ucd_path)
    vcd_by_number = load_vehicle_classes(paths.vcd_path)
    return SupportData(
        paths=paths,
        strings_by_id=load_strings_by_id(paths.strings_path),
        ct_by_number=ct_by_number,
        ucd_by_number=ucd_by_number,
        ucd_by_ct_idx={entry.ct_idx: entry for entry in ucd_by_number.values()},
        vcd_by_number=vcd_by_number,
        vcd_by_ct_idx={entry.ct_idx: entry for entry in vcd_by_number.values()},
    )


def load_class_table(path: str | Path) -> dict[int, ClassTableEntry]:
    root = _xml_root(path)
    entries: dict[int, ClassTableEntry] = {}
    for node in root.findall("CT"):
        number_text = node.attrib.get("Num")
        if number_text is None:
            continue
        number = _safe_int(number_text, default=-1)
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
            mover_definition_data=_safe_int(node.findtext("MoverDefinitionData"), default=-1),
        )
    return entries


def load_unit_classes(path: str | Path) -> dict[int, UnitClassEntry]:
    root = _xml_root(path)
    entries: dict[int, UnitClassEntry] = {}
    for node in root.findall("UCD"):
        number_text = node.attrib.get("Num")
        if number_text is None:
            continue
        number = _safe_int(number_text, default=-1)
        if number < 0:
            continue
        vehicle_ct_indices = tuple(
            value
            for index in range(16)
            if (value := _safe_int(node.findtext(f"VehicleCtIdx_{index}"), default=-1)) >= 0
        )
        entries[number] = UnitClassEntry(
            number=number,
            ct_idx=_safe_int(node.findtext("CtIdx"), default=-1),
            name=(node.findtext("Name") or "").strip(),
            vehicle_ct_indices=vehicle_ct_indices,
        )
    return entries


def load_vehicle_classes(path: str | Path) -> dict[int, VehicleClassEntry]:
    root = _xml_root(path)
    entries: dict[int, VehicleClassEntry] = {}
    for node in root.findall("VCD"):
        number_text = node.attrib.get("Num")
        if number_text is None:
            continue
        number = _safe_int(number_text, default=-1)
        if number < 0:
            continue
        entries[number] = VehicleClassEntry(
            number=number,
            ct_idx=_safe_int(node.findtext("CtIdx"), default=-1),
            name=(node.findtext("Name") or "").strip(),
            callsign_idx=_safe_int(node.findtext("CallsignIdx")),
            callsign_slots=_safe_int(node.findtext("CallsignSlots")),
        )
    return entries


def load_strings_by_id(path: str | Path) -> dict[int, str]:
    strings: dict[int, str] = {}
    for line in Path(path).read_text(encoding="latin-1", errors="replace").splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            strings[int(parts[0])] = parts[1].strip()
    return strings


def format_campaign_time_z(value_ms: int | None) -> str | None:
    if not isinstance(value_ms, int) or value_ms < 0:
        return None
    total_seconds, milliseconds = divmod(value_ms, 1000)
    hours = (total_seconds // 3600) % 24
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if milliseconds:
        return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}z"
    return f"{hours:02}:{minutes:02}:{seconds:02}z"


def _require_files(*paths: Path) -> None:
    missing = [path for path in paths if not path.is_file()]
    if missing:
        message = ", ".join(str(path) for path in missing)
        raise BmsSupportError(f"missing required support files: {message}")


def _xml_root(path: str | Path) -> ET.Element:
    return ET.parse(Path(path)).getroot()


def _safe_int(text: str | None, *, default: int = 0) -> int:
    if text is None:
        return default
    try:
        return int(text.strip())
    except ValueError:
        return default


def load_aircraft_classes(
    path: str | Path,
) -> dict[int, AircraftClassEntry]:
    source_path = Path(path)
    root = _xml_root(source_path)
    entries: dict[int, AircraftClassEntry] = {}
    for row_index, node in enumerate(root.findall("ACD")):
        context = f"{source_path}: ACD row {row_index}"
        number = _required_xml_int(node.attrib.get("Num"), context, "Num")
        if number < 0:
            raise BmsSupportError(f"{context}: negative Num {number}")
        if number in entries:
            raise BmsSupportError(f"{context}: duplicate Num {number}")
        entries[number] = AircraftClassEntry(
            number=number,
            airframe_dat_index=_required_xml_int(
                node.findtext("AirframeDatIdx"), context, "AirframeDatIdx"
            ),
            source_path=source_path,
        )
    return entries



def load_aircraft_types(
    path: str | Path,
    *,
    theater_dir: str | Path | None = None,
) -> tuple[AircraftTypeEntry, ...]:
    source_path = Path(path)
    try:
        lines = source_path.read_text(
            encoding="utf-8-sig", errors="strict"
        ).splitlines()
    except (OSError, UnicodeError) as exc:
        raise BmsSupportError(f"cannot read AcTypes list {source_path}: {exc}") from exc
    if not lines:
        raise BmsSupportError(f"{source_path}: empty AcTypes list")
    try:
        declared_count = int(lines[0].strip())
    except ValueError as exc:
        raise BmsSupportError(
            f"{source_path}: first line is not an entry count"
        ) from exc
    names = lines[1:]
    if len(names) != declared_count:
        raise BmsSupportError(
            f"{source_path}: declares {declared_count} AcTypes entries, "
            f"contains {len(names)}"
        )

    base_acdata_dir: Path | None = None
    if theater_dir is not None:
        theater_path = Path(theater_dir)
        base_data_dir = (
            theater_path
            if theater_path.name.casefold() == "data"
            else theater_path.parent
            if theater_path.parent.name.casefold() == "data"
            else theater_path
        )
        candidate = _casefold_path(base_data_dir, "Sim", "Acdata")
        if candidate != source_path.parent:
            base_acdata_dir = candidate

    entries: list[AircraftTypeEntry] = []
    for index, raw_name in enumerate(names):
        name = raw_name.strip()
        if not name:
            raise BmsSupportError(f"{source_path}: AcTypes index {index} is empty")
        acdata_path = _casefold_path(source_path.parent, f"{name}.txtpb")
        if (
            not acdata_path.is_file()
            and base_acdata_dir is not None
            and base_acdata_dir.is_dir()
        ):
            acdata_path = _casefold_path(base_acdata_dir, f"{name}.txtpb")
        entries.append(
            AircraftTypeEntry(
                index=index,
                name=name,
                acdata_path=acdata_path,
            )
        )
    return tuple(entries)



def load_aircraft_simulation_data(
    path: str | Path,
) -> AircraftSimulationData:
    source_path = Path(path)
    if not source_path.is_file():
        raise BmsSupportError(f"Acdata file does not exist: {source_path}")
    try:
        text = source_path.read_text(encoding="utf-8-sig", errors="strict")
    except (OSError, UnicodeError) as exc:
        raise BmsSupportError(f"cannot read Acdata {source_path}: {exc}") from exc

    try:
        return parse_aircraft_simulation_data(text, source_path)
    except AircraftDataError as exc:
        raise BmsSupportError(str(exc)) from exc



def load_aircraft_rack_catalog(path: str | Path) -> AircraftRackCatalog:
    source_path = Path(path)
    try:
        return parse_rack_catalog(
            source_path.read_text(encoding="latin-1"), source_path
        )
    except (OSError, ValueError) as exc:
        raise BmsSupportError(f"cannot load rack catalog {source_path}: {exc}") from exc



def _casefold_path(base: Path, *parts: str) -> Path:
    """Resolve known BMS path components case-insensitively on Linux."""

    current = base
    for part in parts:
        expected = current / part
        if expected.exists() or not current.is_dir():
            current = expected
            continue
        matches = [
            child for child in current.iterdir()
            if child.name.casefold() == part.casefold()
        ]
        current = matches[0] if len(matches) == 1 else expected
    return current



def _required_xml_int(text: str | None, context: str, name: str) -> int:
    if text is None:
        raise BmsSupportError(f"{context}: missing {name}")
    try:
        return int(text.strip())
    except ValueError as exc:
        raise BmsSupportError(f"{context}: invalid {name} {text!r}") from exc



def _aircraft_file(theater_dir: Path, filename: str) -> Path:
    """Use theater aircraft data, with BMS's same-installation base fallback."""
    local = _casefold_path(theater_dir, "Sim", "Acdata", filename)
    if local.is_file() or theater_dir.parent.name.casefold() != "data":
        return local
    return _casefold_path(theater_dir.parent, "Sim", "Acdata", filename)


def load_weapon_classes(path: str | Path) -> dict[int, WeaponClassEntry]:
    source_path = Path(path)
    entries = {}
    for node in _xml_root(source_path).findall("WCD"):
        context = f"{source_path}: WCD"
        number = _required_xml_int(node.attrib.get("Num"), context, "Num")
        if number < 0 or number in entries:
            raise BmsSupportError(f"{context}: invalid or duplicate Num {number}")
        def integer(name: str) -> int:
            return _required_xml_int(node.findtext(name), f"{context} Num {number}", name)
        entries[number] = WeaponClassEntry(
            number=number, ct_idx=integer("CtIdx"),
            name=(node.findtext("Name") or "").strip(),
            flags=integer("Flags"), strength=integer("Strength"),
            rack_group=integer("Rackgroup"), weight=integer("Weight"), drag=integer("Drag"),
        )
    return entries
