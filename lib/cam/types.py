from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ParsedTwxData:
    current_date: str = ""
    source_path: Path | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedL16Data:
    by_flight: dict[int, dict[str, int]] = field(default_factory=dict)
    source_path: Path | None = None
    warnings: tuple[str, ...] = ()
