"""Shared definitions for DTC fields displayed in briefing templates."""

import hashlib
import json
import re
from decimal import Decimal, ROUND_HALF_UP

from lib.parsers.parse_callsign_ini import FCC_DEFAULTS, ICP_DEFAULTS
from lib.theater_paths import magnetic_variation_for_steerpoints


FIELDS = {
    f"{section}:{field}": {
        "section": section,
        "field": field,
        "default": default,
        "scale": 1,
        "displayOffset": 0,
    }
    for section, defaults in {"ICP": ICP_DEFAULTS, **FCC_DEFAULTS}.items()
    for field, default in defaults.items()
}


def _options(key, choices):
    FIELDS[key]["options"] = [
        {"value": str(value), "label": label} for value, label in choices
    ]


_options("ICP:MasterMode", [(0, "NAV"), (1, "AG"), (2, "AA")])
_options("FCC_AIM:AIM-9_Spot/Scan", [(0, "SPOT"), (1, "SCAN")])
_options("FCC_AIM:AIM-9_TD/BP", [(0, "BP"), (1, "TD")])
_options(
    "FCC_AIM:AIM120_TargetSize",
    [(0, "UNKN"), (1, "SMALL"), (2, "MEDIUM"), (3, "LARGE")],
)
_options("FCC_AGM:Maverick_AutoPwr", [(0, "OFF"), (1, "ON")])
_options(
    "FCC_AGM:Maverick_AutoPwrDir",
    [(1, "North of"), (2, "East of"), (3, "South of"), (4, "West of")],
)

for profile in (1, 2):
    prefix = f"FCC_AGB:Profile{profile}_"
    _options(
        prefix + "Submode",
        [(7, "CCIP"), (8, "CCRP"), (9, "DTOS"), (10, "LADD")],
    )
    _options(prefix + "Fuze", [(1, "NOSE"), (2, "TAIL"), (0, "NSTL")])
    _options(prefix + "SGL/PAIR", [(0, "SGL"), (1, "PAIR")])
    for delay in ("C1_AD1", "C1_AD2", "C2_AD"):
        FIELDS[prefix + delay].update(scale=100, decimals=2)
    FIELDS[prefix + "Release_Pulse"]["displayOffset"] = 1
    FIELDS[prefix + "Release_Angle"]["legacyIds"] = [f"dc2_profile_{profile}_rel_angle"]


# Used only to migrate edits saved by older versions of the templates.
FIELDS["ICP:Bingo_Fuel"]["legacyIds"] = ["admin_6", "dc2_bingo"]
FIELDS["ICP:Alow AGL"]["legacyIds"] = ["admin_1", "dc2_alow"]
FIELDS["ICP:Alow MSL"]["legacyIds"] = ["admin_2", "dc2_msl"]
for profile in (1, 2):
    for field, suffix, ids in (
        ("Submode", "mode", ("sms_mode_1", "sms_mode_2")),
        ("Fuze", "fuze", ("sms_1", "sms_3")),
        ("SGL/PAIR", "pair", ("sms_2", "sms_4")),
        ("C1_AD1", "ad", ("sms_7", "sms_9")),
        ("Release_Spacing", "spacing", ("sms_8", "sms_10")),
        ("C2_BA", "hb", ("sms_14", "sms_16")),
        ("Release_Pulse", "rp", ("sms_15", "sms_17")),
    ):
        FIELDS[f"FCC_AGB:Profile{profile}_{field}"]["legacyIds"] = [
            ids[profile - 1], f"dc2_profile_{profile}_{suffix}",
        ]


def normalize_value(key, raw_value):
    """Validate a draft before writing it to callsign.ini."""
    meta = FIELDS[key]
    value = str(raw_value).strip()
    if len(value) > 128 or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value):
        raise ValueError(f"{key}: enter a number")
    number = Decimal(value)
    if abs(number) > 2**53 - 1:
        raise ValueError(f"{key}: number is too large")
    normalized = format(number, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if number == 0:
        normalized = "0"
    if "options" in meta and normalized not in {option["value"] for option in meta["options"]}:
        raise ValueError(f"{key}: choose a supported value")
    return normalized


def validate_section(section, values):
    if not isinstance(values, dict):
        raise ValueError(f"{section}: expected a field mapping")
    normalized = {}
    for field, value in values.items():
        key = f"{section}:{field}"
        if key not in FIELDS:
            raise ValueError(f"Unknown DTC field: {key}")
        normalized[field] = normalize_value(key, value)
    return normalized


def format_value(key, raw_value):
    """Format a raw callsign.ini value without changing its stored units."""
    meta = FIELDS[key]
    value = str(raw_value).strip()
    if "options" in meta:
        return next(
            (option["label"] for option in meta["options"] if Decimal(option["value"]) == Decimal(value)),
            value,
        )
    number = (Decimal(value) + meta["displayOffset"]) / meta["scale"]
    if "decimals" in meta:
        quantum = Decimal(1).scaleb(-meta["decimals"])
        return f"{number.quantize(quantum, rounding=ROUND_HALF_UP):.{meta['decimals']}f}"
    formatted = format(number, "f")
    return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted


def field_payload(callsign_ini, scope, theater="", *, base_dir=None):
    """Supply the same field definitions and raw values to each page."""
    sections = {"ICP": callsign_ini.icp_settings, **callsign_ini.fcc_settings}
    # Pop-up results belong to this callsign and route, not merely to the template.
    coordinates = [
        [(point.number, point.coord_x, point.coord_y) for point in points]
        for points in (callsign_ini.steerpoints, callsign_ini.tgtsteerpoints, callsign_ini.threat_steerpoints)
    ]
    magnetic_variation = magnetic_variation_for_steerpoints(
        base_dir, theater,
        [*callsign_ini.steerpoints, *callsign_ini.tgtsteerpoints, *callsign_ini.threat_steerpoints],
    )
    # Older cached plans contain true headings; never reuse them as magnetic.
    route_hash = hashlib.sha256(json.dumps(
        ["magnetic-v1", theater, coordinates, magnetic_variation], sort_keys=True,
    ).encode()).hexdigest()
    return {
        "scope": str(scope),
        "popup_scope": f"{scope}:{route_hash}",
        "magnetic_variation": magnetic_variation,
        "fields": FIELDS,
        "values": {
            key: sections.get(meta["section"], {}).get(meta["field"], meta["default"])
            for key, meta in FIELDS.items()
        },
    }
