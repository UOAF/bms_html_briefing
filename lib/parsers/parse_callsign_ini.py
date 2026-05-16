import logging
import re
from decimal import Decimal, InvalidOperation

from lib.cam.opencam.uni_wrappers import WAYPOINT_ACTION_NAMES

logger = logging.getLogger('html_brief_log')

_NUMERIC_VALUE_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")

def _line_key(line_contents = None):
    if line_contents == None:
        return ""
    return line_contents.split("=", 1)[0].strip()

def _line_values(line_contents = None):
    if line_contents == None or "=" not in line_contents:
        return []
    return [part.strip() for part in line_contents.split("=", 1)[1].split(",")]

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

def _target_index(line_contents = None):
    return _line_index(line_contents, "target_")

def _is_flight_path_target(line_contents = None):
    index = _target_index(line_contents)
    return isinstance(index, int) and 0 <= index <= 23

def _is_zeroed_steerpoint(line_contents = None):
    try:
        return all(float(_line_value(line_contents, index)) == 0 for index in range(3))
    except Exception:
        return False

def _section_name(line_contents = None):
    if line_contents == None:
        return ""
    line = line_contents.strip()
    if not line.startswith("[") or not line.endswith("]"):
        return ""
    return line[1:-1].strip()

def _section_lines(file_contents = None, section_name = ""):
    if file_contents == None:
        return []
    section_name = section_name.lower()
    in_section = False
    lines = []
    for line in file_contents:
        current_section = _section_name(line).lower()
        if current_section:
            if in_section:
                break
            in_section = current_section == section_name
            continue
        if in_section:
            lines.append(line)
    return lines

def _clean_offset_value(value = None):
    if value == None:
        return ""
    return str(value).strip()

def _canonical_numeric_value(value = None):
    clean_value = _clean_offset_value(value)
    if not _NUMERIC_VALUE_RE.fullmatch(clean_value):
        return clean_value
    try:
        number = Decimal(clean_value)
    except InvalidOperation:
        return clean_value
    if number == number.to_integral_value():
        return str(number.to_integral_value())
    return format(number.normalize(), "f")

def _offset_is_zero(row = None):
    if not isinstance(row, dict):
        return True
    for key in ("brg", "rng", "elev"):
        value = _clean_offset_value(row.get(key))
        if value == "":
            continue
        try:
            if float(value) != 0:
                return False
        except Exception:
            return False
    return True

def _offset_sort_key(value):
    try:
        return (0, int(value))
    except Exception:
        return (1, str(value))

def _nav_offset_row(brg = "", rng = "", elev = "", stpt = None):
    row = {
        "brg": _clean_offset_value(brg),
        "rng": _clean_offset_value(rng),
        "elev": _clean_offset_value(elev),
    }
    if stpt != None:
        row["stpt"] = _clean_offset_value(stpt)
    return row

def _normalized_modesel(value = None):
    value = _clean_offset_value(value).lower()
    if value not in ("none", "vip", "vrp"):
        return "none"
    return value

def _normalized_nav_offsets(nav_offsets = None):
    if not isinstance(nav_offsets, dict):
        nav_offsets = {}
    normalized = {
        "modesel": _normalized_modesel(nav_offsets.get("modesel")),
        "vip": None,
        "vippup": None,
        "vrp": None,
        "vrppup": None,
        "oa": {},
    }
    for key in ("vip", "vippup", "vrp", "vrppup"):
        row = nav_offsets.get(key)
        if not isinstance(row, dict):
            continue
        stpt = _clean_offset_value(row.get("stpt"))
        normalized[key] = _nav_offset_row(row.get("brg"), row.get("rng"), row.get("elev"), stpt)

    oa = nav_offsets.get("oa")
    if isinstance(oa, dict):
        for stpt, rows in oa.items():
            stpt_key = _clean_offset_value(stpt)
            if stpt_key == "" or not isinstance(rows, dict):
                continue
            normalized["oa"].setdefault(stpt_key, {})
            for row_key in ("oa1", "oa2"):
                row = rows.get(row_key)
                if not isinstance(row, dict):
                    continue
                normalized["oa"][stpt_key][row_key] = _nav_offset_row(row.get("brg"), row.get("rng"), row.get("elev"))
            if not normalized["oa"][stpt_key]:
                del normalized["oa"][stpt_key]
    return normalized

ICP_DEFAULTS = {
    "Manual Wingspan": "35",
    "Bingo_Fuel": "1500",
    "MasterMode": "0",
    "Alow AGL": "100",
    "Alow MSL": "10000",
    "Alow TFAdv": "400",
}

LASER_DEFAULTS = {
    "LaserST": "8",
    "LaserTGP": "1688",
    "LaserLST": "1688",
}

FCC_DEFAULTS = {
    "FCC_AIM": {
        "AIM-9_Spot/Scan": "0",
        "AIM-9_TD/BP": "0",
        "AIM120_TargetSize": "0",
    },
    "FCC_AGM": {
        "Maverick_AutoPwr": "0",
        "Maverick_AutoPwrDir": "1",
        "Maverick_AutoPwrWpt": "1",
    },
    "FCC_AGB": {
        "Profile1_Submode": "8",
        "Profile1_Fuze": "1",
        "Profile1_SGL/PAIR": "0",
        "Profile1_Release_Spacing": "175",
        "Profile1_Release_Pulse": "-1",
        "Profile1_Release_Angle": "45",
        "Profile1_C1_AD1": "400.000000",
        "Profile1_C1_AD2": "600.000000",
        "Profile1_C2_AD": "150.000000",
        "Profile1_C2_BA": "500",
        "Profile2_Submode": "7",
        "Profile2_Fuze": "1",
        "Profile2_SGL/PAIR": "0",
        "Profile2_Release_Spacing": "175",
        "Profile2_Release_Pulse": "-1",
        "Profile2_Release_Angle": "45",
        "Profile2_C1_AD1": "400.000000",
        "Profile2_C1_AD2": "600.000000",
        "Profile2_C2_AD": "150.000000",
        "Profile2_C2_BA": "500",
    },
}

def _normalized_icp_settings(icp_settings = None):
    normalized = dict(ICP_DEFAULTS)
    if isinstance(icp_settings, dict):
        for key in ICP_DEFAULTS:
            value = icp_settings.get(key)
            if value != None:
                clean_value = _clean_offset_value(value)
                if _NUMERIC_VALUE_RE.fullmatch(clean_value):
                    normalized[key] = _canonical_numeric_value(clean_value)
    return normalized

def _normalized_fcc_settings(fcc_settings = None):
    normalized = {section: dict(values) for section, values in FCC_DEFAULTS.items()}
    if not isinstance(fcc_settings, dict):
        return normalized
    for section, defaults in FCC_DEFAULTS.items():
        section_values = fcc_settings.get(section)
        if not isinstance(section_values, dict):
            continue
        for key in defaults:
            value = section_values.get(key)
            if value == None:
                continue
            clean_value = _clean_offset_value(value)
            if _NUMERIC_VALUE_RE.fullmatch(clean_value):
                normalized[section][key] = clean_value
    return normalized

def _normalized_laser_settings(laser_settings = None):
    normalized = dict(LASER_DEFAULTS)
    if isinstance(laser_settings, dict):
        for key in LASER_DEFAULTS:
            value = laser_settings.get(key)
            if value == None:
                continue
            clean_value = _clean_offset_value(value)
            if _NUMERIC_VALUE_RE.fullmatch(clean_value):
                normalized[key] = _canonical_numeric_value(clean_value)
    return normalized

def build_nav_offsets_section(nav_offsets = None, newline = "\n"):
    nav_offsets = _normalized_nav_offsets(nav_offsets)
    lines = ["[NAV OFFSETS]" + newline, f"Modesel={nav_offsets['modesel']}" + newline]
    for key in ("vip", "vippup", "vrp", "vrppup"):
        row = nav_offsets.get(key)
        if not row or _offset_is_zero(row):
            continue
        stpt = _clean_offset_value(row.get("stpt"))
        if stpt == "":
            continue
        lines.append(f"{key.upper()}={stpt},{row['brg']},{row['rng']},{row['elev']}" + newline)
    for stpt in sorted(nav_offsets["oa"], key=_offset_sort_key):
        rows = nav_offsets["oa"][stpt]
        for row_key in ("oa1", "oa2"):
            row = rows.get(row_key)
            if not row or _offset_is_zero(row):
                continue
            lines.append(f"{row_key.upper()}-{stpt}={row['brg']},{row['rng']},{row['elev']}" + newline)
    return lines

def build_icp_section(icp_settings = None, newline = "\n"):
    icp_settings = _normalized_icp_settings(icp_settings)
    lines = ["[ICP]" + newline]
    for key in ICP_DEFAULTS:
        lines.append(f"{key}={icp_settings[key]}" + newline)
    return lines

def build_fcc_sections(fcc_settings = None, newline = "\n"):
    fcc_settings = _normalized_fcc_settings(fcc_settings)
    lines = []
    for section, defaults in FCC_DEFAULTS.items():
        lines.append(f"[{section}]" + newline)
        for key in defaults:
            lines.append(f"{key}={fcc_settings[section][key]}" + newline)
    return lines

def build_laser_section(laser_settings = None, newline = "\n"):
    laser_settings = _normalized_laser_settings(laser_settings)
    lines = ["[Laser]" + newline]
    for key in LASER_DEFAULTS:
        lines.append(f"{key}={laser_settings[key]}" + newline)
    return lines

def replace_nav_offsets_section(file_contents = None, nav_offsets = None):
    if file_contents == None:
        file_contents = []
    newline = "\r\n" if any(line.endswith("\r\n") for line in file_contents) else "\n"
    replacement = build_nav_offsets_section(nav_offsets, newline)
    start = None
    end = None
    for index, line in enumerate(file_contents):
        if _section_name(line).lower() != "nav offsets":
            continue
        start = index
        end = len(file_contents)
        for following_index in range(index + 1, len(file_contents)):
            if _section_name(file_contents[following_index]):
                end = following_index
                break
        break
    if start == None:
        output = list(file_contents)
        if output and output[-1].strip():
            output.append(newline)
        output.extend(replacement)
        return output
    return list(file_contents[:start]) + replacement + list(file_contents[end:])

def _replace_section(file_contents = None, section_name = "", replacement = None):
    if file_contents == None:
        file_contents = []
    if replacement == None:
        replacement = []
    newline = "\r\n" if any(line.endswith("\r\n") for line in file_contents) else "\n"
    start = None
    end = None
    for index, line in enumerate(file_contents):
        if _section_name(line).lower() != section_name.lower():
            continue
        start = index
        end = len(file_contents)
        for following_index in range(index + 1, len(file_contents)):
            if _section_name(file_contents[following_index]):
                end = following_index
                break
        break
    if start == None:
        output = list(file_contents)
        if output and output[-1].strip():
            output.append(newline)
        output.extend(replacement)
        return output
    return list(file_contents[:start]) + list(replacement) + list(file_contents[end:])

def replace_icp_section(file_contents = None, icp_settings = None):
    if file_contents == None:
        file_contents = []
    newline = "\r\n" if any(line.endswith("\r\n") for line in file_contents) else "\n"
    replacement = build_icp_section(icp_settings, newline)
    start = None
    end = None
    for index, line in enumerate(file_contents):
        if _section_name(line).lower() != "icp":
            continue
        start = index
        end = len(file_contents)
        for following_index in range(index + 1, len(file_contents)):
            if _section_name(file_contents[following_index]):
                end = following_index
                break
        break
    if start == None:
        output = list(file_contents)
        if output and output[-1].strip():
            output.append(newline)
        output.extend(replacement)
        return output
    return list(file_contents[:start]) + replacement + list(file_contents[end:])

def replace_fcc_sections(file_contents = None, fcc_settings = None):
    if file_contents == None:
        file_contents = []
    newline = "\r\n" if any(line.endswith("\r\n") for line in file_contents) else "\n"
    normalized = _normalized_fcc_settings(fcc_settings)
    requested_sections = [
        section for section in FCC_DEFAULTS
        if isinstance(fcc_settings, dict) and isinstance(fcc_settings.get(section), dict)
    ]
    if not requested_sections:
        requested_sections = list(FCC_DEFAULTS)
    output = list(file_contents)
    for section in requested_sections:
        defaults = FCC_DEFAULTS[section]
        replacement = [f"[{section}]" + newline]
        for key in defaults:
            replacement.append(f"{key}={normalized[section][key]}" + newline)
        output = _replace_section(output, section, replacement)
    return output

def replace_laser_section(file_contents = None, laser_settings = None):
    if file_contents == None:
        file_contents = []
    newline = "\r\n" if any(line.endswith("\r\n") for line in file_contents) else "\n"
    return _replace_section(file_contents, "Laser", build_laser_section(laser_settings, newline))

class Callsign_ini:
    def __init__(self, file_contents = None):
        self.tgtsteerpoints = self.fill_tgtsteerpoints(file_contents)
        self.wpntgts = self.fill_wpntgts(file_contents)
        self.cmds = self.fill_cmds(file_contents)
        self.steerpoints = self.fill_steerpoints(file_contents)
        self.threat_steerpoints = self.fill_threat_steerpoints(file_contents)
        self.steerpoint_lines = self.fill_steerpoint_lines(file_contents)
        self.nav_offsets = self.fill_nav_offsets(file_contents)
        self.icp_settings = self.fill_icp_settings(file_contents)
        self.fcc_settings = self.fill_fcc_settings(file_contents)
        self.laser_settings = self.fill_laser_settings(file_contents)


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
                s = [l for l in file_contents if l.startswith("target_") and _is_flight_path_target(l) and not _is_zeroed_steerpoint(l)]
                steerpoints = [self.Steerpoint(x) for x in s]
                for steerpoint in steerpoints:
                    steerpoint.is_alternate = False
                landing_indices = [i for i, steerpoint in enumerate(steerpoints) if steerpoint.action == "7"]
                if len(landing_indices) >= 2:
                    steerpoints[landing_indices[-1]].is_alternate = True
                return steerpoints
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
                s = [l for l in file_contents if l.startswith("target_") and not _is_flight_path_target(l) and _line_last_value(l) != "Not set" and not _is_zeroed_steerpoint(l)]
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
                s = [l for l in file_contents if l.startswith("wpntarget_") and _line_last_value(l) != "Not set" and not _is_zeroed_steerpoint(l)]
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
                s = [l for l in file_contents if l.startswith("ppt_") and not _is_zeroed_steerpoint(l)]
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
                    s[i] = [l for l in line_points[6*i:6*i+6] if not _is_zeroed_steerpoint(l)]
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

    def fill_nav_offsets(self, file_contents = None):
        nav_offsets = {
            "modesel": "none",
            "vip": None,
            "vippup": None,
            "vrp": None,
            "vrppup": None,
            "oa": {},
        }
        try:
            for line in _section_lines(file_contents, "NAV OFFSETS"):
                key = _line_key(line)
                values = _line_values(line)
                key_lower = key.lower()
                if key_lower == "modesel":
                    nav_offsets["modesel"] = _normalized_modesel(values[0] if values else None)
                elif key_lower in ("vip", "vippup", "vrp", "vrppup") and len(values) >= 4:
                    nav_offsets[key_lower] = _nav_offset_row(values[1], values[2], values[3], values[0])
                elif key_lower.startswith("oa1-") or key_lower.startswith("oa2-"):
                    row_key, stpt = key_lower.split("-", 1)
                    if len(values) >= 3 and stpt:
                        nav_offsets["oa"].setdefault(stpt, {})
                        nav_offsets["oa"][stpt][row_key] = _nav_offset_row(values[0], values[1], values[2])
            return nav_offsets
        except Exception as e:
            logger.warning(f"Error reading NAV OFFSETS: {e}")
            return nav_offsets

    def fill_icp_settings(self, file_contents = None):
        icp_settings = dict(ICP_DEFAULTS)
        try:
            for line in _section_lines(file_contents, "ICP"):
                key = _line_key(line)
                if key in ICP_DEFAULTS:
                    value = _line_value(line, 0)
                    icp_settings[key] = _canonical_numeric_value(value) if _NUMERIC_VALUE_RE.fullmatch(value) else value
            return icp_settings
        except Exception as e:
            logger.warning(f"Error reading ICP: {e}")
            return icp_settings

    def fill_fcc_settings(self, file_contents = None):
        fcc_settings = {section: dict(values) for section, values in FCC_DEFAULTS.items()}
        try:
            for section, defaults in FCC_DEFAULTS.items():
                for line in _section_lines(file_contents, section):
                    key = _line_key(line)
                    if key in defaults:
                        fcc_settings[section][key] = _line_value(line, 0)
            return fcc_settings
        except Exception as e:
            logger.warning(f"Error reading FCC: {e}")
            return fcc_settings

    def fill_laser_settings(self, file_contents = None):
        laser_settings = dict(LASER_DEFAULTS)
        try:
            for line in _section_lines(file_contents, "Laser"):
                key = _line_key(line)
                if key in LASER_DEFAULTS:
                    laser_settings[key] = _line_value(line, 0)
            return laser_settings
        except Exception as e:
            logger.warning(f"Error reading Laser: {e}")
            return laser_settings
