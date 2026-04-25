from jinja2 import Environment, FileSystemLoader
import os, sys, shutil, logging, filecmp
from PIL import Image

from lib.brief_render import build_brief_render_context
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


def generate_html_file(conf, bms_conf, name, page_num = 0, brief_summary = None, selected_package_index = None):
    if getattr(sys, 'frozen', False):
        script_dir = os.path.dirname(sys.executable)
    else:
        script_dir = os.environ.get("BMS_BRIEF_HOME", os.path.dirname(sys.argv[0]))
    script_dir = os.path.abspath(script_dir)

    briefing_location = os.path.join(bms_conf.base_dir, "User", "Briefings", "briefing.txt")
    callsignini_location = os.path.join(bms_conf.base_dir, "User", "Config", bms_conf.callsign + ".ini")
    #create map folder if it doesn't exist
    try:
        os.mkdir(os.path.join(script_dir, 'assets', 'maps'))
    except Exception as e:
        logger.info(e)

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


    if os.path.isfile(map_file):
        map_exists = False
        try: 
            map_exists = filecmp.cmp(map_file, os.path.join(script_dir, 'assets', 'maps', 'map.png'), shallow = False)
        except Exception as e:
            logger.error(e)
        try:
            if (not map_exists):
                logger_ui.info(f'Copying the map file {map_file}.')
                with Image.open(map_file) as im:
                    if im.size != (4096, 4096):
                        logger_ui.info('The image is not 4K. Resizing. This may take some time: consider saving a 4K image as the default map for this theater.')
                        resized = im.resize((4096, 4096))
                        resized.save(os.path.join(script_dir, 'assets', 'maps', 'map.png'))
                    else:
                        shutil.copyfile(map_file, os.path.join(script_dir, 'assets', 'maps', 'map.png'))
        except Exception as e:
            logger.error(e)
    else:
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
                                                 package_options = render_context["package_options"],
                                                 support_package_rows = render_context["support_package_rows"],
                                                 main_package_l16 = render_context["main_package_l16"],
                                                 bullseye = render_context["bullseye"],
                                                 moon_data = render_context["moon_data"],
                                                 ))
    except Exception as e:
        logger.error(f"Couldn't generate HTML: {e}")
