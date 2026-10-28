"""Which team owned each airfield at the start of a campaign file."""

from __future__ import annotations

from pathlib import Path

from .vendor.opencam.campaign import CamContainer, detect_container_version
from .vendor.opencam.objectives import parse_objectives
from .vendor.opencam.support import SupportData
from .vendor.opencam.teams import read_team_names

START_CAMPAIGN_NAME = "te_new_nt.tac"


def find_start_campaign(data_root: str | Path) -> Path | None:
    """Locate the theater's Campaign/Te_New_Nt.tac regardless of case."""

    campaign_dir = Path(data_root) / "Campaign"
    if not campaign_dir.is_dir():
        return None
    for candidate in campaign_dir.iterdir():
        if candidate.name.casefold() == START_CAMPAIGN_NAME:
            return candidate
    return None


def load_objective_teams(
    campaign_file: str | Path,
    support: SupportData,
) -> dict[int, str]:
    """Map objective campaign ID to the name of its first-owner team."""

    container = CamContainer.from_path(campaign_file)
    version = detect_container_version(container)
    entries = {Path(e.name).suffix.casefold(): e for e in container.entries}
    teams = read_team_names(entries[".tea"].decoded, version)
    objectives = parse_objectives(
        entries[".obj"],
        container_version=version,
        support=support,
    )
    return {
        objective.camp_id: teams[objective.first_owner]
        for objective in objectives
        if objective.first_owner in teams
    }
