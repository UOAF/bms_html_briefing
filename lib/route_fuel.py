"""Approximate route fuel with constant takeoff stores and changing fuel weight.

ISA, no wind, coordinated flight and linear altitude transitions. CAS is the
destination row's planned leg speed. The loadout screen's clean baseline of 1
is excluded from aerodynamic DI. CFTs are represented by their contribution to
takeoff DI; separate CFT aero deltas are not added to this approximation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from lib.cam.opencam.aircraft_data import AircraftSimulationData, AircraftTable
from lib.fuel import ALLOWANCE_LB, FEET_PER_NM, ROUNDING_LB, FuelModelError, _Table, _bracket, _number


def air_state(altitude_ft: float, cas_kt: float) -> tuple[float, float, float]:
    """Return Mach, TAS in knots and dynamic pressure in lbf/ft² (subsonic)."""
    altitude = _number(altitude_ft, "MSL altitude") * .3048
    cas = _number(cas_kt, "CAS", positive=True) * 1852 / 3600
    if not -500 <= altitude <= 20000:
        raise FuelModelError("MSL altitude range")
    temperature = 288.15 - .0065 * min(altitude, 11000)
    pressure = 101325 * (temperature / 288.15) ** (9.80665 / (287.05287 * .0065))
    if altitude > 11000:
        pressure *= math.exp(-9.80665 * (altitude - 11000) / (287.05287 * temperature))
    sea_mach = cas / math.sqrt(1.4 * 287.05287 * 288.15)
    impact_pressure = 101325 * ((1 + .2 * sea_mach ** 2) ** 3.5 - 1)
    mach = math.sqrt(5 * ((impact_pressure / pressure + 1) ** (2 / 7) - 1))
    if sea_mach >= 1 or mach >= 1:
        raise FuelModelError("Subsonic CAS range")
    tas = mach * math.sqrt(1.4 * 287.05287 * temperature) * 3600 / 1852
    q = .7 * pressure * mach ** 2 * .09290304 / 4.4482216152605
    return mach, tas, q


@dataclass(frozen=True)
class RoutePerformance:
    wing_area: float
    thrust_scale: float
    flow_scale: float
    tables: dict[str, _Table]
    stores_drag: tuple[float, ...]

    @classmethod
    def from_simulation(cls, sim: AircraftSimulationData) -> RoutePerformance:
        if sim.fm_type != "FM_AFM" or sim.engine.has_fuel_flow is not True:
            raise FuelModelError("AFM fuel-flow tables")
        engines = _number(sim.engine.number_of_engines, "engine count", positive=True)
        aero = sim.aerodynamics.get("aero_new2")
        if aero is None:
            raise FuelModelError("Lift/drag tables")
        tables = {
            name: _Table.read(aero.tables.get(field), aero.breakpoints.get("mach_bp"),
                              aero.breakpoints.get("alpha_bp"))
            for name, field in (("cl", "clift_table"), ("cd", "cdrag_table"))
        }
        for name in ("perc_lift_table", "perc_drag_table"):
            if name in aero.tables:
                tables[name] = _Table.read(aero.tables[name], aero.breakpoints.get("beta_perc_bp"),
                                           aero.breakpoints.get("alpha_bp"))
        idle = _Table.read(sim.engine.tables.get("alt_mach_thrust_idle_table"))
        for regime in ("idle", "mil", "ab"):
            for quantity in ("thrust", "fuel_flow"):
                source = sim.engine.tables.get(f"alt_mach_{quantity}_{regime}_table")
                if source is not None or regime != "ab":
                    tables[f"{quantity}_{regime}"] = _Table.read(source, idle.x, idle.y)
        if sim.engine.parameters.get("has_advanced_thrust") is True:
            tables["alpha_thrust"] = _Table.read(
                sim.engine.tables.get("alt_alpha_thrust_factor_table"), idle.x)
        drag = sim.stores_drag
        if drag is None:
            raise FuelModelError("Stores drag conversion")
        values = tuple(_number(v, "stores drag conversion") for v in drag.values)
        if drag.limiter_type == "LIMITER_VALUE" and len(values) == 1 and values[0] >= 0:
            values = (0., values[0], 1., values[0])
        elif (drag.limiter_type != "LIMITER_LINE" or len(values) != 4
              or values[0] >= values[2] or min(values[1], values[3]) < 0):
            raise FuelModelError("Stores drag conversion")
        return cls(
            _number(sim.airframe.wing_area_sqft, "wing area", positive=True),
            engines * _number(sim.engine.parameters.get("thrust_factor"), "thrust factor", positive=True),
            engines * _number(sim.engine.parameters.get("fuel_flow_factor"), "fuel-flow factor", positive=True),
            tables, values,
        )

    def to_view(self) -> dict:
        return {"version": 1, **asdict(self)}

    @classmethod
    def from_view(cls, view: dict) -> RoutePerformance:
        if view.get("version") != 1:
            raise FuelModelError("Reload CAM")
        tables = {}
        for name, table in view["tables"].items():
            tables[name] = _Table.read(AircraftTable(
                source_field=name, title=None, x_title=None, y_title=None, multiplier=None,
                x_breakpoints=table["x"], y_breakpoints=table["y"], rows=table["rows"],
            ))
        values = tuple(_number(v, "stores drag conversion") for v in view["stores_drag"])
        if len(values) != 4 or values[0] >= values[2] or min(values[1], values[3]) < 0:
            raise FuelModelError("Stores drag conversion")
        return cls(*(_number(view[key], key, positive=True)
                     for key in ("wing_area", "thrust_scale", "flow_scale")), tables, values)

    def stores_cd(self, mach: float, drag_index: float) -> float:
        index = _number(drag_index, "T/O drag factor") - 1
        if index < 0:
            raise FuelModelError("T/O drag factor")
        x0, y0, x1, y1 = self.stores_drag
        fraction = max(0., min(1., (mach - x0) / (x1 - x0)))
        return index * (y0 + fraction * (y1 - y0))

    def flow(self, altitude_ft: float, cas_kt: float, weight_lb: float,
             drag_index: float, gradient: float = 0) -> tuple[float, float]:
        """Whole-aircraft lb/hour and horizontal speed in knots.

        Thrust balances drag plus the weight component along a straight climb.
        Below-idle descent uses idle fuel; beyond full AB is unsupported.
        """
        mach, tas, q = air_state(altitude_ft, cas_kt)
        weight = _number(weight_lb, "gross weight", positive=True)
        gamma = math.atan(gradient)
        q_area = q * self.wing_area
        cl, cd = self.tables["cl"], self.tables["cd"]
        low, high = max(-5., cl.y[0], cd.y[0]), min(15., cl.y[-1], cd.y[-1])
        alphas = sorted({low, high, *(a for a in cl.y if low < a < high)})

        def correction(name, alpha):
            table = self.tables.get(name)
            return table.at(0, alpha) if table else 1.

        lifts = tuple(cl.at(mach, a) * correction("perc_lift_table", a) for a in alphas)
        if any(a >= b for a, b in zip(lifts, lifts[1:])):
            raise FuelModelError("Cruise lift range")
        i, f = _bracket(lifts, weight * math.cos(gamma) / q_area)
        alpha = alphas[i] + f * (alphas[i + 1] - alphas[i])
        drag = (cd.at(mach, alpha) * correction("perc_drag_table", alpha)
                + self.stores_cd(mach, drag_index)) * q_area
        required_thrust = drag + weight * math.sin(gamma)
        factor = self.tables.get("alpha_thrust")
        thrust_scale = self.thrust_scale * (factor.at(altitude_ft, alpha) if factor else 1.)

        def engine(quantity, regime, scale):
            return self.tables[f"{quantity}_{regime}"].at(altitude_ft, mach) * scale

        t0, t1 = (engine("thrust", r, thrust_scale) for r in ("idle", "mil"))
        f0, f1 = (engine("fuel_flow", r, self.flow_scale) for r in ("idle", "mil"))
        if t1 <= t0 or f0 <= 0 or f1 < f0:
            raise FuelModelError("Idle/MIL performance")
        if required_thrust > t1:
            if not {"thrust_ab", "fuel_flow_ab"} <= self.tables.keys():
                raise FuelModelError("Afterburner performance")
            t0, f0 = t1, f1
            t1, f1 = engine("thrust", "ab", thrust_scale), engine("fuel_flow", "ab", self.flow_scale)
            if t1 <= t0 or f1 < f0:
                raise FuelModelError("Afterburner performance")
            if required_thrust > t1:
                raise FuelModelError("Required thrust exceeds full AB")
        fraction = max(0., (required_thrust - t0) / (t1 - t0))
        return f0 + fraction * (f1 - f0), tas * math.cos(gamma)


@dataclass(frozen=True)
class RoutePoint:
    number: int
    north_ft: float
    east_ft: float
    altitude_ft: float
    cas_kt: float
    hold_hours: float = 0.


class RouteFuelError(FuelModelError):
    """A failed leg or hold, with only fully integrated downstream arrivals."""

    def __init__(self, reason: str, values: dict[int, int], from_number: int, to_number: int):
        super().__init__(reason)
        self.values = dict(values)
        self.from_number = from_number
        self.to_number = to_number


def remaining_route_fuel(model: RoutePerformance, points: list[RoutePoint],
                         dry_weight_lb: float, drag_index: float) -> dict[int, int]:
    """Integrate required fuel backward from landing, rounding only displayed cells.

    Midpoint steps are at most 2 nm / 30 seconds. Fuel is part of aircraft weight,
    so a long route is not evaluated at an arbitrary fixed takeoff fuel load.
    Values are at arrival, before a hold at that point. No refuelling credit.
    A local performance failure preserves completed arrivals in RouteFuelError;
    no value depending on the failed leg or hold is returned.
    """
    dry = _number(dry_weight_lb, "dry weight", positive=True)
    drag_index = _number(drag_index, "T/O drag factor")
    if drag_index < 1:
        raise FuelModelError("T/O drag factor")
    if not points:
        raise FuelModelError("Planned route")
    required = float(ALLOWANCE_LB)
    result = {}

    def rounded():
        return ROUNDING_LB * math.ceil(round(required / ROUNDING_LB, 9))

    for index in range(len(points) - 1, -1, -1):
        point = points[index]
        from_number = point.number
        try:
            hold = _number(point.hold_hours, "hold duration")
            if hold < 0 or hold > 24:
                raise FuelModelError("Hold duration")
            if hold:
                steps = max(1, math.ceil(hold * 120))
                dt = hold / steps
                for _ in range(steps):
                    first, _ = model.flow(point.altitude_ft, point.cas_kt, dry + required, drag_index)
                    middle, _ = model.flow(point.altitude_ft, point.cas_kt,
                                           dry + required + first * dt / 2, drag_index)
                    required += middle * dt
            result[point.number] = rounded()
            if index == 0:
                break
            previous = points[index - 1]
            from_number = previous.number
            distance = math.hypot(point.north_ft - previous.north_ft,
                                  point.east_ft - previous.east_ft) / FEET_PER_NM
            if distance == 0:
                if point.altitude_ft != previous.altitude_ft:
                    raise FuelModelError("Zero-length altitude transition")
                continue
            gradient = (point.altitude_ft - previous.altitude_ft) / (distance * FEET_PER_NM)
            steps = max(1, math.ceil(distance / 2))
            ds = distance / steps
            for step in range(steps):
                fraction = 1 - (step + .5) / steps
                altitude = previous.altitude_ft + fraction * (point.altitude_ft - previous.altitude_ft)
                first, speed = model.flow(altitude, point.cas_kt, dry + required, drag_index, gradient)
                dt = ds / speed
                middle, _ = model.flow(altitude, point.cas_kt, dry + required + first * dt / 2,
                                       drag_index, gradient)
                required += middle * dt
        except FuelModelError as exc:
            raise RouteFuelError(str(exc), result, from_number, point.number) from exc
    return result
