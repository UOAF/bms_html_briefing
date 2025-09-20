from jinja2 import Template, Environment, FileSystemLoader

import config
import parse_brief 


try:
    with open(config.briefing_location, encoding = "latin1") as briefing_file:
        briefing_contents = briefing_file.readlines()
        brf = parse_brief.Briefing(briefing_contents)
        env = Environment(loader=FileSystemLoader("templates"))
        
        index_left_tmpl = env.get_template("index_left.html")
        index_right_tmpl = env.get_template("index_right.html")
        
        with open("index_left.html", "w") as index_left_output:
            index_left_output.write(index_left_tmpl.render(airbases = brf.airbases,
                                                       package_size = len(brf.package),
                                                       overview = brf.overview,
                                                       package = brf.package,
                                                       steerpoints = brf.steerpoints,
                                                       own_flight = brf.own_flight,
                                                       support = brf.support))
            
            with open("index_right.html", "w") as index_right_output:
                index_right_output.write(index_right_tmpl.render(airbases = brf.airbases,
                                                             package_size = len(brf.package),
                                                             overview = brf.overview,
                                                             package = brf.package,
                                                             steerpoints = brf.steerpoints,
                                                             own_flight = brf.own_flight,
                                                             support = brf.support))
except Exception as e:
    print(f"Couldn't generate HTML: {e}")


