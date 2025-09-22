from jinja2 import Template, Environment, FileSystemLoader

import os
import config
import parse_brief 
import parse_callsignini

briefing_location = os.path.join(config.bms_location, "User/Briefings/briefing.txt")
callsignini_location = os.path.join(config.bms_location, "User/Config", config.callsign + ".ini")

script_dir = os.path.dirname(__file__)
templates_dir = os.path.join(script_dir, 'templates')

def generate_html_file(name, brief_parts, page_num):
    try:
        with open(briefing_location, encoding = "latin1") as briefing_file:
            briefing_contents = briefing_file.readlines()
            brf = parse_brief.Briefing(briefing_contents)
        
            with open(callsignini_location, encoding = "latin1") as callsignini_file:
                callsignini_contents = callsignini_file.readlines()
                ci = parse_callsignini.Callsign_ini(callsignini_contents)

            env = Environment(loader=FileSystemLoader(templates_dir))
            index_tmpl = env.get_template("index.html")

        with open(os.path.join(script_dir, "output", name+".html"), "w") as index_output:
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
                                                 brief_parts = brief_parts,
                                                 cmds = ci.cmds,
                                                 num = page_num))
    except Exception as e:
        print(f"Couldn't generate HTML: {e}")


for i, c in enumerate(config.page_contents):
    generate_html_file("index_"+str(i + 1), c, i+1)
