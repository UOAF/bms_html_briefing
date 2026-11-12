"""Version ordering, Git release metadata, and the frozen application's version."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple


ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(
    r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)


class VersionTuple(NamedTuple):
    major: int
    minor: int
    patch: int
    stable: bool
    prerelease: tuple[tuple[int, int | str], ...]


def version_tuple(version: str) -> VersionTuple:
    # Keep legacy major.minor tags equivalent to major.minor.0.
    match = VERSION_PATTERN.fullmatch(str(version).strip())
    if match is None:
        raise ValueError(version)
    major, minor, patch, prerelease = match.groups()
    identifiers = []
    for part in prerelease.split(".") if prerelease else ():
        if part.isdigit():
            if len(part) > 1 and part.startswith("0"):
                raise ValueError(version)
            identifiers.append((0, int(part)))
        else:
            identifiers.append((1, part))
    # Stable releases sort after their prereleases; build metadata has no precedence.
    return VersionTuple(int(major), int(minor), int(patch or 0), prerelease is None, tuple(identifiers))


class BuildVersionError(ValueError):
    pass


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildVersionError("Git metadata unavailable") from exc
    return result.stdout.strip()


def _version_tags(root: Path, *filters: str) -> list[str]:
    tags = []
    for tag in _git(root, "tag", *filters).splitlines():
        try:
            version_tuple(tag)
        except ValueError:
            continue
        tags.append(tag)
    return tags


def release_version(root: Path = ROOT) -> str:
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise BuildVersionError("Uncommitted changes")

    versions = {tag.removeprefix("v") for tag in _version_tags(root, "--points-at", "HEAD")}
    if not versions:
        raise BuildVersionError("Version tag required")
    if len(versions) != 1:
        raise BuildVersionError("Ambiguous version tags: " + ", ".join(sorted(versions)))
    return versions.pop()


def nightly_version(root: Path = ROOT) -> str:
    commit = _git(root, "rev-parse", "--short=12", "HEAD")
    dirty = _git(root, "status", "--porcelain", "--untracked-files=no")
    tags = _version_tags(root, "--merged", "HEAD")
    if tags:
        matches = [arg for tag in tags for arg in ("--match", tag)]
        base = _git(root, "describe", "--tags", "--abbrev=0", *matches, "HEAD").removeprefix("v")
    else:
        base = "0.0.0"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Metadata preserves the base version's ordering against stable releases.
    separator = "." if "+" in base else "+"
    return f"{base}{separator}nightly.{timestamp}.g{commit}" + (".dirty" if dirty else "")


def get_app_version(root: Path = ROOT) -> str:
    if getattr(sys, "frozen", False):
        from lib._version import APP_VERSION

        return APP_VERSION

    # Source runs always inspect this checkout, ignoring any previous build stamp.
    try:
        return release_version(root)
    except BuildVersionError:
        try:
            commit = _git(root, "rev-parse", "--short", "HEAD")
            dirty = _git(root, "status", "--porcelain", "--untracked-files=no")
        except BuildVersionError:
            return "dev"
        return f"dev-{commit}" + ("-dirty" if dirty else "")


def source_state(root: Path = ROOT) -> dict:
    return {
        "commit": _git(root, "rev-parse", "HEAD"),
        "dirty": bool(_git(root, "status", "--porcelain", "--untracked-files=no")),
        "source_digest": hashlib.sha256(
            _git(root, "diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--").encode()
        ).hexdigest(),
    }


def finalize_build_info(path: Path, root: Path = ROOT) -> None:
    info = json.loads(path.read_text(encoding="utf-8"))
    if any(info[key] != value for key, value in source_state(root).items()):
        raise BuildVersionError("Build source changed")
    version_digest = hashlib.sha256((root / "lib/_version.py").read_bytes()).hexdigest()
    if version_digest != info["version_digest"]:
        raise BuildVersionError("Build version changed")


def write_build_version(
    root: Path = ROOT, *, nightly: bool = False,
    metadata: Path | None = None, platform: str | None = None,
) -> str:
    state = source_state(root) if metadata is not None else None
    version = nightly_version(root) if nightly else release_version(root)
    version_source = f"# Generated by lib/app_version.py; ignored by Git.\nAPP_VERSION = {version!r}\n"
    (root / "lib" / "_version.py").write_text(version_source, encoding="utf-8", newline="\n")
    if metadata is not None:
        if platform not in ("linux", "windows"):
            raise BuildVersionError("Build platform required")
        info = {
            "schema_version": 1,
            "application": "bms_html_briefing",
            "platform": platform,
            "version": version,
            "nightly": nightly,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "version_digest": hashlib.sha256(version_source.encode()).hexdigest(),
            **state,
        }
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        finalize_build_info(metadata, root)
    return version


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--nightly", action="store_true")
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--platform", choices=("linux", "windows"))
    parser.add_argument("--finalize-metadata", type=Path)
    args = parser.parse_args()
    if bool(args.metadata) != bool(args.platform):
        parser.error("--metadata / --platform")
    if args.finalize_metadata and (args.metadata or args.nightly):
        parser.error("--finalize-metadata")
    try:
        if args.finalize_metadata:
            finalize_build_info(args.finalize_metadata)
        else:
            print(write_build_version(nightly=args.nightly, metadata=args.metadata, platform=args.platform))
    except (BuildVersionError, OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
