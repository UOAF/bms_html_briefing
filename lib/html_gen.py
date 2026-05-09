from jinja2 import Environment, FileSystemLoader
import os, sys, shutil, logging, filecmp, hashlib, math, re
from threading import Lock
from uuid import uuid4
from PIL import Image

from lib.brief_render import build_brief_render_context
from lib.parsers.parse_briefing_txt import Briefing
from lib.parsers.parse_callsign_ini import Callsign_ini

logger = logging.getLogger('html_brief_log')
logger_ui = logging.getLogger('ui_logger')

MAP_LOGICAL_SIZE = (4096, 4096)
MAP_TILE_SIZE = 256
MAP_TILE_MIN_ZOOM = -3
MAP_TILE_MAX_NATIVE_ZOOM_CAP = 2
MAP_TILE_MANIFEST = "manifest.txt"
MAP_MAX_SOURCE_PIXELS = MAP_LOGICAL_SIZE[0] * MAP_LOGICAL_SIZE[1] * (2 ** MAP_TILE_MAX_NATIVE_ZOOM_CAP) ** 2
LOCAL_MAP_ID = "local"
WEB_MAP_SOURCES = {
    "esri_imagery_hybrid": {
        "max_zoom": 23,
        "layers": [
            {
                "url_template": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                "attribution": "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
                "filter": "brightness(1.0) saturate(1.0) contrast(1.0)",
                "max_native_zoom": 23,
            },
            {
                "url_template": "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
                "attribution": "Tiles &copy; Esri",
                "max_native_zoom": 23,
            },
        ],
    },
}

Image.MAX_IMAGE_PIXELS = max(Image.MAX_IMAGE_PIXELS or 0, MAP_MAX_SOURCE_PIXELS)

_map_tile_locks = {}
_map_tile_locks_guard = Lock()


def page_contents_ini_to_list(conf):
    return [[s.strip(' \n') for s in value.split(',') if s != ''] for key, value in conf['pages'].items()]


def _page_contents_for_render(conf, brief_summary = None):
    page_contents = page_contents_ini_to_list(conf)
    if not isinstance(brief_summary, dict):
        return page_contents
    swapped_pages = []
    for page in page_contents:
        swapped_pages.append([
            "package_cam" if section == "package" else section
            for section in page
        ])
    return swapped_pages


def _map_digest(map_path):
    digest = hashlib.sha256()
    with open(map_path, "rb") as map_file:
        for chunk in iter(lambda: map_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _map_cache_slug(name):
    slug = re.sub(r"[^a-z0-9._-]+", "-", (name or "default").strip().lower())
    slug = slug.strip(".-")
    return slug or "default"


def _map_selection(conf):
    try:
        raw = conf["system"].get("map", LOCAL_MAP_ID)
    except Exception:
        raw = LOCAL_MAP_ID
    map_id = str(raw).strip().lower().replace("-", "_") or LOCAL_MAP_ID
    if map_id in WEB_MAP_SOURCES:
        return _map_selection_from_id(map_id)

    return _map_selection_from_id(LOCAL_MAP_ID)


def _map_selection_from_id(map_id):
    if map_id in WEB_MAP_SOURCES:
        source = WEB_MAP_SOURCES[map_id]
        layers = source.get("layers") or [source]
        first_layer = layers[0] if layers else {}
        return {
            "id": map_id,
            "base_mode": "web",
            "web_tile_layers": layers,
            "web_tile_url_template": first_layer.get("url_template", ""),
            "web_tile_attribution": first_layer.get("attribution", ""),
            "web_tile_filter": first_layer.get("filter", ""),
            "web_tile_max_zoom": source.get("max_zoom", 19),
        }
    return {
        "id": LOCAL_MAP_ID,
        "base_mode": "local_tiles",
        "web_tile_layers": [],
        "web_tile_url_template": "",
        "web_tile_attribution": "",
        "web_tile_filter": "",
        "web_tile_max_zoom": 19,
    }


def _map_tile_info(map_path):
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


def _map_tile_lock(tile_cache_dir):
    abs_dir = os.path.abspath(tile_cache_dir)
    with _map_tile_locks_guard:
        lock = _map_tile_locks.get(abs_dir)
        if lock is None:
            lock = Lock()
            _map_tile_locks[abs_dir] = lock
        return lock


def _tile_manifest_text(source_digest, tile_info):
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


def _map_tiles_current(tile_cache_dir, map_path, source_digest):
    manifest_path = os.path.join(tile_cache_dir, "tiles", MAP_TILE_MANIFEST)
    try:
        manifest = open(manifest_path, "r", encoding="utf-8").read()
    except Exception:
        return False
    tile_info = _map_tile_info(map_path)
    if manifest != _tile_manifest_text(source_digest, tile_info):
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


def _generate_map_tiles(map_path, tile_cache_dir, source_digest):
    tiles_dir = os.path.join(tile_cache_dir, "tiles")
    tmp_tiles_dir = os.path.join(tile_cache_dir, f"tiles.tmp.{os.getpid()}.{uuid4().hex}")
    os.makedirs(tile_cache_dir, exist_ok=True)

    tile_info = _map_tile_info(map_path)
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
            manifest_file.write(_tile_manifest_text(source_digest, tile_info))

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


def generate_html_file(conf, bms_conf, name, page_num = 0, brief_summary = None, selected_package_index = None):
    if getattr(sys, 'frozen', False):
        script_dir = os.path.dirname(sys.executable)
    else:
        script_dir = os.environ.get("BMS_BRIEF_HOME", os.path.dirname(sys.argv[0]))
    script_dir = os.path.abspath(script_dir)

    briefing_location = os.path.join(bms_conf.base_dir, "User", "Briefings", "briefing.txt")
    callsignini_location = os.path.join(bms_conf.base_dir, "User", "Config", bms_conf.callsign + ".ini")
    map_dir = os.path.join(script_dir, 'assets', 'maps')
    try:
        os.makedirs(map_dir, exist_ok=True)
    except Exception as e:
        logger.error(e)
        logger_ui.error(f"Couldn't create the map folder: {e}")

    map_selection = _map_selection(conf)
    map_id = map_selection["id"]
    map_base_mode = map_selection["base_mode"]
    web_tile_url_template = map_selection["web_tile_url_template"]
    web_tile_attribution = map_selection["web_tile_attribution"]
    web_tile_filter = map_selection["web_tile_filter"]
    web_tile_layers = map_selection["web_tile_layers"]
    web_tile_max_zoom = map_selection["web_tile_max_zoom"]

    # load map location
    map_file = ''
    if bms_conf.theater_config.has_option(bms_conf.theater, 'map_file'):
        map_file = bms_conf.theater_config[bms_conf.theater]['map_file']
    else:
        if bms_conf.theater_config.has_option(bms_conf.theater, 'default_map_file'):
            map_file = os.path.join(bms_conf.base_dir, bms_conf.theater_config[bms_conf.theater]['default_map_file'])

    # normalize relative paths to absolute (needed when theater ini stores relative paths)
    if map_file and not os.path.isabs(map_file):
        map_file = os.path.join(bms_conf.base_dir, map_file)

    # fallback to bundled map if nothing set
    if not map_file:
        map_file = os.path.join(script_dir, 'assets', 'maps', 'map.png')

    map_output_path = os.path.join(map_dir, 'map.png')
    map_cache_slug = _map_cache_slug(bms_conf.theater)
    map_cache_dir = os.path.join(map_dir, "theaters", map_cache_slug)
    map_cache_output_path = os.path.join(map_cache_dir, "map.png")
    map_tile_url_template = f"assets/maps/theaters/{map_cache_slug}/tiles/{{z}}/{{x}}/{{y}}.png"
    map_tile_max_native_zoom = 0
    if map_base_mode == "web":
        logger_ui.info("Using web map tiles; local map tile generation skipped.")
    elif os.path.isfile(map_file):
        try:
            source_digest = _map_digest(map_file)
            cache_map_exists = (
                os.path.isfile(map_cache_output_path)
                and _map_digest(map_cache_output_path) == source_digest
            )
            legacy_map_exists = False
            if os.path.isfile(map_output_path):
                try:
                    legacy_map_exists = filecmp.cmp(map_file, map_output_path, shallow = False)
                except Exception as e:
                    logger.error(e)
            if not cache_map_exists:
                logger_ui.info(f'Copying the map file {map_file}.')
                os.makedirs(map_cache_dir, exist_ok=True)
                with Image.open(map_file) as im:
                    if im.size != MAP_LOGICAL_SIZE:
                        logger_ui.info(f'Map image is {im.size[0]}x{im.size[1]}; internal map coordinates remain 4096x4096.')
                    if im.format == "PNG":
                        shutil.copyfile(map_file, map_cache_output_path)
                    else:
                        im.save(map_cache_output_path)
            if not legacy_map_exists:
                try:
                    shutil.copyfile(map_cache_output_path, map_output_path)
                except Exception as e:
                    logger.error(e)
            if not _map_tiles_current(map_cache_dir, map_cache_output_path, source_digest):
                with _map_tile_lock(map_cache_dir):
                    if not _map_tiles_current(map_cache_dir, map_cache_output_path, source_digest):
                        _generate_map_tiles(map_cache_output_path, map_cache_dir, source_digest)
            map_tile_max_native_zoom = _map_tile_info(map_cache_output_path)["max_native_zoom"]
        except Exception as e:
            logger.error(e)
            logger_ui.error(f"Couldn't prepare the map file: {e}")
    elif map_base_mode != "web":
        logger_ui.error(f"Couldn't find the map file: {map_file}")

    templates_dir = os.path.join(script_dir, 'templates')

    page_contents = _page_contents_for_render(conf, brief_summary = brief_summary)

    try:
        with open(briefing_location, "r", encoding = "latin1") as briefing_file:
            briefing_contents = briefing_file.readlines()
        brf = Briefing(briefing_contents)

        try:
            with open(callsignini_location, "r", encoding = "latin1") as callsignini_file:
                callsignini_contents = callsignini_file.readlines()
            ci = Callsign_ini(callsignini_contents)
        except Exception as e:
            logger.error(f"Couldn't load callsign.ini: {e}")

        env = Environment(loader=FileSystemLoader(templates_dir))
        index_tmpl = env.get_template("index.html")
        render_context = build_brief_render_context(
            brief_summary=brief_summary,
            selected_package_index=selected_package_index,
            theater_center={
                "lat": getattr(bms_conf, "theater_center_latitude", None),
                "lng": getattr(bms_conf, "theater_center_longitude", None),
            },
        )

        logo_present = os.path.isfile(os.path.join(script_dir, "assets", "logo.png"))

        with open(os.path.join(conf['system']['output_dir'], name+".html"), "w", encoding = "utf-8") as index_output:
            index_output.write(index_tmpl.render(airbases = brf.airbases,
                                                 package_size = len(brf.package),
                                                 overview = brf.overview,
                                                 package = brf.package,
                                                 steerpoints = brf.steerpoints,
                                                 own_flight = brf.own_flight,
                                                 support = brf.support,
                                                 roe = brf.roe,
                                                 weather = brf.weather,
                                                 comm = brf.comm,
                                                 stpt_coords = ci.steerpoints,
                                                 tstpt_coords = ci.threat_steerpoints,
                                                 stpt_lines = ci.steerpoint_lines,
                                                 tgtsteerpoints = ci.tgtsteerpoints,
                                                 wpntgts = ci.wpntgts,
                                                 brief_pages = page_contents,
                                                 cmds = ci.cmds,
                                                 num = page_num,
                                                 logo_present = logo_present,
                                                 brief_is_joined = True,
                                                 map_id = map_id,
                                                 map_base_mode = map_base_mode,
                                                 theater_name = bms_conf.theater,
                                                 theater_center_latitude = getattr(bms_conf, "theater_center_latitude", None),
                                                 theater_center_longitude = getattr(bms_conf, "theater_center_longitude", None),
                                                 theater_size_km = getattr(bms_conf, "theater_size_km", None),
                                                 web_tile_url_template = web_tile_url_template,
                                                 web_tile_attribution = web_tile_attribution,
                                                 web_tile_filter = web_tile_filter,
                                                 web_tile_layers = web_tile_layers,
                                                 web_tile_max_zoom = web_tile_max_zoom,
                                                 map_tile_max_native_zoom = map_tile_max_native_zoom,
                                                 map_tile_url_template = map_tile_url_template,
                                                 package_options = render_context["package_options"],
                                                 support_package_rows = render_context["support_package_rows"],
                                                 main_package_l16 = render_context["main_package_l16"],
                                                 bullseye = render_context["bullseye"],
                                                 moon_data = render_context["moon_data"],
                                                 ))
    except Exception as e:
        logger.error(f"Couldn't generate HTML: {e}")
