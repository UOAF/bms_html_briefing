from jinja2 import Environment, FileSystemLoader
import os, sys, shutil, logging, filecmp
from PIL import Image

from lib.parse_brief import Briefing
from lib.parse_callsignini import Callsign_ini

logger = logging.getLogger('html_brief_log')
logger_ui = logging.getLogger('ui_logger')

def page_contents_ini_to_list(conf):
    return [[s.strip(' \n') for s in value.split(',') if s != ''] for key, value in conf['pages'].items()]

def generate_html_file(conf, bms_conf, name, page_num = 0):
    if getattr(sys, 'frozen', False):
        script_dir = os.path.dirname(sys.executable)
    else:
        script_dir = os.environ.get("BMS_BRIEF_HOME", os.path.dirname(sys.argv[0]))
    script_dir = os.path.abspath(script_dir)

    briefing_location = os.path.join(bms_conf.base_dir, "User", "Briefings", "briefing.txt")
    callsignini_location = os.path.join(bms_conf.base_dir, "User", "Config", bms_conf.callsign + ".ini")

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
        try:
            if (not filecmp.cmp(map_file, os.path.join(script_dir, 'assets', 'maps', 'map.png'), shallow = False)):
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

    page_contents = page_contents_ini_to_list(conf)

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
                                                 logo_present = True,
                                                 brief_is_joined = True
                                                 ))
    except Exception as e:
        logger.error(f"Couldn't generate HTML: {e}")
