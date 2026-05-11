import logging

from lib.cam.opencam.uni_wrappers import WAYPOINT_ACTION_NAMES

logger = logging.getLogger('html_brief_log')

def _line_key(line_contents = None):
    if line_contents == None:
        return ""
    return line_contents.split("=", 1)[0].strip()

def _line_values(line_contents = None):
    if line_contents == None or "=" not in line_contents:
        return []
    return [part.strip(" \n") for part in line_contents.split("=", 1)[1].split(",")]

def _line_index(line_contents = None, prefix = ""):
    key = _line_key(line_contents)
    if not key.startswith(prefix):
        return ""
    try:
        return int(key[len(prefix):])
    except Exception:
        return ""

def _line_value(line_contents = None, index = 0):
    values = _line_values(line_contents)
    if index < 0 or index >= len(values):
        return ""
    return values[index]

def _line_last_value(line_contents = None):
    values = _line_values(line_contents)
    if not values:
        return ""
    return values[-1]

class Callsign_ini:
    def __init__(self, file_contents = None):
        self.tgtsteerpoints = self.fill_tgtsteerpoints(file_contents)
        self.wpntgts = self.fill_wpntgts(file_contents)
        self.cmds = self.fill_cmds(file_contents)
        self.steerpoints = self.fill_steerpoints(file_contents)
        self.threat_steerpoints = self.fill_threat_steerpoints(file_contents)
        self.steerpoint_lines = self.fill_steerpoint_lines(file_contents)


    class Steerpoint:
        def __init__(self, line_contents = None):
            for attr in ["number", "action", "action_name", "coord_x", "coord_y", "coord_z"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(line_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        logger.warning(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, "")
                else:
                    logger.warning(f"No function to find {type(self).__name__}.{attr}")

        def init_number(self, line_contents):
            index = _line_index(line_contents, "target_")
            if index == "":
                return ""
            return index + 1

        def init_action(self, line_contents):
            value = _line_value(line_contents, 3)
            return value if value != "" else "Action"

        def init_action_name(self, line_contents):
            value = _line_value(line_contents, 3)
            try:
                action = int(value)
            except Exception:
                return value if value != "" else "Action"
            return WAYPOINT_ACTION_NAMES.get(action, str(action))

        def init_coord_x(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 0)

        def init_coord_y(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 1)

        def init_coord_z(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 2)

    def fill_steerpoints(self, file_contents = None):
        if file_contents == None:
            return []
        else:
            try:
                s = [l for l in file_contents if l.startswith("target_") and _line_last_value(l) == "Not set" and _line_value(l, 0) != "0.000000"]
                # we only take the steerpoints up to the first type "7" = landing? and then another "7" for alternate, hopefully
                path_end = next(i for i, l in enumerate(s) if _line_value(l, 3) == "7")
                alternate = next(i for i, l in enumerate(s[path_end + 1:]) if _line_value(l, 3) == "7")
                t = s[:path_end+1]
                t.append(s[path_end + 1 + alternate])
                return [self.Steerpoint(x) for x in t]
            except Exception as e:
                logger.warning(f"Error reading steerpoints: {e}")
                return []

    class TgtSteerpoint:
        def __init__(self, line_contents = None):
            for attr in ["number", "name", "coord_x", "coord_y", "coord_z"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(line_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        logger.warning(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, "")
                else:
                    logger.warning(f"No function to find {type(self).__name__}.{attr}")

        def init_number(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_index(line_contents, "target_") + 1

        def init_name(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.split(", ")[-1].strip(" \n")

        def init_coord_x(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 0)

        def init_coord_y(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 1)

        def init_coord_z(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 2)

    def fill_tgtsteerpoints(self, file_contents = None):
        if file_contents == None:
            return []
        else:
            try:
                s = [l for l in file_contents if l.startswith("target_") and _line_last_value(l) != "Not set"]
                return [self.TgtSteerpoint(x) for x in s]
            except Exception as e:
                logger.warning(f"Error reading target steerpoints: {e}")
                return []


    class WpnTgt:
        def __init__(self, line_contents = None):
            for attr in ["number", "name", "coord_x", "coord_y", "coord_z"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(line_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        logger.warning(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, "")
                else:
                    logger.warning(f"No function to find {type(self).__name__}.{attr}")

        def init_number(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_index(line_contents, "wpntarget_") + 1

        def init_name(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.split(", ")[-1].strip(" \n")

        def init_coord_x(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 0)

        def init_coord_y(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 1)

        def init_coord_z(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 2)


    def fill_wpntgts(self, file_contents = None):
        if file_contents == None:
            return []
        else:
            try:
                s = [l for l in file_contents if l.startswith("wpntarget_") and _line_last_value(l) != "Not set"]
                return [self.WpnTgt(x) for x in s]
            except Exception as e:
                logger.warning(f"Error reading weapon target steerpoints: {e}")
                return []

    class ThreatSteerpoint:
        def __init__(self, line_contents = None):
            for attr in ["number", "name", "coord_x", "coord_y", "coord_z", "radius"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(line_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        logger.warning(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, "")
                else:
                    logger.warning(f"No function to find {type(self).__name__}.{attr}")

        def init_number(self, line_contents):
            index = _line_index(line_contents, "ppt_")
            if index == "":
                return ""
            return 56 + index

        def init_name(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.split(", ")[-1].strip(" \n")

        def init_coord_x(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 0)

        def init_coord_y(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 1)

        def init_coord_z(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 2)

        def init_radius(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 3)

    def fill_threat_steerpoints(self, file_contents = None):
        if file_contents == None:
            return []
        else:
            try:
                s = [l for l in file_contents if l.startswith("ppt_") and _line_value(l, 0) != "0.000000"]
                return [self.ThreatSteerpoint(x) for x in s]
            except Exception as e:
                logger.warning(f"Error reading threat steerpoints: {e}")
                return []
    
    class SteerpointLinePoint:
        def __init__(self, line_contents = None):
            for attr in ["coord_x", "coord_y", "coord_z"]:
                init_func = getattr(self, f'init_{attr}', None)
                if callable(init_func):
                    try:
                        value = init_func(line_contents)
                        setattr(self, attr, value)
                    except Exception as e:
                        logger.warning(f"Error finding {type(self).__name__}.{attr}: {e}")
                        setattr(self, attr, "")
                else:
                    logger.warning(f"No function to find {type(self).__name__}.{attr}")

        def init_coord_x(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 0)

        def init_coord_y(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 1)

        def init_coord_z(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return _line_value(line_contents, 2)


    def fill_steerpoint_lines(self, file_contents = None):
        if file_contents == None:
            return []
        else:
            try:
                s = []
                r = []
                for i in range(4):
                    s.append([])
                    r.append([])
                    line_points = [l for l in file_contents if l.startswith("lineSTPT_")]
                    s[i] = [l for l in line_points[6*i:6*i+6] if _line_value(l, 0) != "0.000000"]
                    r[i] = [self.SteerpointLinePoint(x) for x in s[i]]
                return r
            except Exception as e:
                logger.warning(f"Error reading threat steerpoints: {e}")
                return []

    def fill_cmds(self, file_contents = None):
        if file_contents == None:
            return []
        else:
            prgrms = [{} for i in range(6)]
            try:
                s = [l.strip("\n") for l in file_contents if l.startswith("PGM") and l.split(" ")[2].split("=")[0] != "Comment"]
                for l in s:
                    sl = l.split(" ")
                    val = sl[-1].split("=")[-1]
                    tp = sl[2][0] + sl[-1].split("=")[-2]
                    prgrms[int(sl[1])][tp] = val
                return prgrms
            except Exception as e:
                logger.warning(f"Error reading CMDS: {e}")
                return prgrms
