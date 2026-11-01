"""Shared parsed-record field primitives."""

from __future__ import annotations

from dataclasses import dataclass

from .binary import Codec


@dataclass
class Field:
    """One parsed binary field value."""

    name: str
    value: object
    codec: Codec


FieldMap = dict[str, Field]
