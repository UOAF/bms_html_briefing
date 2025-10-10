from jinja2 import Template, Environment, FileSystemLoader
import os, sys, logging, time
from lib.parse_brief import Briefing
from lib.parse_callsignini import Callsign_ini

logger = logging.getLogger('html_brief_log')
logging.basicConfig(filename='debug.log', filemode='w', encoding='utf-8', level=logging.DEBUG)

if getattr(sys, 'frozen', False):
    script_dir = os.path.dirname(sys.executable)
else:
    script_dir = os.path.dirname(sys.argv[0])

monitor = False
joined = True

output_dir = os.path.join(script_dir, "output")
os.makedirs(output_dir, exist_ok=True)

# parse config
with open(os.path.join(script_dir, "config.ini")) as config_file:
    try:
        config_contents = config_file.readlines()
        bms_location = next(l for l in config_contents if l.startswith("bms_location")).split("=")[1].strip("\n ")
        callsign = next(l for l in config_contents if l.startswith("callsign")).split("=")[1].strip("\n ")
        page_contents = [[p.strip("\n ") for p in l.split("=")[1].split(",")] for l in config_contents if l.startswith("page")]
    except Exception as e:
        logger.error(f"Couldn't load config: {e}")

    logo_present = os.path.isfile(os.path.join(script_dir, "assets", "logo.png"))

    try:
        joined = (next(l for l in config_contents if l.startswith("joined")).split("=")[1].strip("\n ")) == "True"
    except Exception as e:
        print(f"Joined or not is not specified in config: {e}")
        logger.warning(f"Joined or not is not specified in config: {e}")
    try:
        monitor = (next(l for l in config_contents if l.startswith("monitor")).split("=")[1].strip("\n ")) == "True"
    except Exception as e:
        logger.warning(f"Monitor or not is not specified in config: {e}")

if (len(sys.argv) > 1):
   if "-m" in sys.argv or "--monitor" in sys.argv:
       monitor = True
   if "-s" in sys.argv or "--separated" in sys.argv:
       joined = False
   

briefing_location = os.path.join(bms_location, "User", "Briefings", "briefing.txt")
callsignini_location = os.path.join(bms_location, "User", "Config", callsign + ".ini")

templates_dir = os.path.join(script_dir, 'templates')

def generate_html_file(name, page_num = 0):
    try:
        with open(briefing_location, "r", encoding = "latin1") as briefing_file:
            briefing_contents = briefing_file.readlines()
            brf = Briefing(briefing_contents)
        
            with open(callsignini_location, "r", encoding = "latin1") as callsignini_file:
                callsignini_contents = callsignini_file.readlines()
                ci = Callsign_ini(callsignini_contents)

            env = Environment(loader=FileSystemLoader(templates_dir))
            index_tmpl = env.get_template("index.html")

#        os.makedirs(os.path.join(script_dir, "output"), exist_ok = True)
        with open(os.path.join(output_dir, name+".html"), "w", encoding = "utf-8") as index_output:
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
                                                 brief_is_joined = joined))
    except Exception as e:
        print(f"Couldn't generate HTML: {e}")
        logger.error(f"Couldn't generate HTML: {e}")

if joined == True:
    generate_html_file("index_joined", 0)
else:
    for i, c in enumerate(page_contents):
        generate_html_file("index_"+str(i + 1), i+1)

if monitor:
    print("Monitoring files for changes...")
    last_modified = max(os.path.getmtime(callsignini_location), os.path.getmtime(briefing_location))
    while True:
        current_modified = max(os.path.getmtime(callsignini_location), os.path.getmtime(briefing_location))
        if current_modified != last_modified:
            if joined == True:
                generate_html_file("index_joined", 0)
            else:
                for i, c in enumerate(page_contents):
                    generate_html_file("index_"+str(i + 1), i+1)
                    
            last_modified = current_modified
            print("Files updated.")
        time.sleep(2)



