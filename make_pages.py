from jinja2 import Template, Environment, FileSystemLoader
import os, sys
import parse_brief, parse_callsignini

# parse config

if len(sys.argv) > 1:
    config_path = sys.argv[1]
else:
    print("Please provide the config.ini file.")
    exit()

with open(config_path) as config_file:
    try:
        config_contents = config_file.readlines()
        bms_location = next(l for l in config_contents if l.startswith("bms_location")).split("=")[1].strip("\n ")
        output_folder = next(l for l in config_contents if l.startswith("output_folder")).split("=")[1].strip("\n ")
        callsign = next(l for l in config_contents if l.startswith("callsign")).split("=")[1].strip("\n ")
        page_contents = [[p.strip("\n ") for p in l.split("=")[1].split(",")] for l in config_contents if l.startswith("page")]
        joined = (next(l for l in config_contents if l.startswith("joined")).split("=")[1].strip("\n ")) == "True"
    except Exception as e:
        print(f"Couldn't load config: {e}")

briefing_location = os.path.join(bms_location, "User", "Briefings", "briefing.txt")
callsignini_location = os.path.join(bms_location, "User", "Config", callsign + ".ini")

script_dir = os.path.dirname(__file__)
templates_dir = os.path.join(script_dir, 'templates')

def generate_html_file(name, page_num = 0):
    try:
        with open(briefing_location, encoding = "latin1") as briefing_file:
            briefing_contents = briefing_file.readlines()
            brf = parse_brief.Briefing(briefing_contents)
        
            with open(callsignini_location, encoding = "latin1") as callsignini_file:
                callsignini_contents = callsignini_file.readlines()
                ci = parse_callsignini.Callsign_ini(callsignini_contents)

            env = Environment(loader=FileSystemLoader(templates_dir))
            if page_num == 0:
                index_tmpl = env.get_template("index_joined.html")
            else:
                index_tmpl = env.get_template("index.html")

#        os.makedirs(os.path.join(script_dir, "output"), exist_ok = True)
        with open(os.path.join(output_folder, name+".html"), "w") as index_output:
            index_output.write(index_tmpl.render(airbases = brf.airbases,
                                                 package_size = len(brf.package),
                                                 overview = brf.overview,
                                                 package = brf.package,
                                                 steerpoints = brf.steerpoints,
                                                 own_flight = brf.own_flight,
                                                 support = brf.support,
                                                 roe = brf.roe,
                                                 weather = brf.weather,
                                                 tgtsteerpoints = ci.tgtsteerpoints,
                                                 brief_pages = page_contents,
                                                 cmds = ci.cmds,
                                                 num = page_num))
    except Exception as e:
        print(f"Couldn't generate HTML: {e}")


if joined == True:
    generate_html_file("index_joined", 0)
else:
    for i, c in enumerate(page_contents):
        generate_html_file("index_"+str(i + 1), i+1)
