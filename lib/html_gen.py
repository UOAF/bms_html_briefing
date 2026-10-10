from jinja2 import Environment, FileSystemLoader
import os, sys, logging
import math

from lib.airfields import resolve_briefing_airbase_names
from lib.brief_render import build_brief_render_context
from lib.atis import build_departure_atis
from lib.bms_paths import callsign_ini_path
from lib.dtc_fields import field_payload, format_value
from lib.fuel_brief import build_fuel_plan
from lib.admin_brief import build_admin_data
from lib.map_sources import map_selection as select_map, map_source_options as get_map_source_options
from lib.map_tiles import local_map_available, prepare_local_map_tiles, resolve_local_map_file
from lib.progress import ProgressCallback
from lib.parsers.parse_briefing_txt import Briefing
from lib.parsers.parse_callsign_ini import Callsign_ini

logger = logging.getLogger('html_brief_log')
logger_ui = logging.getLogger('ui_logger')


def _flightplan_headings(steerpoints, variations):
    headings = {}
    for point in steerpoints:
        heading = point.heading
        try:
            true_heading = float(heading)
        except (TypeError, ValueError):
            headings[str(point.number)] = heading
            continue
        variation = variations.get(str(point.number))
        if not math.isfinite(true_heading):
            heading = "—"
        elif variation is None:
            heading = f"{heading}°T"
        else:
            heading = str(math.floor((true_heading - variation) % 360 + 0.5) % 360)
        headings[str(point.number)] = heading
    return headings



def normalize_layout_pages(values):
    """Treat legacy package entries as an alias for the two independent sections."""
    pages = dict(values)
    for key, value in list(pages.items()):
        if key.startswith('page') and key[4:].isdigit():
            parts = [part.strip() for part in value.split(',')]
            if 'package' in parts:
                pages[key] = ', '.join(
                    part for entry in parts
                    for part in (['main_package', 'supporting_package'] if entry == 'package' else [entry])
                )
    return pages


def page_contents_ini_to_list(conf, *, warnings=None):
    """Keep each section's first placement in config order, retaining empty pages."""
    pages, seen = [], {}
    for key, value in normalize_layout_pages(conf['pages']).items():
        if not (key.casefold().startswith('page') and key[4:].isdigit()):
            continue
        sections = []
        for section in (entry.strip() for entry in value.split(',')):
            # Retired templates may still be present in a saved layout.
            if not section or section in ('datacard_1', 'datacard_2'):
                continue
            if section in seen:
                if warnings is not None:
                    warning = f'Duplicate section: {section}; kept: {seen[section]}; ignored: {key}'
                    if warning not in warnings:
                        warnings.append(warning)
                continue
            seen[section] = key
            sections.append(section)
        pages.append(sections)
    return pages


def _brief_page_styles(conf):
    settings = conf['briefing_style'] if 'briefing_style' in conf else {}

    def font_size(key, fallback):
        value = settings.get(key, '').strip()
        if not value:
            return fallback
        try:
            size = float(value)
            if 6 <= size <= 32:
                return size
        except ValueError:
            pass
        logger.warning('Invalid briefing_style.%s: %r; expected 6–32 pixels, using %s.', key, value, fallback)
        return fallback

    def spacing(key, fallback):
        value = settings.get(key, '').strip().lower()
        if not value:
            return fallback
        if value in ('normal', 'compact'):
            return value
        logger.warning('Invalid briefing_style.%s: %r; expected normal or compact, using %s.', key, value, fallback)
        return fallback

    default_size = font_size('font_size', 16)
    default_spacing = spacing('spacing', 'normal')
    styles = []
    for key in conf['pages']:
        if not (key.casefold().startswith('page') and key[4:].isdigit()):
            continue
        size = font_size(f'{key}_font_size', default_size)
        density = spacing(f'{key}_spacing', default_spacing)
        declarations = []
        if size != 16:
            declarations.extend([
                f'--brief-font-size: {size:g}px',
                f'--brief-heading-font-size: {size * 0.95:g}px',
            ])
        if density == 'compact':
            declarations.extend(['--brief-cell-padding: 1px 2px', '--brief-row-height: 1.3em'])
        styles.append('; '.join(declarations))
    return styles


def _page_contents_for_render(conf, brief_summary = None):
    page_contents = page_contents_ini_to_list(conf)
    if not isinstance(brief_summary, dict):
        return page_contents
    swapped_pages = []
    for page in page_contents:
        swapped_pages.append([
            {"main_package": "main_package_cam", "supporting_package": "supporting_package_cam"}.get(section, section)
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
    progress: ProgressCallback | None = None,
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
                progress=progress,
            )
            map_tile_url_template = local_map_tiles["map_tile_url_template"]
            map_tile_max_native_zoom = local_map_tiles["map_tile_max_native_zoom"]

    if progress is not None:
        progress(
            title="Preparing briefing",
            stage="brief_render",
            message="Rendering the briefing preview...",
            note=None,
            current=None,
            total=None,
        )

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
            ci = Callsign_ini()

        resolve_briefing_airbase_names(brf, ci, bms_conf)

        env = Environment(loader=FileSystemLoader(templates_dir))
        index_tmpl = env.get_template(template_name)
        render_context = build_brief_render_context(
            brief_summary=brief_summary,
            selected_package_index=selected_package_index,
            theater_center={
                "lat": getattr(bms_conf, "theater_center_latitude", None),
                "lng": getattr(bms_conf, "theater_center_longitude", None),
            },
            briefing_package_number=brf.overview.package_id,
            own_flight=getattr(brf, "own_flight", None),
            support_rows=brf.support,
        )

        dtc_fields = field_payload(ci, callsignini_location, bms_conf.theater, base_dir=bms_conf.base_dir)
        dtc_values = {key: format_value(key, value) for key, value in dtc_fields["values"].items()}
        fuel_plan = build_fuel_plan(
            summary=brief_summary, briefing=brf, dtc=ci,
            bms_base_dir=bms_conf.base_dir, theater=bms_conf.theater,
        )
        admin_data = build_admin_data(
            summary=brief_summary, briefing=brf, player_name=getattr(bms_conf, "pilot_name", ""),
            bms_base_dir=bms_conf.base_dir, theater=bms_conf.theater,
        )
        atis = build_departure_atis(
            summary=brief_summary, briefing=brf, dtc=ci, bms_conf=bms_conf,
        ) if any('atis' in page for page in page_contents) else {}

        logo_present = os.path.isfile(os.path.join(script_dir, "assets", "logo.png"))

        with open(os.path.join(conf['system']['output_dir'], name+".html"), "w", encoding = "utf-8") as index_output:
            index_output.write(index_tmpl.render(airbases = brf.airbases,
                                                 package_size = len(brf.package),
                                                 overview = brf.overview,
                                                 package = brf.package,
                                                 steerpoints = brf.steerpoints,
                                                 flightplan_headings = _flightplan_headings(brf.steerpoints, dtc_fields['magnetic_variation']),
                                                 fuel_plan = fuel_plan,
                                                 admin_data = admin_data,
                                                 own_flight = brf.own_flight,
                                                 support = brf.support,
                                                 roe = brf.roe,
                                                 weather = brf.weather,
                                                 atis = atis,
                                                 comm = brf.comm,
                                                 stpt_coords = ci.steerpoints,
                                                 tstpt_coords = ci.threat_steerpoints,
                                                 stpt_lines = ci.steerpoint_lines,
                                                 tgtsteerpoints = ci.tgtsteerpoints,
                                                 wpntgts = ci.wpntgts,
                                                 brief_pages = page_contents,
                                                 brief_page_keys = [key for key in conf['pages'] if key.startswith('page') and key[4:].isdigit()],
                                                 brief_page_styles = _brief_page_styles(conf),
                                                 cmds = ci.cmds,
                                                 icp_settings = ci.icp_settings,
                                                 dtc_fields = dtc_fields,
                                                 dtc_values = dtc_values,
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
                                                 map_flight_overlays = render_context["map_flight_overlays"],
                                                 map_tanker_overlay = render_context["map_tanker_overlay"],
                                                 ))
    except Exception as e:
        logger.error(f"Couldn't generate HTML: {e}")
