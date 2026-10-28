"""Read team names from a CAM container's .tea entry (campaign version 109+)."""

from __future__ import annotations

import struct

MIN_TEA_VERSION = 109
TEAM_NAME_OFFSET = 453  # offset of Team.name from the team start at version >= 109
TEAM_NAME_SIZE = 20
MAX_TEAMS = 8


class TeamDataError(RuntimeError):
    """Raised when the .tea entry cannot be read as a version 109+ team table."""


def read_team_names(tea: bytes, version: int | None) -> dict[int, str]:
    """Return {team number: name} for every team in a .tea payload."""

    if version is None or version < MIN_TEA_VERSION:
        raise TeamDataError(
            f"team table needs campaign version >= {MIN_TEA_VERSION}, got {version}"
        )
    if len(tea) < 2 + 11:
        raise TeamDataError("tea entry is too small")
    count = min(struct.unpack_from("<h", tea, 0)[0], MAX_TEAMS)
    start = 2
    _, creator, entity_type, who = struct.unpack_from("<IIHB", tea, start)
    names = {who: _team_name(tea, start)}
    cursor = start + 1
    # Tasking-manager blocks between teams are variable-length, so find the next
    # team by its creator ID, entity type and rising team number.
    for expected in range(who + 1, count):
        signature = struct.pack("<IHB", creator, entity_type, expected)
        position = tea.find(signature, cursor)
        if position < 4:
            raise TeamDataError(f"team {expected} not found in tea entry")
        names[expected] = _team_name(tea, position - 4)
        cursor = position + 1
    return names


def _team_name(tea: bytes, team_start: int) -> str:
    begin = team_start + TEAM_NAME_OFFSET
    raw = tea[begin : begin + TEAM_NAME_SIZE]
    if len(raw) < TEAM_NAME_SIZE:
        raise TeamDataError("tea entry ends inside a team name")
    return raw.split(b"\x00", 1)[0].decode("latin-1", errors="replace").strip()
