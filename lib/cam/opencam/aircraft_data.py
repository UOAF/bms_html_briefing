"""Deterministic projections of BMS aircraft protobuf-text support files.

This module reads authored inputs, not flight-performance estimates. Omitted
values remain absent (None); tables retain their own axes and multipliers.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import math
from pathlib import Path
import re


class AircraftDataError(ValueError):
    """Invalid or unsupported aircraft support data."""


@dataclass(frozen=True)
class _Message:
    fields: dict[str, tuple[object, ...]]

    def one(self, name: str, default=None):
        values = self.fields.get(name, ())
        if len(values) > 1:
            raise AircraftDataError(f"duplicate singular field {name}")
        return values[0] if values else default

    def message(self, name: str) -> _Message:
        value = self.one(name, _Message({}))
        if not isinstance(value, _Message):
            raise AircraftDataError(f"{name} must be a message")
        return value

    def scalar(self, name: str, kind: type, default=None):
        value = self.one(name, default)
        if value is None:
            return None
        if kind is float and type(value) in (int, float):
            value = float(value)
        if type(value) is not kind:
            raise AircraftDataError(f"{name} must be {kind.__name__}")
        if kind is float and not math.isfinite(value):
            raise AircraftDataError(f"{name} must be finite")
        return value

    def numbers(self, name: str) -> tuple[float, ...]:
        values = self.fields.get(name, ())
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise AircraftDataError(f"{name} must contain finite numbers")
        return tuple(float(v) for v in values)

    def scalars(self) -> dict[str, int | float | bool | str]:
        result = {}
        for name, values in self.fields.items():
            if any(isinstance(v, _Message) for v in values):
                continue
            if len(values) != 1:
                raise AircraftDataError(f"duplicate singular field {name}")
            result[name] = values[0]
        return result


# A token scanner, rather than regex searches across nested messages. Every
# non-comment byte must belong to a supported textproto token.
_TOKEN = re.compile(
    r"""(?P<skip>\s+|\#[^\n]*|//[^\n]*|/\*[\s\S]*?\*/)"""
    r"""|(?P<string>"(?:[^"\\\r\n]|\\.)*"|'(?:[^'\\\r\n]|\\.)*')"""
    r"""|(?P<number>[-+]?(?:0[xX][0-9a-fA-F]+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?))"""
    r"""|(?P<name>[A-Za-z_][A-Za-z_0-9.]*)"""
    r"""|(?P<punct>[{}<>:\[\],;])"""
)


def _parse(text: str) -> _Message:
    tokens = []
    offset = 0
    while offset < len(text):
        match = _TOKEN.match(text, offset)
        if match is None:
            line = text.count("\n", 0, offset) + 1
            raise AircraftDataError(f"unsupported textproto token at line {line}")
        if match.lastgroup != "skip":
            tokens.append((match.lastgroup, match.group()))
        offset = match.end()
    position = 0

    def peek():
        return tokens[position][1] if position < len(tokens) else None

    def pop():
        nonlocal position
        if position >= len(tokens):
            raise AircraftDataError("unexpected end of textproto")
        token = tokens[position]
        position += 1
        return token

    def scalar():
        kind, token = pop()
        if kind == "string":
            parts = [ast.literal_eval(token)]
            while position < len(tokens) and tokens[position][0] == "string":
                parts.append(ast.literal_eval(pop()[1]))
            return "".join(parts)
        if kind == "number":
            if "x" in token.lower():
                return int(token, 16)
            if any(c in token for c in ".eE"):
                value = float(token)
                if not math.isfinite(value):
                    raise AircraftDataError("non-finite number")
                return value
            # Textproto integer literals with a leading zero are octal.
            digits = token.lstrip("+-")
            return int(token, 8 if len(digits) > 1 and digits.startswith("0") else 10)
        if kind == "name":
            if token in ("true", "false"):
                return token == "true"
            return token  # preserve enum identifiers
        raise AircraftDataError(f"expected scalar, got {token!r}")

    def value():
        if peek() in ("{", "<"):
            opener = pop()[1]
            return message("}" if opener == "{" else ">")
        return scalar()

    def message(end=None):
        fields = {}
        while peek() is not None and peek() != end:
            kind, name = pop()
            if kind != "name":
                raise AircraftDataError(f"expected field name, got {name!r}")
            if peek() == ":":
                pop()
            elif peek() not in ("{", "<"):
                raise AircraftDataError(f"missing ':' after {name}")
            values = []
            if peek() == "[":
                pop()
                while peek() != "]":
                    values.append(value())
                    if peek() == ",":
                        pop()
                    elif peek() != "]":
                        raise AircraftDataError(f"missing list separator in {name}")
                pop()
            else:
                values.append(value())
            fields.setdefault(name, []).extend(values)
            if peek() in (",", ";"):
                pop()
        if end is not None:
            if peek() != end:
                raise AircraftDataError(f"unclosed message, expected {end}")
            pop()
        return _Message({key: tuple(values) for key, values in fields.items()})

    return message()


@dataclass(frozen=True)
class AircraftTable:
    """Authored row-major table; absent axes/multiplier are not invented."""

    source_field: str
    title: str | None
    x_breakpoints: tuple[float, ...] | None
    y_breakpoints: tuple[float, ...] | None
    x_title: str | None
    y_title: str | None
    multiplier: float | None
    rows: tuple[tuple[float, ...], ...]

    def to_view(self) -> dict[str, object]:
        return {
            "source_field": self.source_field,
            "title": self.title,
            "x_breakpoints": None if self.x_breakpoints is None else list(self.x_breakpoints),
            "y_breakpoints": None if self.y_breakpoints is None else list(self.y_breakpoints),
            "x_title": self.x_title,
            "y_title": self.y_title,
            "multiplier": self.multiplier,
            "rows": [list(row) for row in self.rows],
        }


def _table(node: _Message, path: str) -> AircraftTable:
    x, y = node.message("x_axis"), node.message("y_axis")
    rows = []
    for row in node.fields.get("data", ()):
        if not isinstance(row, _Message):
            raise AircraftDataError(f"{path}.data must be a message")
        rows.append(row.numbers("values"))
    if rows and any(len(row) != len(rows[0]) for row in rows):
        raise AircraftDataError(f"{path}: ragged table rows")
    return AircraftTable(
        source_field=path,
        title=node.scalar("title", str),
        x_breakpoints=x.numbers("breakpoints") if "breakpoints" in x.fields else None,
        y_breakpoints=y.numbers("breakpoints") if "breakpoints" in y.fields else None,
        x_title=x.scalar("title", str),
        y_title=y.scalar("title", str),
        multiplier=node.scalar("multiplier", float),
        rows=tuple(rows),
    )


@dataclass(frozen=True)
class AircraftAirframeData:
    empty_weight_lb: float | None
    internal_fuel_lb: float | None
    wing_area_sqft: float | None

    def to_view(self) -> dict[str, object]:
        return {
            "empty_weight_lb": self.empty_weight_lb,
            "internal_fuel_lb": self.internal_fuel_lb,
            "wing_area_sqft": self.wing_area_sqft,
        }


@dataclass(frozen=True)
class AircraftEngineData:
    parameters: dict[str, int | float | bool | str]
    auxiliary_parameters: dict[str, int | float | bool | str]
    tables: dict[str, AircraftTable]

    @property
    def has_fuel_flow(self) -> bool | None:
        value = self.parameters.get("has_fuel_flow")
        if value is not None and type(value) is not bool:
            raise AircraftDataError("engine.has_fuel_flow must be bool")
        return value

    @property
    def number_of_engines(self) -> int | None:
        value = self.auxiliary_parameters.get("n_engines")
        if value is not None and type(value) is not int:
            raise AircraftDataError("auxaero.engine.n_engines must be int")
        return value

    def to_view(self) -> dict[str, object]:
        return {
            "parameters": dict(self.parameters),
            "auxiliary_parameters": dict(self.auxiliary_parameters),
            "tables": {name: table.to_view() for name, table in self.tables.items()},
        }


@dataclass(frozen=True)
class AircraftAerodynamics:
    parameters: dict[str, int | float | bool | str]
    breakpoints: dict[str, tuple[float, ...]]
    tables: dict[str, AircraftTable]

    def to_view(self) -> dict[str, object]:
        return {
            "parameters": dict(self.parameters),
            "breakpoints": {name: list(values) for name, values in self.breakpoints.items()},
            "tables": {name: table.to_view() for name, table in self.tables.items()},
        }


@dataclass(frozen=True)
class AircraftStoresDrag:
    limiter_type: str | None
    values: tuple[float, ...]

    def to_view(self) -> dict[str, object]:
        return {"limiter_type": self.limiter_type, "values": list(self.values)}


@dataclass(frozen=True)
class AircraftSimulationData:
    source_path: Path
    has_cft: bool
    cft_fuel_lb: int
    cft_fuel_rate: float
    fm_type: str | None
    airframe: AircraftAirframeData
    engine: AircraftEngineData
    aerodynamics: dict[str, AircraftAerodynamics]
    fuel_system: dict[str, int | float | bool | str]
    refueling: dict[str, int | float | bool | str]
    flaps: dict[str, dict[str, int | float | bool | str]]
    hardpoint_groups: tuple[str, ...]
    external_hardpoints: tuple[float, ...]
    stores_drag: AircraftStoresDrag | None

    def to_view(self) -> dict[str, object]:
        return {
            "source_path": str(self.source_path),
            "fm_type": self.fm_type,
            "has_cft": self.has_cft,
            "cft_fuel_lb": self.cft_fuel_lb,
            "cft_fuel_rate": self.cft_fuel_rate,
            "airframe": self.airframe.to_view(),
            "engine": self.engine.to_view(),
            "aerodynamics": {name: aero.to_view() for name, aero in self.aerodynamics.items()},
            "fuel_system": dict(self.fuel_system),
            "refueling": dict(self.refueling),
            "flaps": {name: dict(values) for name, values in self.flaps.items()},
            "hardpoint_groups": list(self.hardpoint_groups),
            "external_hardpoints": list(self.external_hardpoints),
            "stores_drag": None if self.stores_drag is None else self.stores_drag.to_view(),
        }


_ENGINE_TABLES = (
    "alt_mach_thrust_idle_table",
    "alt_mach_thrust_mil_table",
    "alt_mach_thrust_ab_table",
    "alt_alpha_thrust_factor_table",
    "alt_mach_fuel_flow_idle_table",
    "alt_mach_fuel_flow_mil_table",
    "alt_mach_fuel_flow_ab_table",
    "alt_mach_idle_rpm_chart",
    "alt_mach_max_rpm_chart",
    "alt_mach_max_rpm_ab_chart",
    "alt_mach_nozzle_max_chart",
    "alt_spool_rate_table",
    "alt_function66_table",
)

_AERO_TABLES = {
    "aero": (
        "mach_alpha_cl_table", "mach_alpha_cd_table",
        "mach_alpha_cl_tef_table", "mach_alpha_cd_tef_table",
    ),
    "aero_new2": (
        "clift_table", "cdrag_table", "perc_lift_table", "perc_drag_table",
        "c_lift_tef_table", "c_drag_tef_table", "cl_cft_table", "cd_cft_table",
    ),
}


def parse_aircraft_simulation_data(text: str, source_path: str | Path) -> AircraftSimulationData:
    """Read the supported weight/fuel/aero fields without interpolation or estimates."""
    source_path = Path(source_path)
    try:
        root = _parse(text)
        airframe, aux = root.message("airframe"), root.message("auxaero")
        engine, fuel = root.message("engine"), aux.message("fuel")
        aero_new = root.message("aero_new2")
        has_cft = aero_new.scalar("has_cft", bool, False)
        cft_fuel = fuel.scalar("cft_fuel", int, 0)
        cft_rate = fuel.scalar("fuel_CFT_rate", float, 0.0)
        if has_cft and "cft_fuel" not in fuel.fields:
            raise AircraftDataError("has_cft is true but cft_fuel is absent")
        if cft_fuel < 0 or cft_rate < 0:
            raise AircraftDataError("negative CFT fuel metadata")
        aero_data = {}
        for section, names in _AERO_TABLES.items():
            if section not in root.fields:
                continue
            node = root.message(section)
            aero_data[section] = AircraftAerodynamics(
                parameters=node.scalars(),
                breakpoints={
                    name: node.message(name).numbers("breakpoints")
                    for name in ("mach_bp", "alpha_bp", "beta_perc_bp", "mach_tef_bp", "alpha_tef_bp")
                    if name in node.fields
                },
                tables={
                    name: _table(node.message(name), f"{section}.{name}")
                    for name in names if name in node.fields
                },
            )
        engine_data = AircraftEngineData(
            parameters=engine.scalars(),
            auxiliary_parameters=aux.message("engine").scalars(),
            tables={
                name: _table(engine.message(name), f"engine.{name}")
                for name in _ENGINE_TABLES if name in engine.fields
            },
        )
        # Validate typed convenience properties when loading, not on first use.
        engine_data.has_fuel_flow
        engine_data.number_of_engines
        stores_drag = None
        for limit in root.message("limits").fields.get("limit", ()):
            if not isinstance(limit, _Message):
                raise AircraftDataError("limits.limit must be a message")
            if limit.scalar("key", str) == "LIM_STORES_DRAG":
                if stores_drag is not None:
                    raise AircraftDataError("duplicate LIM_STORES_DRAG")
                stores_drag = AircraftStoresDrag(
                    limiter_type=limit.scalar("type", str),
                    values=limit.message("data").numbers("values"),
                )
        hardpoints = aux.message("hardpoints")
        groups = hardpoints.fields.get("hardpoint_grp", ())
        if any(type(value) is not str for value in groups):
            raise AircraftDataError("hardpoint_grp must contain strings")
        return AircraftSimulationData(
            source_path=source_path,
            has_cft=has_cft, cft_fuel_lb=cft_fuel, cft_fuel_rate=cft_rate,
            fm_type=root.scalar("fmtype", str),
            airframe=AircraftAirframeData(
                empty_weight_lb=airframe.scalar("empty_weight_lbs", float),
                internal_fuel_lb=airframe.scalar("internal_fuel_lbs", float),
                wing_area_sqft=airframe.scalar("area_sqft", float),
            ),
            engine=engine_data, aerodynamics=aero_data,
            fuel_system=fuel.scalars(),
            refueling=aux.message("air_air_refuel").scalars(),
            flaps={name: aux.message(name).scalars() for name in ("flaps", "lef", "tef") if name in aux.fields},
            hardpoint_groups=tuple(groups),
            external_hardpoints=hardpoints.message("is_external_hardpoint").numbers("values"),
            stores_drag=stores_drag,
        )
    except (AircraftDataError, ValueError, SyntaxError, OverflowError) as exc:
        raise AircraftDataError(f"{source_path}: {exc}") from exc
