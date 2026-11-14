"""Versions of the two inputs used by the interactive briefing."""

from pathlib import Path

from lib.bms_paths import callsign_ini_path


def source_files(bms):
    paths = {
        "briefing": Path(bms.base_dir) / "User" / "Briefings" / "briefing.txt",
        "callsign": callsign_ini_path(bms),
    }
    versions = {}
    for name, path in paths.items():
        try:
            stat = path.stat()
            # Nanoseconds exceed JavaScript's integer precision.
            versions[name] = {"path": str(path), "mtime": str(stat.st_mtime_ns), "size": stat.st_size}
        except OSError:
            versions[name] = None
    return versions
