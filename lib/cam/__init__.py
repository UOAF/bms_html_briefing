"""Public library API for CAM helpers.

The summary extractor is imported lazily so low-level parser modules can import
``lib.cam.types`` without loading the whole summary stack and creating cycles.
"""

__all__ = ["extract_cam_brief_data"]


def __getattr__(name: str):
    if name == "extract_cam_brief_data":
        from .summary import extract_cam_brief_data

        return extract_cam_brief_data
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
