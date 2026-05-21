from jinja2 import Environment, FileSystemLoader
import os, sys, logging

from lib.brief_render import build_brief_render_context
from lib.bms_paths import callsign_ini_path
from lib.map_sources import map_selection as select_map, map_source_options as get_map_source_options
from lib.map_tiles import local_map_available, prepare_local_map_tiles, resolve_local_map_file
from lib.parsers.parse_briefing_txt import Briefing
from lib.parsers.parse_callsign_ini import Callsign_ini

logger = logging.getLogger('html_brief_log')
logger_ui = logging.getLogger('ui_logger')


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


def generate_html_file(
    conf,
    bms_conf,
    name,
    page_num = 0,
    brief_summary = None,
    selected_package_index = None,
    template_name = "index.html",
    pdf_mode = False,
    pdf_artifacts = None,
):
    if getattr(sys, 'frozen', False):
        script_dir = os.path.dirname(sys.executable)
    else:
        script_dir = os.environ.get("BMS_BRIEF_HOME", os.path.dirname(sys.argv[0]))
    script_dir = os.path.abspath(script_dir)

    briefing_location = os.path.join(bms_conf.base_dir, "User", "Briefings", "briefing.txt")
    callsignini_location = callsign_ini_path(bms_conf)
    map_dir = os.path.join(script_dir, 'assets', 'maps')
    try:
        os.makedirs(map_dir, exist_ok=True)
    except Exception as e:
        logger.error(e)
        logger_ui.error(f"Couldn't create the map folder: {e}")

    map_selection = select_map(conf, getattr(bms_conf, "version", None))
    map_id = map_selection["id"]
    map_base_mode = map_selection["base_mode"]
    web_tile_url_template = map_selection["web_tile_url_template"]
    web_tile_attribution = map_selection["web_tile_attribution"]
    web_tile_filter = map_selection["web_tile_filter"]
    web_tile_layers = map_selection["web_tile_layers"]
    web_tile_max_zoom = map_selection["web_tile_max_zoom"]

    map_tile_max_native_zoom = 0
    map_tile_url_template = ""
    if map_base_mode == "web":
        logger_ui.info("Using web map tiles; local map tile generation skipped.")
    else:
        map_file = resolve_local_map_file(bms_conf, script_dir)
        if not local_map_available(map_file):
            logger_ui.error("Map skipped: no map file configured for %s %s.", bms_conf.version, bms_conf.theater)
            map_base_mode = "none"
        elif pdf_mode:
            logger.debug("PDF mode render: local map tile generation skipped.")
        else:
            local_map_tiles = prepare_local_map_tiles(
                map_file,
                map_dir,
                bms_conf.theater,
                getattr(bms_conf, "version", None),
            )
            map_tile_url_template = local_map_tiles["map_tile_url_template"]
            map_tile_max_native_zoom = local_map_tiles["map_tile_max_native_zoom"]

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
        index_tmpl = env.get_template(template_name)
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
                                                 pdf_mode = pdf_mode,
                                                 pdf_artifacts = pdf_artifacts or {},
                                                 map_id = map_id,
                                                 map_available = map_base_mode != "none",
                                                 map_source_options = get_map_source_options(getattr(bms_conf, "version", None)),
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
