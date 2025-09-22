class Briefing:
    def __init__(self, file_contents = None):
        self.overview = self.Overview(file_contents)
        self.situation = self.Situation(file_contents)
        self.weather = self.Weather(file_contents)
        self.roe = self.init_roe(file_contents)
        self.package = self.fill_package(self, file_contents)
        self.threat = self.Threat(file_contents)
        self.steerpoints = self.fill_steerpoints(file_contents)
        self.comm = self.fill_comms(file_contents)
        self.airbases = self.fill_airbases(self)
        self.support = self.fill_support(file_contents)

    class Overview:
        def __init__(self, file_contents = None):
            for attr in ["callsign", "mission_type", "package_id", "package_description", "package_mission", "target_area", "time_on_target", "sunrise", "sunset"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(file_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        print(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, "")
                else:
                    print(f"No function to find {type(self).__name__}.{attr}")

        def init_callsign(self, file_contents):
            if file_contents == None:
                return ""
            else:
                s = file_contents[4].strip("\n")
                return s.strip("\t").split()[0]
               
        def init_mission_type(self, file_contents):
            if file_contents == None:
                return ""
            else:
                s = file_contents[4].strip("\n")
                return s.strip("\t").split()[1].strip(")(")

        def init_package_id(self, file_contents):
            if file_contents == None:
                return ""
            else:
                s = next(l for l in file_contents if l.strip("\t\n)").startswith("Package"))
                return ''.join([n for n in s if n.isdigit()])

        def init_package_description(self, file_contents):
            if file_contents == None:
                return ""
            else:
                s = next(l for l in file_contents if l.strip("\t\n)").startswith("Package"))
                return s[s.find("("):].strip("() \n")

        def init_package_mission(self, file_contents):
            if file_contents == None:
                return ""
            else:
                s = next(l for l in file_contents if l.strip("\t\n)").startswith("Pkg-Mission"))
                return s[s.find(":"):].strip(": \t \n")

        def init_target_area(self, file_contents):
            if file_contents == None:
                return ""
            else:
                s = next(l for l in file_contents if l.strip("\t\n)").startswith("Target Area"))
                return s[s.find(":"):].strip(": \t \n")

        def init_time_on_target(self, file_contents):
            if file_contents == None:
                return ""
            else:
                s = next(l for l in file_contents if l.strip("\t\n)").startswith("Time on Target"))
                return  s[s.find(":"):].strip(": \t \n")

        def init_sunrise(self, file_contents):
            if file_contents == None:
                return ""
            else:
                s = next(l for l in file_contents if l.strip("\t \n)").startswith("Sunrise"))
                return s[s.find(":"):].strip(": \t \n")

        def init_sunset(self, file_contents):
            if file_contents == None:
                return ""
            else:
                s = next(l for l in file_contents if l.strip("\t \n) ").startswith("Sunset"))
                return s[s.find(":"):].strip(": \t \n")

    class Situation:
        def __init__(self, file_contents = None):
            for attr in ["sitrep"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(file_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        print(f"Error finding \'{attr}\': {e}")
                        setattr(self, attr, "")
                else:
                    print(f"No function to find {type(self).__name__}.{attr}")

        def init_sitrep(self, file_contents):
            if file_contents == None:
                return ""
            else:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Situation"))
                end = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Pilot Roster"))
                s = file_contents[start+1:end]
                return ''.join(s).strip("\t\n").replace("\t","")

    class PilotRoster:
        def __init__(self, brf = None, line_contents = None):
            for attr in ["callsign", "lead", "wing", "element", "four"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(line_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        print(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, "")
                else:
                    print(f"No function to find {type(self).__name__}.{attr}")

            for attr in ["own"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(brf, line_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        print(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, False)
                else:
                    print(f"No function to find {type(self).__name__}.{attr}")

        def init_callsign(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[0]

        def init_lead(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[1].strip(" \n")

        def init_wing(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[2].strip(" \n")
            
        def init_element(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[3].strip(" \n")
            
        def init_four(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[4].strip(" \n")

        def init_own(self, brf, line_contents):
            if line_contents == None:
                return False
            else:
                return self.callsign == brf.overview.callsign

    def fill_roster(self, brf = None, file_contents = None):
        if file_contents == None:
            return []
        else:
            try:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Pilot Roster"))
                end = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Package Elements"))

                name_list = file_contents[start+4:end-1]
                s = [self.PilotRoster(brf, x) for x in name_list]
                return s
            except Exception as e:
                print(f"Error reading roster: {e}")
                return []

    class PackageElement:
        roster = [],
        def __init__(self, brf = None, line_contents = None):
            for attr in ["callsign", "flight", "role", "aircraft", "task", "takeoff", "push", "tot", "iff"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(brf, line_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        print(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, "")
                else:
                    print(f"No function to find {type(self).__name__}.{attr}")
            for attr in ["primary"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(brf, line_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        print(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, False)
                else:
                    print(f"No function to find {type(self).__name__}.{attr}")
        
        def init_callsign(self, brf, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents[0].strip("\t").split("\t")[0]

        def init_takeoff(self, brf, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents[1].strip("\t").split("\t")[1].split(": ")[1]

        def init_flight(self, brf, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents[0].strip("\t").split("\t")[1].strip("(x )")

        def init_push(self, brf, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents[1].strip("\t").split("\t")[2].split(": ")[1]

        def init_role(self, brf, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents[0].strip("\t").split("\t")[2]

        def init_tot(self, brf, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents[1].strip("\t").split("\t")[3].split(": ")[1]
            
        def init_aircraft(self, brf, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents[0].strip("\t").split("\t")[3]

        def init_iff(self, brf, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents[1].strip("\t").split("\t")[4]
            
        def init_task(self, brf, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents[0].strip("\t").split("\t")[4]

        def init_primary(self, brf, line_contents):
            if line_contents == None:
                return False
            else:
                return line_contents[0].strip("\t").split("\t")[1].strip(" ").endswith("(x )")

    def get_weapon_list(self, clsgn, file_contents):
        s = [[],[],[],[]]
        try:
            start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Ordnance"))
            end = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Weather"))
        
            weapon_list = file_contents[start:end]
            
            start = next(i for i, l in enumerate(weapon_list) if l.strip("\t \n").startswith(clsgn))
            end = next(i + start for i, l in enumerate(weapon_list[start:]) if l.strip("\t \n) ") == '')

            fl_weapon_list = weapon_list[start:end]

            for i in range(1, len(fl_weapon_list)):
                for j in range(4):
                    s[j].append(fl_weapon_list[i].strip("\t \n").split("\t")[j])

        except Exception as e:
            print(f"Error reading weapon list for {clsgn}: {e}")
        return s

    def fill_package(self, brf, file_contents = None):
        if file_contents == None:
            return []
        else:
            try:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Package Elements"))
                end = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Threat Analysis"))
                s = file_contents[start+4:end-1]
                pe = [self.PackageElement(brf, (s[2*i],s[2*i+1])) for i in range(int(len(s)/2))]
                rstr = brf.fill_roster(brf, file_contents)
                for i in range(len(pe)):
                    pe[i].roster = rstr[i]
                    pe[i].weapons = self.get_weapon_list(pe[i].callsign, file_contents)
                    if pe[i].roster.own:
                        brf.own_flight = pe[i]
                return pe
            except Exception as e:
                print(f"Error reading package: {e}")
                return []


    class Threat:
        def __init__(self, file_contents = None):
            for attr in ["threat"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(file_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        print(f"Error finding \'{attr}\': {e}")
                        setattr(self, attr, "")
                else:
                    print(f"No function to find {type(self).__name__}.{attr}")

        def init_threat(self, file_contents):
            if file_contents == None:
                return ""
            else:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Threat Analysis"))
                end = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Steerpoints"))
                s = file_contents[start+1:end]
                return ''.join(s).strip("\t\n").replace("\t","")

    class Steerpoint:
        def __init__(self, line_contents = None):
            for attr in ["number", "description", "time", "distance", "heading", "cas", "altitude", "action", "form", "comment"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(line_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        print(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, "")
                else:
                    print(f"No function to find {type(self).__name__}.{attr}")

        def init_number(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[0]

        def init_description(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[1]

        def init_time(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[2]

        def init_distance(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[4]

        def init_heading(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[6]

        def init_cas(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[8]

        def init_altitude(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[10]

        def init_action(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[11]

        def init_form(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[12]

        def init_comment(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[13].strip("\n")


    def fill_steerpoints(self, file_contents = None):
        if file_contents == None:
            return []
        else:
            try:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Steerpoints"))
                end = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Comm Ladder"))
                s = file_contents[start+4:end-1]
                return [self.Steerpoint(x) for x in s]
            except Exception as e:
                print(f"Error reading steerpoints: {e}")
                return []


    class Comm:
        def __init__(self, line_contents = None):
            for attr in ["agency", "callsign", "uhf", "vhf", "notes"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(line_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        print(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, "")
                else:
                    print(f"No function to find {type(self).__name__}.{attr}")

        def init_agency(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[0].strip(":")

        def init_callsign(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[1]

        def init_uhf(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[2]

        def init_vhf(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[3]

        def init_notes(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[4]

    def fill_comms(self, file_contents = None):
        if file_contents == None:
            return []
        else:
            try:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Comm Ladder"))
                end = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Iff"))
                s = list(filter(lambda l: l != "", [x.strip(" \n ") for x in file_contents[start+4:end-1]]))
                return [self.Comm(x) for x in s]
            except Exception as e:
                print(f"Error reading comms: {e}")
                return []


        
    class Airbase:
        def __init__(self, brf = None, agncy = None):
            for attr in ["tcn", "ground", "approach", "ils", "agency"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(brf, agncy)
                        setattr(self, attr, value)
                    except Exception as e:
                        print(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, "")
                else:
                    print(f"No function to find {type(self).__name__}.{attr}")

        def init_tcn(self, brf, agncy):
            return ""

        def init_ground(self, brf, agncy):
            for x in brf.comm:
                if x.agency == agncy + " Ground":
                    return x.uhf
            return ""

        def init_approach(self, brf, agncy):
            for x in brf.comm:
                if x.agency == agncy + " Departure" or x.agency == agncy + " Approach":
                    return x.uhf
            return ""
            
        def init_ils(self, brf, agncy):
            return ""

        def init_agency(self, brf, agncy):
            for x in brf.comm:
                if x.agency == agncy + " Tower":
                    return x.callsign.split(" ")[0]
            return ""

    def fill_airbases(self, brf = None):
            return [self.Airbase(self, agncy) for agncy in ["Dep", "Arr", "Alt"]]

    class Support:
        def __init__(self, line_contents = None):
            for attr in ["callsign", "type", "comment"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(line_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        print(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, "")
                else:
                    print(f"No function to find {type(self).__name__}.{attr}")

        def init_callsign(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[0]

        def init_type(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[1]

        def init_comment(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.strip("\t").split("\t")[2]

    def fill_support(self, file_contents = None):
        if file_contents == None:
            return []
        else:
            try:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Support"))
                end = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Rules of Engagement"))
                s = list(filter(lambda l: l != "", [x.strip(" \n ") for x in file_contents[start+4:end-1]]))
                return [self.Support(x) for x in s]
            except Exception as e:
                print(f"Error reading support: {e}")
                return []

    class Weather:
        def __init__(self, file_contents = None):
            for attr in ["sit", "wind", "vis", "temp", "cloud", "con"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(file_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        print(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, "")
                else:
                    print(f"No function to find {type(self).__name__}.{attr}")

        def init_sit(self, file_contents):
            if file_contents == None:
                return ""
            else:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Weather"))
                return file_contents[start + 4].strip("\t \n").split("\t")[1:4]

        def init_wind(self, file_contents):
            if file_contents == None:
                return ""
            else:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Weather"))
                return file_contents[start + 5].strip("\t \n").split("\t")[1:4]

        def init_vis(self, file_contents):
            if file_contents == None:
                return ""
            else:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Weather"))
                return file_contents[start + 6].strip("\t \n").split("\t")[1:4]

        def init_temp(self, file_contents):
            if file_contents == None:
                return ""
            else:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Weather"))
                return file_contents[start + 7].strip("\t \n").split("\t")[1:4]

        def init_cloud(self, file_contents):
            if file_contents == None:
                return ""
            else:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Weather"))
                return file_contents[start + 8].strip("\t \n").split("\t")[1:4]

        def init_con(self, file_contents):
            if file_contents == None:
                return ""
            else:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Weather"))
                return file_contents[start + 9].strip("\t \n").split("\t")[1:4]
           
    def init_roe(self, file_contents):
        if file_contents == None:
            return ""
        else:
            try:
                start = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Rules of Engagement"))
                end = next(i for i, l in enumerate(file_contents) if l.strip("\t \n) ").startswith("Emergency"))
                s = file_contents[start+1:end]
                return ''.join(s).strip("\t\n").replace("\t","")
            except Exception as e:
                print(f"Error reading ROE: {e}")
                return ""
