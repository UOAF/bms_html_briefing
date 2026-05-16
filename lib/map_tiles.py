import filecmp
import hashlib
import logging
import math
import os
import re
import shutil
from threading import Lock
from uuid import uuid4

from PIL import Image

logger = logging.getLogger("html_brief_log")
logger_ui = logging.getLogger("ui_logger")

MAP_LOGICAL_SIZE = (4096, 4096)
MAP_TILE_SIZE = 256
MAP_TILE_MIN_ZOOM = -3
MAP_TILE_MAX_NATIVE_ZOOM_CAP = 2
MAP_TILE_MANIFEST = "manifest.txt"
MAP_MAX_SOURCE_PIXELS = MAP_LOGICAL_SIZE[0] * MAP_LOGICAL_SIZE[1] * (2 ** MAP_TILE_MAX_NATIVE_ZOOM_CAP) ** 2

Image.MAX_IMAGE_PIXELS = max(Image.MAX_IMAGE_PIXELS or 0, MAP_MAX_SOURCE_PIXELS)

_map_tile_locks = {}
_map_tile_locks_guard = Lock()


def map_digest(map_path):
    digest = hashlib.sha256()
    with open(map_path, "rb") as map_file:
        for chunk in iter(lambda: map_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def map_cache_slug(name):
    slug = re.sub(r"[^a-z0-9._-]+", "-", (name or "default").strip().lower())
    slug = slug.strip(".-")
    return slug or "default"


def map_tile_info(map_path):
    with Image.open(map_path) as im:
        source_size = im.size
    max_dim = max(source_size)
    if max_dim <= MAP_LOGICAL_SIZE[0]:
        max_native_zoom = 0
    else:
        max_native_zoom = int(math.ceil(math.log(max_dim / MAP_LOGICAL_SIZE[0], 2)))
        max_native_zoom = min(max_native_zoom, MAP_TILE_MAX_NATIVE_ZOOM_CAP)
    return {
        "source_size": source_size,
        "max_native_zoom": max_native_zoom,
    }


def map_tile_lock(tile_cache_dir):
    abs_dir = os.path.abspath(tile_cache_dir)
    with _map_tile_locks_guard:
        lock = _map_tile_locks.get(abs_dir)
        if lock is None:
            lock = Lock()
            _map_tile_locks[abs_dir] = lock
        return lock


def tile_manifest_text(source_digest, tile_info):
    source_width, source_height = tile_info["source_size"]
    return "\n".join([
        f"source_sha256={source_digest}",
        f"source_size={source_width}x{source_height}",
        f"logical_size={MAP_LOGICAL_SIZE[0]}x{MAP_LOGICAL_SIZE[1]}",
        f"tile_size={MAP_TILE_SIZE}",
        f"min_zoom={MAP_TILE_MIN_ZOOM}",
        f"max_native_zoom={tile_info['max_native_zoom']}",
        "",
    ])


def map_tiles_current(tile_cache_dir, map_path, source_digest):
    manifest_path = os.path.join(tile_cache_dir, "tiles", MAP_TILE_MANIFEST)
    try:
        manifest = open(manifest_path, "r", encoding="utf-8").read()
    except Exception:
        return False
    tile_info = map_tile_info(map_path)
    if manifest != tile_manifest_text(source_digest, tile_info):
        return False
    for zoom in range(MAP_TILE_MIN_ZOOM, tile_info["max_native_zoom"] + 1):
        level_size = int(MAP_LOGICAL_SIZE[0] * (2 ** zoom))
        tile_count = (level_size + MAP_TILE_SIZE - 1) // MAP_TILE_SIZE
        zoom_dir = os.path.join(tile_cache_dir, "tiles", str(zoom))
        found = 0
        for x in range(tile_count):
            x_dir = os.path.join(zoom_dir, str(x))
            if not os.path.isdir(x_dir):
                return False
            for y in range(tile_count):
                if not os.path.isfile(os.path.join(x_dir, f"{y}.png")):
                    return False
                found += 1
        if found != tile_count * tile_count:
            return False
    return True


def generate_map_tiles(map_path, tile_cache_dir, source_digest):
    tiles_dir = os.path.join(tile_cache_dir, "tiles")
    tmp_tiles_dir = os.path.join(tile_cache_dir, f"tiles.tmp.{os.getpid()}.{uuid4().hex}")
    os.makedirs(tile_cache_dir, exist_ok=True)

    tile_info = map_tile_info(map_path)
    max_native_zoom = tile_info["max_native_zoom"]
    source_width, source_height = tile_info["source_size"]
    expected_tiles = sum(
        ((int(MAP_LOGICAL_SIZE[0] * (2 ** zoom)) + MAP_TILE_SIZE - 1) // MAP_TILE_SIZE) ** 2
        for zoom in range(MAP_TILE_MIN_ZOOM, max_native_zoom + 1)
    )
    logger_ui.info(
        "Generating map tiles: source=%dx%d logical=%dx%d native_zoom=%d total_tiles=%d.",
        source_width,
        source_height,
        MAP_LOGICAL_SIZE[0],
        MAP_LOGICAL_SIZE[1],
        max_native_zoom,
        expected_tiles,
    )
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    try:
        with Image.open(map_path) as im:
            base = im.convert("RGB")
            for zoom in range(MAP_TILE_MIN_ZOOM, max_native_zoom + 1):
                level_size = int(MAP_LOGICAL_SIZE[0] * (2 ** zoom))
                level = base.resize((level_size, level_size), resample) if base.size != (level_size, level_size) else base.copy()
                tile_count = (level_size + MAP_TILE_SIZE - 1) // MAP_TILE_SIZE
                logger_ui.info(
                    "Generating map tiles: zoom %d (%dx%d, %d tiles).",
                    zoom,
                    level_size,
                    level_size,
                    tile_count * tile_count,
                )
                for x in range(tile_count):
                    for y in range(tile_count):
                        tile = Image.new("RGB", (MAP_TILE_SIZE, MAP_TILE_SIZE), "white")
                        crop = level.crop((
                            x * MAP_TILE_SIZE,
                            y * MAP_TILE_SIZE,
                            min((x + 1) * MAP_TILE_SIZE, level_size),
                            min((y + 1) * MAP_TILE_SIZE, level_size),
                        ))
                        tile.paste(crop, (0, 0))
                        tile_dir = os.path.join(tmp_tiles_dir, str(zoom), str(x))
                        os.makedirs(tile_dir, exist_ok=True)
                        tile.save(os.path.join(tile_dir, f"{y}.png"))

        with open(os.path.join(tmp_tiles_dir, MAP_TILE_MANIFEST), "w", encoding="utf-8") as manifest_file:
            manifest_file.write(tile_manifest_text(source_digest, tile_info))

        old_tiles_dir = os.path.join(tile_cache_dir, f"tiles.old.{os.getpid()}.{uuid4().hex}")
        if os.path.isdir(tiles_dir):
            os.replace(tiles_dir, old_tiles_dir)
        os.replace(tmp_tiles_dir, tiles_dir)
        if os.path.isdir(old_tiles_dir):
            shutil.rmtree(old_tiles_dir, ignore_errors=True)
        logger_ui.info("Map tile generation complete.")
    finally:
        if os.path.isdir(tmp_tiles_dir):
            shutil.rmtree(tmp_tiles_dir, ignore_errors=True)


def resolve_local_map_file(bms_conf, script_dir):
    map_file = ""
    if bms_conf.theater_config.has_option(bms_conf.theater, "map_file"):
        map_file = bms_conf.theater_config[bms_conf.theater]["map_file"]
    elif bms_conf.theater_config.has_option(bms_conf.theater, "default_map_file"):
        map_file = os.path.join(
            bms_conf.base_dir,
            bms_conf.theater_config[bms_conf.theater]["default_map_file"],
        )

    if map_file and not os.path.isabs(map_file):
        map_file = os.path.join(bms_conf.base_dir, map_file)

    if not map_file:
        map_file = os.path.join(script_dir, "assets", "maps", "map.png")

    return map_file


def prepare_local_map_tiles(map_file, map_dir, theater):
    map_output_path = os.path.join(map_dir, "map.png")
    cache_slug = map_cache_slug(theater)
    cache_dir = os.path.join(map_dir, "theaters", cache_slug)
    cache_output_path = os.path.join(cache_dir, "map.png")
    tile_url_template = f"assets/maps/theaters/{cache_slug}/tiles/{{z}}/{{x}}/{{y}}.png"
    max_native_zoom = 0

    if not os.path.isfile(map_file):
        logger_ui.error(f"Couldn't find the map file: {map_file}")
        return {
            "map_tile_url_template": tile_url_template,
            "map_tile_max_native_zoom": max_native_zoom,
        }

    try:
        source_digest = map_digest(map_file)
        cache_map_exists = (
            os.path.isfile(cache_output_path)
            and map_digest(cache_output_path) == source_digest
        )
        legacy_map_exists = False
        if os.path.isfile(map_output_path):
            try:
                legacy_map_exists = filecmp.cmp(map_file, map_output_path, shallow=False)
            except Exception as e:
                logger.error(e)
        if not cache_map_exists:
            logger_ui.info(f"Copying the map file {map_file}.")
            os.makedirs(cache_dir, exist_ok=True)
            with Image.open(map_file) as im:
                if im.size != MAP_LOGICAL_SIZE:
                    logger_ui.info(f"Map image is {im.size[0]}x{im.size[1]}; internal map coordinates remain 4096x4096.")
                if im.format == "PNG":
                    shutil.copyfile(map_file, cache_output_path)
                else:
                    im.save(cache_output_path)
        if not legacy_map_exists:
            try:
                shutil.copyfile(cache_output_path, map_output_path)
            except Exception as e:
                logger.error(e)
        if not map_tiles_current(cache_dir, cache_output_path, source_digest):
            with map_tile_lock(cache_dir):
                if not map_tiles_current(cache_dir, cache_output_path, source_digest):
                    generate_map_tiles(cache_output_path, cache_dir, source_digest)
        max_native_zoom = map_tile_info(cache_output_path)["max_native_zoom"]
    except Exception as e:
        logger.error(e)
        logger_ui.error(f"Couldn't prepare the map file: {e}")

    return {
        "map_tile_url_template": tile_url_template,
        "map_tile_max_native_zoom": max_native_zoom,
    }
