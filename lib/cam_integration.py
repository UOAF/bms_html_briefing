from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from lib.parse_l16 import format_l16_code, load_l16_for_save
from lib.parse_twx import load_twx_date_for_cam_path, load_twx_date_for_save

logger = logging.getLogger("html_brief_log")


class CamIntegrationError(RuntimeError):
    """Raised when CAM integration cannot parse expected data."""


def _to_vuid_tuple(value: Any) -> Optional[tuple[int, int]]:
    if not isinstance(value, dict):
        return None
    num = value.get("num")
    creator = value.get("creator")
    if isinstance(num, int) and isinstance(creator, int):
        return (num, creator)
    return None


def _resolve_cam_modules() -> tuple[Any, Any]:
    try:
        from lib.cam.cam_content import parse_cam_file
        from lib.cam.summary import parse_cam_summary
    except Exception as exc:
        logger.exception("Failed to import CAM parser modules")
        raise CamIntegrationError(f"Failed to import CAM parser modules: {exc}") from exc

    logger.debug("Resolved CAM modules via static package imports")
    return parse_cam_file, parse_cam_summary


def _infer_support_base_dir(
    bms_base_dir: str | Path | None,
    theater_target_folder: str | Path | None,
    theater_name: str | None = None,
) -> Path | None:
    def normalize_token(text: str) -> str:
        return "".join(ch for ch in text.lower() if ch.isalnum())

    def has_ct(objects_dir: Path) -> bool:
        if not objects_dir.is_dir():
            return False
        try:
            for child in objects_dir.iterdir():
                if child.is_file() and child.name.lower() == "falcon4_ct.xml":
                    return True
        except Exception:
            return False
        return False

    def infer_objects_from_target(target_path: Path) -> Path | None:
        resolved = target_path.resolve()
        if resolved.name.lower() == "koreaobj":
            return resolved.parent
        parts_l = [part.lower() for part in resolved.parts]
        if "koreaobj" in parts_l:
            idx = parts_l.index("koreaobj")
            if idx > 0:
                return Path(*resolved.parts[:idx])
        # If the target already points to the objects folder.
        if resolved.name.lower() == "objects":
            return resolved
        return None

    def infer_addon_token_from_target(target_path: Path) -> str | None:
        resolved = target_path.resolve()
        for part in resolved.parts:
            part_l = part.lower()
            if part_l.startswith("add-on"):
                token = normalize_token(part_l.replace("add-on", "", 1))
                if token:
                    return token
        return None

    if theater_target_folder:
        target_path = Path(theater_target_folder).expanduser()
        objects_from_target = infer_objects_from_target(target_path)
        if objects_from_target is not None and has_ct(objects_from_target):
            logger.debug(
                "Support base dir resolved from theater target folder: %s",
                objects_from_target,
            )
            return objects_from_target

    if bms_base_dir:
        base = Path(bms_base_dir).expanduser()
        data_dir = base / "Data"

        add_on_objects: list[tuple[Path, str, str]] = []
        if data_dir.is_dir():
            try:
                for add_on_dir in data_dir.iterdir():
                    if not add_on_dir.is_dir():
                        continue
                    add_on_name = add_on_dir.name
                    if not add_on_name.lower().startswith("add-on"):
                        continue
                    objects_dir = None
                    for candidate in (
                        add_on_dir / "TerrData" / "Objects",
                        add_on_dir / "Terrdata" / "Objects",
                        add_on_dir / "Terrdata" / "objects",
                    ):
                        if has_ct(candidate):
                            objects_dir = candidate
                            break
                    if objects_dir is None:
                        continue
                    add_on_objects.append(
                        (
                            objects_dir,
                            add_on_name.lower(),
                            normalize_token(add_on_name.replace("add-on", "", 1)),
                        )
                    )
            except Exception:
                pass

        # First priority: infer add-on from theater target folder, even if the folder itself
        # points at a non-objects path (e.g. .../TerrData/Hellas/KoreaObj).
        if theater_target_folder and add_on_objects:
            target_path = Path(theater_target_folder).expanduser()
            target_addon_token = infer_addon_token_from_target(target_path)
            if target_addon_token:
                for objects_dir, add_on_name, add_on_token in add_on_objects:
                    if (
                        target_addon_token == add_on_token
                        or target_addon_token in add_on_token
                        or add_on_token in target_addon_token
                        or add_on_name in str(target_path).lower()
                    ):
                        logger.debug(
                            "Support base dir resolved from add-on target match: %s",
                            objects_dir,
                        )
                        return objects_dir

        # Second priority: infer add-on from active theater name.
        if add_on_objects and theater_name:
            theater_l = theater_name.lower()
            theater_token = normalize_token(theater_name)
            for objects_dir, add_on_name, add_on_token in add_on_objects:
                if (
                    theater_l in str(objects_dir).lower()
                    or theater_l in add_on_name
                    or (theater_token and (theater_token in add_on_token or add_on_token in theater_token))
                ):
                    logger.debug(
                        "Support base dir resolved from theater name match: %s",
                        objects_dir,
                    )
                    return objects_dir

        # Fallback to default KTO objects.
        default_objects_candidates = [
            base / "Data" / "TerrData" / "Objects",
            base / "Data" / "Terrdata" / "Objects",
        ]
        for objects_dir in default_objects_candidates:
            if has_ct(objects_dir):
                logger.debug("Support base dir resolved to default KTO objects: %s", objects_dir)
                return objects_dir

        if add_on_objects:
            logger.debug(
                "Support base dir falling back to first add-on objects: %s",
                add_on_objects[0][0],
            )
            return add_on_objects[0][0]

    if theater_target_folder:
        target_path = Path(theater_target_folder).expanduser()
        objects_from_target = infer_objects_from_target(target_path)
        if objects_from_target is not None and objects_from_target.is_dir():
            logger.debug(
                "Support base dir fallback to inferred objects dir without CT validation: %s",
                objects_from_target,
            )
            return objects_from_target

    if bms_base_dir:
        fallback = Path(bms_base_dir).expanduser().resolve()
        logger.debug("Support base dir fallback to BMS base dir: %s", fallback)
        return fallback
    logger.debug("Support base dir could not be inferred.")
    return None


def _record_index_by_id(uni_parsed: dict[str, Any]) -> dict[tuple[int, int], dict[str, Any]]:
    out: dict[tuple[int, int], dict[str, Any]] = {}
    records = uni_parsed.get("records")
    if not isinstance(records, list):
        return out
    for record in records:
        if not isinstance(record, dict):
            continue
        rec_id = _to_vuid_tuple(record.get("id"))
        if rec_id is None:
            continue
        out[rec_id] = record
    return out


def _collect_player_package_ids(
    uni_parsed: dict[str, Any],
    player_squadron_id: tuple[int, int] | None,
) -> tuple[set[tuple[int, int]], str]:
    if player_squadron_id is None:
        return set(), "all_packages_fallback"

    packages = uni_parsed.get("packages")
    if not isinstance(packages, list):
        return set(), "all_packages_fallback"

    record_by_id = _record_index_by_id(uni_parsed)
    player_kind: str | None = None
    player_record = record_by_id.get(player_squadron_id)
    if isinstance(player_record, dict) and isinstance(player_record.get("kind"), str):
        player_kind = player_record.get("kind")

    # Highest confidence for many saves: CMP player id points to a player flight.
    if player_kind == "flight":
        flight_linked: set[tuple[int, int]] = set()
        for package in packages:
            if not isinstance(package, dict):
                continue
            package_id = _to_vuid_tuple(package.get("id"))
            if package_id is None:
                continue
            planned = package.get("planned_flight_slots")
            if isinstance(planned, list):
                for slot in planned:
                    if isinstance(slot, dict) and _to_vuid_tuple(slot.get("id")) == player_squadron_id:
                        flight_linked.add(package_id)
                        break
            refs = package.get("flight_refs")
            if isinstance(refs, list):
                for ref in refs:
                    if isinstance(ref, dict) and _to_vuid_tuple(ref.get("id")) == player_squadron_id:
                        flight_linked.add(package_id)
                        break
            urefs = package.get("unit_refs")
            if isinstance(urefs, list):
                for ref in urefs:
                    if isinstance(ref, dict) and _to_vuid_tuple(ref.get("id")) == player_squadron_id:
                        flight_linked.add(package_id)
                        break
        if flight_linked:
            return flight_linked, "player_flight_ref"

    # Highest confidence: package references explicitly include player's squadron VU_ID.
    explicit: set[tuple[int, int]] = set()
    for package in packages:
        if not isinstance(package, dict):
            continue
        package_id = _to_vuid_tuple(package.get("id"))
        if package_id is None:
            continue
        refs = package.get("unit_refs")
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            if ref.get("kind") != "squadron":
                continue
            if _to_vuid_tuple(ref.get("id")) == player_squadron_id:
                explicit.add(package_id)
                break
    if explicit:
        return explicit, "player_squadron_ref"

    # Fallback: match package squadron callsign index against player squadron callsign index.
    player_callsign_idx: int | None = None
    if isinstance(player_record, dict):
        profile = player_record.get("callsign_profile")
        if isinstance(profile, dict) and isinstance(profile.get("callsign_idx"), int):
            player_callsign_idx = profile.get("callsign_idx")

    if player_callsign_idx is None:
        return set(), "all_packages_fallback"

    by_callsign: set[tuple[int, int]] = set()
    for package in packages:
        if not isinstance(package, dict):
            continue
        package_id = _to_vuid_tuple(package.get("id"))
        if package_id is None:
            continue
        refs = package.get("unit_refs")
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict) or ref.get("kind") != "squadron":
                continue
            ref_id = _to_vuid_tuple(ref.get("id"))
            if ref_id is None:
                continue
            ref_record = record_by_id.get(ref_id)
            if not isinstance(ref_record, dict):
                continue
            profile = ref_record.get("callsign_profile")
            if not isinstance(profile, dict):
                continue
            ref_callsign_idx = profile.get("callsign_idx")
            if isinstance(ref_callsign_idx, int) and ref_callsign_idx == player_callsign_idx:
                by_callsign.add(package_id)
                break

    if by_callsign:
        return by_callsign, "callsign_idx_fallback"
    return set(), "all_packages_fallback"


def extract_cam_brief_data(
    cam_file_path: str | Path,
    *,
    bms_base_dir: str | Path | None = None,
    theater_target_folder: str | Path | None = None,
    theater_name: str | None = None,
    save_stem: str | None = None,
) -> dict[str, Any]:
    logger.debug(
        "Extract CAM brief data start: cam=%s base=%s theater_target=%s theater=%s save_stem=%s",
        cam_file_path,
        bms_base_dir,
        theater_target_folder,
        theater_name,
        save_stem,
    )
    parse_cam_file, parse_cam_summary = _resolve_cam_modules()

    source_path = Path(cam_file_path).resolve()
    support_base_dir = _infer_support_base_dir(
        bms_base_dir,
        theater_target_folder,
        theater_name=theater_name,
    )

    parsed_cam = parse_cam_file(
        source_path,
        bms_base_dir=support_base_dir,
        parse_entries=True,
        best_effort=True,
    )
    cmp_parsed = parsed_cam.get_parsed_by_ext(".cmp") or {}
    uni_parsed = parsed_cam.get_parsed_by_ext(".uni") or {}

    player_squadron = _to_vuid_tuple(cmp_parsed.get("player_squadron_id"))
    selected_package_ids, match_method = _collect_player_package_ids(uni_parsed, player_squadron)
    logger.debug(
        "CAM parsed: cmp=%s uni=%s player_squadron=%s match_method=%s selected_package_ids=%d",
        isinstance(cmp_parsed, dict),
        isinstance(uni_parsed, dict),
        player_squadron,
        match_method,
        len(selected_package_ids),
    )

    warnings: list[str] = []
    packages: list[dict[str, Any]] = []
    summary_bullseye: dict[str, Any] = {}
    l16_source_path: str | None = None
    current_time_ms = cmp_parsed.get("current_time") if isinstance(cmp_parsed.get("current_time"), int) else None
    current_time_z = cmp_parsed.get("current_time_z") if isinstance(cmp_parsed.get("current_time_z"), str) else None
    current_date, _ = load_twx_date_for_cam_path(source_path)
    if current_date is None:
        current_date, _ = load_twx_date_for_save(
            bms_base_dir=bms_base_dir,
            theater_target_folder=theater_target_folder,
            save_stem=save_stem or source_path.stem,
        )

    try:
        summary = parse_cam_summary(
            source_path,
            cmp_parsed=cmp_parsed,
            uni_parsed=uni_parsed,
            bms_base_dir=support_base_dir,
            container_version=parsed_cam.container_version,
            current_date=current_date,
        )
        if current_time_ms is None and isinstance(summary.get("current_time_ms"), int):
            current_time_ms = summary.get("current_time_ms")
        if not current_time_z and isinstance(summary.get("current_time_z"), str):
            current_time_z = summary.get("current_time_z")
        if current_date is None and isinstance(summary.get("current_date"), str):
            current_date = summary.get("current_date")
        if isinstance(summary.get("bullseye"), dict):
            summary_bullseye = summary.get("bullseye")
        raw_packages = summary.get("packages")
        if isinstance(raw_packages, list):
            if selected_package_ids:
                packages = [
                    package
                    for package in raw_packages
                    if isinstance(package, dict)
                    and _to_vuid_tuple(package.get("package_id")) in selected_package_ids
                ]
            else:
                packages = [package for package in raw_packages if isinstance(package, dict)]
        raw_warnings = summary.get("warnings")
        if isinstance(raw_warnings, list):
            warnings.extend(str(item) for item in raw_warnings)
    except Exception as exc:
        logger.exception("CAM summary shaping failed for %s", source_path)
        warnings.append(f"Summary shaping fallback: {exc}")

    # Fallback when summary-level package shaping is unavailable but UNI packages exist.
    if not packages:
        raw_uni_packages = uni_parsed.get("packages")
        if isinstance(raw_uni_packages, list):
            fallback_packages: list[dict[str, Any]] = []
            for package in raw_uni_packages:
                if not isinstance(package, dict):
                    continue
                package_id = _to_vuid_tuple(package.get("id"))
                if selected_package_ids and package_id not in selected_package_ids:
                    continue
                fallback_packages.append(
                    {
                        "package_id": package.get("id"),
                        "package_number": package.get("package_number"),
                        "tasking": package.get("package_mission"),
                        "timing": package.get("timing"),
                        "steerpoints": package.get("waypoints") if isinstance(package.get("waypoints"), list) else [],
                        "flights": [],
                        "notes": ["fallback_from_uni_packages"],
                    }
                )
            if fallback_packages:
                warnings.append("Using UNI package fallback data shape.")
                packages = fallback_packages
                logger.debug(
                    "Using UNI package fallback shape: packages=%d",
                    len(fallback_packages),
                )

    # Optional Link16 mapping (by flight number) for package/support table enrichment.
    l16_by_flight, l16_path = load_l16_for_save(
        bms_base_dir=bms_base_dir,
        theater_target_folder=theater_target_folder,
        save_stem=save_stem or source_path.stem,
    )
    if l16_path is not None:
        l16_source_path = str(l16_path)
    for package in packages:
        if not isinstance(package, dict):
            continue
        flights = package.get("flights")
        if not isinstance(flights, list):
            continue
        for flight in flights:
            if not isinstance(flight, dict):
                continue
            number = flight.get("flight_number")
            if isinstance(number, int):
                flight["l16"] = format_l16_code(l16_by_flight.get(number))
    logger.debug(
        "Link16 enrichment complete: l16_source=%s mapped_flights=%d",
        l16_source_path,
        len(l16_by_flight),
    )

    def bullseye_grid_size_for_theater(theater: str | None) -> tuple[int, int]:
        # Deterministic baseline grid for BMS campaign bullseye coordinates.
        # Keep explicit theater hook for future per-theater overrides if needed.
        _ = theater
        return (1024, 1024)

    def map_coord_from_cmp(value: int, axis: str, grid_size: int) -> float:
        # Most saves: bullseye is in campaign grid units (0..grid_size).
        # Some saves: bullseye may already be Falcon world scalar-ish values.
        if abs(value) <= grid_size * 2:
            map_scalar = (float(value) / float(grid_size)) * 4096.0
        else:
            map_scalar = (float(value) / 3359580.0) * 4096.0
        if axis == "lat":
            return map_scalar - 4096.0
        return map_scalar

    bullseye_name_id = cmp_parsed.get("bullseye_name_id")
    bullseye_x = cmp_parsed.get("bullseye_x") if isinstance(cmp_parsed.get("bullseye_x"), int) else None
    bullseye_y = cmp_parsed.get("bullseye_y") if isinstance(cmp_parsed.get("bullseye_y"), int) else None
    grid_x, grid_y = bullseye_grid_size_for_theater(theater_name)

    map_lat: float | None = None
    map_lng: float | None = None
    if isinstance(bullseye_x, int) and isinstance(bullseye_y, int):
        # CAM bullseye coordinates use theater grid orientation:
        # x -> horizontal map axis (lng), y -> vertical map axis (lat).
        map_lng = map_coord_from_cmp(bullseye_x, "lng", grid_x)
        map_lat = map_coord_from_cmp(bullseye_y, "lat", grid_y)
        logger.debug(
            "Bullseye transformed: cmp=(%d,%d) grid=(%d,%d) map=(%.3f,%.3f)",
            bullseye_x,
            bullseye_y,
            grid_x,
            grid_y,
            map_lat,
            map_lng,
        )

    bullseye = {
        "x": bullseye_x,
        "y": bullseye_y,
        "name_id": bullseye_name_id if isinstance(bullseye_name_id, int) else None,
        "name": summary_bullseye.get("name") if isinstance(summary_bullseye.get("name"), str) else None,
        "map_lat": map_lat,
        "map_lng": map_lng,
        "map_grid_size_x": grid_x,
        "map_grid_size_y": grid_y,
    }

    if match_method == "all_packages_fallback":
        warnings.append("Could not isolate player-linked packages; returning all parsed packages.")

    if player_squadron is None:
        warnings.append("player_squadron_id not found in .cmp; package list may include all teams.")
    elif not packages:
        warnings.append("No player-linked packages matched in parsed UNI package references.")
    logger.debug(
        "Extract CAM brief data done: package_count=%d warnings=%d",
        len(packages),
        len(warnings),
    )

    return {
        "source_path": str(source_path),
        "support_base_dir": str(support_base_dir) if support_base_dir is not None else None,
        "l16_source_path": l16_source_path,
        "current_date": current_date,
        "current_time_ms": current_time_ms,
        "current_time_z": current_time_z,
        "player": {
            "squadron_id": {
                "num": player_squadron[0],
                "creator": player_squadron[1],
            }
            if player_squadron is not None
            else None,
            "package_match_method": match_method,
        },
        "bullseye": bullseye,
        "package_count": len(packages),
        "packages": packages,
        "warnings": warnings,
    }
