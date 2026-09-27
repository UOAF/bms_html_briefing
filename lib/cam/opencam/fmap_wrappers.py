"""Typed, read-only access to stored FMAP grid cells."""

from __future__ import annotations

from dataclasses import dataclass

from .fmap_parser import FMAP_WIND_LEVELS_FT, FmapRecord


@dataclass(frozen=True)
class FmapCell:
    record: FmapRecord
    index: int

    def __post_init__(self) -> None:
        if not isinstance(self.record, FmapRecord):
            raise TypeError("record must be a FmapRecord")
        if type(self.index) is not int:
            raise TypeError("cell index must be an integer")
        if not 0 <= self.index < self.record.cell_count:
            raise IndexError(f"FMAP cell index {self.index} is out of range")

    @property
    def row(self) -> int:
        return self.index // self.record.width

    @property
    def column(self) -> int:
        return self.index % self.record.width

    @property
    def weather_type(self) -> int:
        return self.record.weather_types[self.index]

    @property
    def pressure_hpa(self) -> float:
        return self.record.pressure_hpa[self.index]

    @property
    def temperature_c(self) -> float:
        return self.record.temperature_c[self.index]

    @property
    def wind_speeds_knots(self) -> tuple[float, ...]:
        return self.record.wind_speeds_knots[self.index]

    @property
    def wind_directions_deg(self) -> tuple[float, ...]:
        return self.record.wind_directions_deg[self.index]

    @property
    def cumulus_base_ft(self) -> float:
        return self.record.cumulus_base_ft[self.index]

    @property
    def cumulus_density(self) -> int:
        return self.record.cumulus_density[self.index]

    @property
    def cumulus_size(self) -> float:
        return self.record.cumulus_size[self.index]

    @property
    def tower_cumulus_flag(self) -> int:
        return self.record.tower_cumulus_flags[self.index]

    @property
    def shower_cumulus_flag(self) -> int | None:
        values = self.record.shower_cumulus_flags
        return None if values is None else values[self.index]

    @property
    def fog_end_km(self) -> float:
        return self.record.fog_end_km[self.index]

    @property
    def fog_layer_z_ft(self) -> float | None:
        values = self.record.fog_layer_z_ft
        return None if values is None else values[self.index]

    def to_view(self) -> dict[str, object]:
        return {
            "index": self.index,
            "row": self.row,
            "column": self.column,
            "weather_type": self.weather_type,
            "pressure_hpa": self.pressure_hpa,
            "temperature_c": self.temperature_c,
            "wind_speeds_knots": list(self.wind_speeds_knots),
            "wind_directions_deg": list(self.wind_directions_deg),
            "cumulus_base_ft": self.cumulus_base_ft,
            "cumulus_density": self.cumulus_density,
            "cumulus_size": self.cumulus_size,
            "tower_cumulus_flag": self.tower_cumulus_flag,
            "shower_cumulus_flag": self.shower_cumulus_flag,
            "fog_end_km": self.fog_end_km,
            "fog_layer_z_ft": self.fog_layer_z_ft,
        }


@dataclass(frozen=True)
class FmapWeather:
    record: FmapRecord

    @property
    def version(self) -> int:
        return self.record.version

    @property
    def width(self) -> int:
        return self.record.width

    @property
    def height(self) -> int:
        return self.record.height

    @property
    def cell_count(self) -> int:
        return self.record.cell_count

    @property
    def movement_heading_deg(self) -> int:
        return self.record.movement_heading_deg

    @property
    def movement_speed_knots(self) -> float:
        return self.record.movement_speed_knots

    @property
    def stratus_fair_ft(self) -> int:
        return self.record.stratus_fair_ft

    @property
    def stratus_inclement_ft(self) -> int:
        return self.record.stratus_inclement_ft

    @property
    def contrail_altitudes_ft(self) -> tuple[int, ...]:
        return self.record.contrail_altitudes_ft

    @property
    def wind_levels_ft(self) -> tuple[int, ...]:
        return FMAP_WIND_LEVELS_FT

    @property
    def cells(self) -> tuple[FmapCell, ...]:
        return tuple(FmapCell(self.record, index) for index in range(self.cell_count))

    def cell(self, row: int, column: int) -> FmapCell:
        """Select a zero-based stored grid cell, with no wrapping or projection."""
        if type(row) is not int or type(column) is not int:
            raise TypeError("row and column must be integers")
        if not 0 <= row < self.height or not 0 <= column < self.width:
            raise IndexError(f"FMAP cell ({row}, {column}) is out of range")
        return FmapCell(self.record, row * self.width + column)

    def to_view(self) -> dict[str, object]:
        return {
            "version": self.version,
            "width": self.width,
            "height": self.height,
            "cell_count": self.cell_count,
            "movement_heading_deg": self.movement_heading_deg,
            "movement_speed_knots": self.movement_speed_knots,
            "stratus_fair_ft": self.stratus_fair_ft,
            "stratus_inclement_ft": self.stratus_inclement_ft,
            "contrail_altitudes_ft": list(self.contrail_altitudes_ft),
            "wind_levels_ft": list(self.wind_levels_ft),
            "cells": [cell.to_view() for cell in self.cells],
        }


def wrap_fmap(record: FmapRecord) -> FmapWeather:
    if not isinstance(record, FmapRecord):
        raise TypeError("record must be a FmapRecord")
    return FmapWeather(record)
