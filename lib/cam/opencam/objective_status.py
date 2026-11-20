"""Deterministically confirmed objective-feature status semantics."""

from __future__ import annotations


FEATURE_STATUS_EMPTY = 0
FEATURE_STATUS_REPAIRED = 1
FEATURE_STATUS_DAMAGED = 2
FEATURE_STATUS_DESTROYED = 3
FEATURE_STATUS_NO_DAMAGE = 7

FEATURE_STATUS_NAMES = {
    FEATURE_STATUS_EMPTY: "",
    FEATURE_STATUS_REPAIRED: "Repaired",
    FEATURE_STATUS_DAMAGED: "Damaged",
    FEATURE_STATUS_DESTROYED: "Destroyed",
    FEATURE_STATUS_NO_DAMAGE: "NO_DAMAGE",
}


def validate_feature_status(value: object, *, error_type: type[Exception]) -> int:
    """Return one confirmed status code or raise ``error_type``."""

    if type(value) is not int:
        raise error_type(
            f"feature status must be an integer, got {type(value).__name__}"
        )
    if value not in FEATURE_STATUS_NAMES:
        allowed = ", ".join(str(code) for code in FEATURE_STATUS_NAMES)
        raise error_type(
            f"feature status must be one of {allowed}, got {value}"
        )
    return value
