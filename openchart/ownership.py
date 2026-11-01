"""Which team owned each airfield at the start of a campaign file."""

from __future__ import annotations

from pathlib import Path

from .vendor.opencam.campaign import CamContainer, detect_container_version
from .vendor.opencam.cmp_parser import parse_cmp_record
from .vendor.opencam.objectives import parse_objectives
from .vendor.opencam.support import SupportData

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

    container = CamContainer.from_path(campaign_file, decode_cmp=True)
    version = detect_container_version(container)
    entries = {Path(e.name).suffix.casefold(): e for e in container.entries}
    campaign = parse_cmp_record(entries[".cmp"], container_version=version)
    teams = {
        team_id: team.team_name_raw.split(b"\x00", 1)[0].decode("latin-1").strip()
        for team_id, team in enumerate(campaign.get("team_info"))
    }
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
