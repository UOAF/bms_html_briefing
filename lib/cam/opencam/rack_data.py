"""Authored BmsRack.dat hardware definitions; no automatic rack selection."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex


@dataclass(frozen=True)
class RackDirective:
    command: str
    arguments: tuple[str, ...]
    line_number: int

    def to_view(self) -> dict[str, object]:
        return {
            "command": self.command,
            "arguments": list(self.arguments),
            "line_number": self.line_number,
        }


@dataclass(frozen=True)
class RackDefinition:
    name: str
    ct_index: int | None
    station_count: int | None
    weapon_ids: tuple[int, ...]
    sim_weapon_ids: tuple[int, ...]
    weapon_classes: tuple[str, ...]
    directives: tuple[RackDirective, ...]

    def to_view(self) -> dict[str, object]:
        return {
            "name": self.name, "ct_index": self.ct_index,
            "station_count": self.station_count,
            "weapon_ids": list(self.weapon_ids),
            "sim_weapon_ids": list(self.sim_weapon_ids),
            "weapon_classes": list(self.weapon_classes),
            "directives": [item.to_view() for item in self.directives],
        }


@dataclass(frozen=True)
class PylonDefinition:
    ct_index: int | None
    rack_names: tuple[str, ...]
    directives: tuple[RackDirective, ...]

    def to_view(self) -> dict[str, object]:
        return {
            "ct_index": self.ct_index, "rack_names": list(self.rack_names),
            "directives": [item.to_view() for item in self.directives],
        }


@dataclass(frozen=True)
class RackGroup:
    name: str
    pylons: tuple[PylonDefinition, ...]

    def to_view(self) -> dict[str, object]:
        return {"name": self.name, "pylons": [p.to_view() for p in self.pylons]}


@dataclass(frozen=True)
class AircraftRackCatalog:
    source_path: Path
    racks: tuple[RackDefinition, ...]
    groups: tuple[RackGroup, ...]

    def rack(self, name: str) -> RackDefinition:
        matches = [rack for rack in self.racks if rack.name == name]
        if len(matches) != 1:
            raise ValueError(f"{self.source_path}: expected one rack {name!r}, found {len(matches)}")
        return matches[0]

    def group(self, name: str) -> RackGroup:
        matches = [group for group in self.groups if group.name == name]
        if len(matches) != 1:
            raise ValueError(f"{self.source_path}: expected one group {name!r}, found {len(matches)}")
        return matches[0]

    def to_view(self) -> dict[str, object]:
        return {
            "source_path": str(self.source_path),
            "racks": [rack.to_view() for rack in self.racks],
            "groups": [group.to_view() for group in self.groups],
        }


def parse_rack_catalog(text: str, source_path: str | Path) -> AircraftRackCatalog:
    """Preserve declaration and preference order, including all directives."""
    path = Path(source_path)
    racks, groups = [], []
    kind = name = None
    records, pylons = [], []

    def args(directives, command):
        return tuple(arg for d in directives if d.command == command for arg in d.arguments)

    def integer(directives, command):
        values = args(directives, command)
        if not values:
            return None
        if len(values) != 1:
            raise ValueError(f"{path}: duplicate or malformed {command}")
        return int(values[0])

    def flush():
        if kind == "definerack":
            racks.append(RackDefinition(
                name=name, ct_index=integer(records, "rackct"),
                station_count=integer(records, "rackstations"),
                weapon_ids=tuple(int(v) for v in args(records, "addwid")),
                sim_weapon_ids=tuple(int(v) for v in args(records, "addswd")),
                weapon_classes=args(records, "addwclass"),
                directives=tuple(records),
            ))
        elif kind == "definegroup":
            groups.append(RackGroup(
                name=name,
                pylons=tuple(PylonDefinition(
                    ct_index=integer(items, "pylonct"),
                    rack_names=args(items, "addrack"),
                    directives=tuple(items),
                ) for items in pylons),
            ))

    for line_number, line in enumerate(text.splitlines(), 1):
        try:
            tokens = shlex.split(line, comments=True)
            if not tokens:
                continue
            command = tokens[0].lower()
            arguments = tuple(tokens[1:])
            if command in ("definerack", "definegroup"):
                if len(arguments) != 1:
                    raise ValueError("definition requires one name")
                flush()
                kind, name = command, arguments[0]
                records, pylons = [], []
                continue
            if command == "addpylon":
                if kind != "definegroup" or arguments:
                    raise ValueError("addpylon requires a group and no arguments")
                pylons.append([])
                continue
            if kind == "definerack":
                allowed = {"rackct", "rackstations", "addwid", "addswd", "addwclass",
                           "addany", "addloadorder", "weapjettmodes", "rackjettmodes",
                           "smsmodes", "racksmsname"}
                target = records
            elif kind == "definegroup" and pylons:
                allowed = {"pylonct", "addrack", "pylonsmsname"}
                target = pylons[-1]
            else:
                raise ValueError("directive outside a rack or pylon")
            if command not in allowed:
                raise ValueError(f"unsupported directive {command}")
            if command in {"rackct", "rackstations", "pylonct", "addrack"}:
                if len(arguments) != 1:
                    raise ValueError(f"{command} requires one argument")
            if command in {"addwid", "addswd", "addwclass", "addloadorder"}:
                arguments = tuple(part for arg in arguments for part in arg.split(",") if part)
            target.append(RackDirective(command, arguments, line_number))
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
    flush()
    return AircraftRackCatalog(path, tuple(racks), tuple(groups))
