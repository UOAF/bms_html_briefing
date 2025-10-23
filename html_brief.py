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
bms_version = "4.38"

output_dir = os.path.join(script_dir, "output")
os.makedirs(output_dir, exist_ok=True)

# get config path
config_path = os.path.join(script_dir, "config.ini") 
for i, arg in enumerate(sys.argv):
   if arg == "-c" or arg == "--config":
       config_path = sys.argv[i+1]

# parse config
with open(config_path) as config_file:
    # mandatory arguments
    try:
        config_contents = config_file.readlines()
        if sys.platform == 'linux':
            wine_prefix = next(l for l in config_contents if l.startswith("wine_prefix")).split("=")[1].strip("\n ")
        page_contents = [[p.strip("\n ") for p in l.split("=")[1].split(",")] for l in config_contents if l.startswith("page")]

    except Exception as e:
        logger.error(f"Couldn't load config: {e}")

    logo_present = os.path.isfile(os.path.join(script_dir, "assets", "logo.png"))

    # optional arguments
    try:
        joined = (next(l for l in config_contents if l.startswith("joined")).split("=")[1].strip("\n ")) == "True"
    except Exception as e:
        print(f"Joined or not is not specified in config: {e}")
        logger.warning(f"Joined or not is not specified in config: {e}")
    try:
        monitor = (next(l for l in config_contents if l.startswith("monitor")).split("=")[1].strip("\n ")) == "True"
    except Exception as e:
        logger.warning(f"Monitor or not is not specified in config: {e}")
    try:
        bms_version = next(l for l in config_contents if l.startswith("bms_version")).split("=")[1].strip("\n ")
    except Exception as e:
        logger.warning(f"BMS version is not specified in config: {e}")


for i, arg in enumerate(sys.argv):
   if arg == "-m" or arg == "--monitor":
       monitor = True
   if arg == "-s" or arg == "--separated":
       joined = False

# get BMS location
if sys.platform == 'linux':
    print(f"We are on Linux! Wine prefix is {wine_prefix}.")
    with open(os.path.join(wine_prefix, "system.reg"), "r") as reg_file:
        reg_file_contents = reg_file.readlines()
    entry_start = next(i for i,l in enumerate(reg_file_contents) if l.startswith("[Software\\\\Wow6432Node\\\\Benchmark Sims\\\\Falcon BMS " + bms_version + "]"))
    base_dir_win = next(l for l in reg_file_contents[entry_start:] if l.strip('\"').startswith("baseDir")).split('=')[1].strip('\"\n')
    callsign_reg = next(l for l in reg_file_contents[entry_start:] if l.strip('\"').startswith("PilotCallsign")).split('=')[1].strip('\"\n')
    callsign = ''.join([chr(int(c, 16)) for c in callsign_reg.split(':')[-1].split(',')]).strip('\x00')
    print(f"Callsign is: {callsign}")
    base_dir = os.path.join(wine_prefix, "drive_" + base_dir_win.split(":\\")[0].lower(), *base_dir_win.split("\\")[1:])
    print(f"Base dir is: {base_dir}")

if sys.platform == 'win32' or sys.platform == 'cygwin':
    import winreg
    baseSubKey = r"SOFTWARE\WOW6432Node\Benchmark Sims\Falcon BMS " + bms_version + r"\\"
    regHandle = winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE)
    keyHandle = winreg.OpenKey(regHandle, baseSubKey)
    callsign_reg = winreg.QueryValueEx(keyHandle, "PilotCallsign")[0]
    callsign = callsign_reg.decode('utf-8').strip('\x00')
    print(f"Callsign is: {callsign}")
    base_dir = winreg.QueryValueEx(keyHandle, "baseDir")[0]
    print(f"Base dir is: {base_dir}")


briefing_location = os.path.join(base_dir, "User", "Briefings", "briefing.txt")
callsignini_location = os.path.join(base_dir, "User", "Config", callsign + ".ini")

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
                                                 brief_is_joined = joined,
                                                 ))
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



