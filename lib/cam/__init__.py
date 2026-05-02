"""Public library API for CAM helpers."""

__all__ = ["extract_cam_brief_data"]


def __getattr__(name: str):
    if name == "extract_cam_brief_data":
        from .extract import extract_cam_brief_data

        return extract_cam_brief_data
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
