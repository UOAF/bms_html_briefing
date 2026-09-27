"""Approximate clean-aircraft return fuel at 30,000 ft / Mach 0.8.

OpenCAM supplies authored inputs; the interpolation and fuel policy here are
app-owned approximations. AFM engine table units are lbf and lb/hour per engine;
thrust and fuel flow are scaled by the authored engine count.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import math

from lib.cam.opencam.aircraft_data import AircraftSimulationData, AircraftTable

RETURN_ALTITUDE_FT = 30_000
RETURN_MACH = 0.8
ALLOWANCE_LB = 500
ROUNDING_LB = 100
FEET_PER_NM = 1852 / 0.3048

# ISA troposphere at the fixed return altitude.
_TEMPERATURE_K = 288.15 - 0.0065 * RETURN_ALTITUDE_FT * 0.3048
_PRESSURE_PA = 101325 * (_TEMPERATURE_K / 288.15) ** (9.80665 / (287.05287 * 0.0065))
RETURN_TAS_KT = RETURN_MACH * math.sqrt(1.4 * 287.05287 * _TEMPERATURE_K) / (1852 / 3600)
_Q_LBF_SQFT = 0.7 * _PRESSURE_PA * RETURN_MACH ** 2 * 0.09290304 / 4.4482216152605

ASSUMPTIONS = "Min. return fuel @ 30k, 0.8M + 500lb"


class FuelModelError(ValueError):
    """Aircraft inputs do not support the fixed return profile."""


def _number(value: object, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise FuelModelError(f"Missing or invalid {label}.")
    if positive and value <= 0:
        raise FuelModelError(f"{label} must be positive.")
    return float(value)


def _axis(values: tuple[float, ...] | None, label: str) -> tuple[float, ...]:
    if values is None or len(values) < 2:
        raise FuelModelError(f"Missing {label} breakpoints.")
    values = tuple(_number(value, label) for value in values)
    if any(a >= b for a, b in zip(values, values[1:])):
        raise FuelModelError(f"{label} breakpoints must increase.")
    return values


def _bracket(axis: tuple[float, ...], value: float) -> tuple[int, float]:
    if not axis[0] <= value <= axis[-1]:
        raise FuelModelError("Return profile is outside the aircraft tables.")
    index = min(max(bisect_right(axis, value) - 1, 0), len(axis) - 2)
    return index, (value - axis[index]) / (axis[index + 1] - axis[index])


@dataclass(frozen=True)
class _Table:
    x: tuple[float, ...]
    y: tuple[float, ...]
    rows: tuple[tuple[float, ...], ...]

    @classmethod
    def read(cls, table: AircraftTable | None, x=None, y=None) -> "_Table":
        if table is None:
            raise FuelModelError("Required aircraft performance table is missing.")
        xs = _axis(table.x_breakpoints if table.x_breakpoints is not None else x, "x")
        ys = _axis(table.y_breakpoints if table.y_breakpoints is not None else y, "y")
        if len(table.rows) != len(xs) or any(len(row) != len(ys) for row in table.rows):
            raise FuelModelError("Aircraft table dimensions do not match its breakpoints.")
        # Absent authored multipliers mean no scaling in this approximate model.
        scale = 1.0 if table.multiplier is None else _number(table.multiplier, "table multiplier", positive=True)
        rows = tuple(tuple(_number(v, "table value") * scale for v in row) for row in table.rows)
        return cls(xs, ys, rows)

    def at(self, x: float, y: float) -> float:
        i, fx = _bracket(self.x, x)
        j, fy = _bracket(self.y, y)
        a = self.rows[i][j] * (1 - fy) + self.rows[i][j + 1] * fy
        b = self.rows[i + 1][j] * (1 - fy) + self.rows[i + 1][j + 1] * fy
        return a * (1 - fx) + b * fx


def cruise_rate_lb_nm(sim: AircraftSimulationData) -> int:
    """Return a whole-lb/nm rate covering 500 lb through full internal fuel.

    Lift balances weight; drag determines required thrust. Fuel flow is linearly
    interpolated between idle and MIL by thrust fraction. Check endpoints and
    every intervening CL/CD breakpoint, so the rate covers the complete fuel
    weight interval in this piecewise-linear model. No stores or CFT mass/drag
    corrections, auxaero flow factors, or campaign FuelRate are inferred.
    """
    if sim.fm_type != "FM_AFM" or sim.engine.has_fuel_flow is not True:
        raise FuelModelError("This aircraft does not have supported AFM fuel-flow tables.")
    engine_count = _number(sim.engine.number_of_engines, "engine count", positive=True)
    empty = _number(sim.airframe.empty_weight_lb, "empty weight", positive=True)
    capacity = _number(sim.airframe.internal_fuel_lb, "internal fuel capacity", positive=True)
    if capacity < ALLOWANCE_LB:
        raise FuelModelError("Internal fuel capacity is below the 500 lb allowance.")
    area = _number(sim.airframe.wing_area_sqft, "wing area", positive=True)
    aero = sim.aerodynamics.get("aero_new2")
    if aero is None:
        raise FuelModelError("Advanced lift/drag tables are missing.")
    cl = _Table.read(aero.tables.get("clift_table"), aero.breakpoints.get("mach_bp"), aero.breakpoints.get("alpha_bp"))
    cd = _Table.read(aero.tables.get("cdrag_table"), aero.breakpoints.get("mach_bp"), aero.breakpoints.get("alpha_bp"))
    q_area = _Q_LBF_SQFT * area
    low_cl, high_cl = (empty + ALLOWANCE_LB) / q_area, (empty + capacity) / q_area

    # Use the ordinary cruise branch, avoiding post-stall roots.
    alphas = sorted({-5.0, 15.0, *(a for a in cl.y if -5 < a < 15)})
    lifts = [cl.at(RETURN_MACH, a) for a in alphas]
    if any(a >= b for a, b in zip(lifts, lifts[1:])):
        raise FuelModelError("Lift table has no unambiguous cruise branch.")
    if not lifts[0] <= low_cl <= high_cl <= lifts[-1]:
        raise FuelModelError("Fuel weight is outside the supported cruise lift range.")

    def alpha_for_lift(value: float) -> float:
        i, fraction = _bracket(tuple(lifts), value)
        return alphas[i] + fraction * (alphas[i + 1] - alphas[i])

    low_alpha, high_alpha = alpha_for_lift(low_cl), alpha_for_lift(high_cl)
    candidates = {low_alpha, high_alpha}
    candidates.update(a for a in (*cl.y, *cd.y) if low_alpha < a < high_alpha)

    tables = sim.engine.tables
    idle = _Table.read(tables.get("alt_mach_thrust_idle_table"))

    def engine(name: str) -> float:
        return _Table.read(tables.get(name), idle.x, idle.y).at(RETURN_ALTITUDE_FT, RETURN_MACH)

    thrust_scale = _number(sim.engine.parameters.get("thrust_factor"), "thrust factor", positive=True)
    flow_scale = _number(sim.engine.parameters.get("fuel_flow_factor"), "fuel-flow factor", positive=True)
    # Compare whole-aircraft drag with combined thrust, then interpolate the
    # combined flow. All engines share the same operating point in this model.
    thrust_scale *= engine_count
    flow_scale *= engine_count
    t_idle = idle.at(RETURN_ALTITUDE_FT, RETURN_MACH) * thrust_scale
    t_mil = engine("alt_mach_thrust_mil_table") * thrust_scale
    f_idle = engine("alt_mach_fuel_flow_idle_table") * flow_scale
    f_mil = engine("alt_mach_fuel_flow_mil_table") * flow_scale
    if t_mil <= t_idle or f_idle <= 0 or f_mil < f_idle:
        raise FuelModelError("Invalid idle/MIL thrust or fuel-flow range.")

    # Our tested cruise path has unity alpha/beta correction factors. Reject
    # other authored corrections instead of silently ignoring their effect.
    alpha_factor = tables.get("alt_alpha_thrust_factor_table")
    if sim.engine.parameters.get("has_advanced_thrust") is True:
        factor = _Table.read(alpha_factor, idle.x)
        candidates.update(a for a in factor.y if low_alpha < a < high_alpha)
        if any(not math.isclose(factor.at(RETURN_ALTITUDE_FT, a), 1.0) for a in candidates):
            raise FuelModelError("Non-unity thrust corrections are not supported.")
    for name in ("perc_lift_table", "perc_drag_table"):
        if name in aero.tables:
            correction = _Table.read(aero.tables[name], aero.breakpoints.get("beta_perc_bp"), aero.breakpoints.get("alpha_bp"))
            points = candidates | {a for a in correction.y if low_alpha < a < high_alpha}
            if any(not math.isclose(correction.at(0, a), 1.0) for a in points):
                raise FuelModelError("Non-unity sideslip corrections are not supported.")

    flows = []
    for alpha in candidates:
        drag = cd.at(RETURN_MACH, alpha) * q_area
        fraction = (drag - t_idle) / (t_mil - t_idle)
        if not 0 <= fraction <= 1:
            raise FuelModelError("The return profile cannot be maintained between idle and MIL.")
        flows.append(f_idle + fraction * (f_mil - f_idle))
    return math.ceil(max(flows) / RETURN_TAS_KT)


def minimum_fuel_lb(distance_nm: float, rate_lb_nm: float) -> int:
    distance = _number(distance_nm, "return distance")
    rate = _number(rate_lb_nm, "cruise consumption", positive=True)
    if distance < 0:
        raise FuelModelError("Return distance cannot be negative.")
    units = (distance * rate + ALLOWANCE_LB) / ROUNDING_LB
    # Coordinate conversions can put an exact boundary a few ulps above itself.
    # Remove sub-micro-pound noise before rounding up to the next 100 lb.
    return ROUNDING_LB * math.ceil(round(units, 9))
