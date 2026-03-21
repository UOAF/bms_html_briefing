from jinja2 import Environment, FileSystemLoader
import os, sys, shutil, logging, filecmp
from typing import Any
from PIL import Image

from lib.parsers.parse_briefing_txt import Briefing
from lib.parsers.parse_callsign_ini import Callsign_ini

logger = logging.getLogger('html_brief_log')
logger_ui = logging.getLogger('ui_logger')

CAM_SUPPORT_CELL_IDS = [
    "package_1", "package_2", "package_3", "package_4", "package_5", "package_6", "package_7", "package_30",
    "package_8", "package_9", "package_10", "package_11", "package_12", "package_13", "package_14", "package_31",
    "package_15", "package_16", "package_17", "package_18", "package_19", "package_21", "package_22", "package_32",
    "package_23", "package_24", "package_25", "package_26", "package_27", "package_28", "package_29", "package_33",
    "package_34", "package_35", "package_36", "package_37", "package_38", "package_39", "package_40", "package_41",
]
CAM_SUPPORT_COLS = 8
CAM_SUPPORT_MAX_ROWS = len(CAM_SUPPORT_CELL_IDS) // CAM_SUPPORT_COLS

def page_contents_ini_to_list(conf):
    return [[s.strip(' \n') for s in value.split(',') if s != ''] for key, value in conf['pages'].items()]

def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _cam_mission_name(entity: Any) -> str:
    if not isinstance(entity, dict):
        return ""
    tasking = entity.get("tasking")
    if not isinstance(tasking, dict):
        return ""
    for key in ("mission_name", "old_mission_name"):
        value = tasking.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text and text.upper() != "NONE":
                return text
    return ""


def _format_cam_time(value_ms: Any) -> str:
    if not isinstance(value_ms, int) or value_ms < 0:
        return ""
    total_seconds = value_ms // 1000
    hours = (total_seconds // 3600) % 24
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}z"


def _format_cam_aircraft(flight: Any) -> str:
    if not isinstance(flight, dict):
        return ""
    aircraft = flight.get("aircraft")
    if not isinstance(aircraft, str):
        return ""
    aircraft = aircraft.strip()
    if not aircraft:
        return ""
    if aircraft[:1].isdigit():
        return aircraft
    for key in ("aircraft_count", "aircraft_num", "flight_size", "num_aircraft"):
        count = _as_int(flight.get(key))
        if isinstance(count, int) and count > 0:
            return f"{count} {aircraft}"
    return aircraft


def _blank_support_rows() -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = []
    for row_idx in range(CAM_SUPPORT_MAX_ROWS):
        row: list[dict[str, str]] = []
        for col_idx in range(CAM_SUPPORT_COLS):
            cell_index = row_idx * CAM_SUPPORT_COLS + col_idx
            row.append({"id": CAM_SUPPORT_CELL_IDS[cell_index], "value": ""})
        rows.append(row)
    return rows


def _build_cam_template_context(
    cam_summary: dict[str, Any] | None,
    selected_package_index: int | None,
) -> dict[str, Any]:
    empty_context = {
        "cam_package_options": [],
        "cam_support_package_rows": _blank_support_rows(),
        "cam_main_package_l16": {},
        "cam_bullseye": {"lat": None, "lng": None},
    }
    if not isinstance(cam_summary, dict):
        return empty_context

    packages_raw = cam_summary.get("packages")
    packages = [pkg for pkg in packages_raw if isinstance(pkg, dict)] if isinstance(packages_raw, list) else []

    selected_index = selected_package_index if isinstance(selected_package_index, int) else None
    if packages and (selected_index is None or selected_index < 0 or selected_index >= len(packages)):
        selected_index = 0

    package_options: list[dict[str, Any]] = []
    for idx, pkg in enumerate(packages):
        package_number = _as_int(pkg.get("package_number"))
        label = f"#{idx + 1}" if package_number is None else str(package_number)
        mission_name = _cam_mission_name(pkg)
        if mission_name:
            label = f"{label} ({mission_name})"
        search_parts = [label]
        if package_number is not None:
            search_parts.append(str(package_number))
        flights = pkg.get("flights")
        if isinstance(flights, list):
            for flight in flights:
                mission_text = _cam_mission_name(flight)
                if mission_text:
                    search_parts.append(mission_text)
        package_options.append(
            {
                "index": idx,
                "label": label,
                "search_text": " ".join(part.strip().lower() for part in search_parts if isinstance(part, str) and part.strip()),
                "selected": idx == selected_index,
            }
        )

    support_rows = _blank_support_rows()
    if selected_index is not None and 0 <= selected_index < len(packages):
        selected_package = packages[selected_index]
        flights = selected_package.get("flights")
        row_values: list[list[str]] = []
        if isinstance(flights, list):
            for flight in flights[:CAM_SUPPORT_MAX_ROWS]:
                timing = flight.get("timing") if isinstance(flight.get("timing"), dict) else {}
                row_values.append(
                    [
                        flight.get("callsign").strip() if isinstance(flight.get("callsign"), str) else "",
                        str(flight["flight_number"]) if isinstance(flight.get("flight_number"), int) else "",
                        _cam_mission_name(flight),
                        _format_cam_aircraft(flight),
                        _format_cam_time(timing.get("takeoff_time_ms")),
                        _format_cam_time(timing.get("push_time_ms")),
                        _format_cam_time(timing.get("time_on_target_ms")),
                        flight.get("l16").strip() if isinstance(flight.get("l16"), str) else "",
                    ]
                )
        if not row_values:
            timing = selected_package.get("timing") if isinstance(selected_package.get("timing"), dict) else {}
            row_values.append(
                [
                    "",
                    str(selected_package["package_number"]) if isinstance(selected_package.get("package_number"), int) else "",
                    _cam_mission_name(selected_package),
                    "",
                    _format_cam_time(timing.get("takeoff_time_ms")),
                    _format_cam_time(timing.get("push_time_ms")),
                    _format_cam_time(timing.get("time_on_target_ms")),
                    "",
                ]
            )
        while len(row_values) < CAM_SUPPORT_MAX_ROWS:
            row_values.append([""] * CAM_SUPPORT_COLS)
        support_rows = []
        for row_idx, values in enumerate(row_values[:CAM_SUPPORT_MAX_ROWS]):
            row: list[dict[str, str]] = []
            for col_idx in range(CAM_SUPPORT_COLS):
                cell_index = row_idx * CAM_SUPPORT_COLS + col_idx
                row.append(
                    {
                        "id": CAM_SUPPORT_CELL_IDS[cell_index],
                        "value": values[col_idx] if col_idx < len(values) and isinstance(values[col_idx], str) else "",
                    }
                )
            support_rows.append(row)

    main_package_l16: dict[str, str] = {}
    for pkg in packages:
        flights = pkg.get("flights")
        if not isinstance(flights, list):
            continue
        for flight in flights:
            if not isinstance(flight, dict):
                continue
            flight_number = _as_int(flight.get("flight_number"))
            l16 = flight.get("l16")
            if flight_number is None or not isinstance(l16, str):
                continue
            l16_text = l16.strip()
            if l16_text:
                main_package_l16[str(flight_number)] = l16_text

    bullseye = cam_summary.get("bullseye") if isinstance(cam_summary.get("bullseye"), dict) else {}
    lat = bullseye.get("map_lat")
    lng = bullseye.get("map_lng")

    return {
        "cam_package_options": package_options,
        "cam_support_package_rows": support_rows,
        "cam_main_package_l16": main_package_l16,
        "cam_bullseye": {
            "lat": lat if isinstance(lat, (int, float)) else None,
            "lng": lng if isinstance(lng, (int, float)) else None,
        },
    }


def generate_html_file(conf, bms_conf, name, page_num = 0, cam_summary = None, cam_package_index = None):
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
        cam_context = _build_cam_template_context(cam_summary, cam_package_index)

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
                                                 brief_is_joined = True,
                                                 cam_package_options = cam_context["cam_package_options"],
                                                 cam_support_package_rows = cam_context["cam_support_package_rows"],
                                                 cam_main_package_l16 = cam_context["cam_main_package_l16"],
                                                 cam_bullseye = cam_context["cam_bullseye"],
                                                 ))
    except Exception as e:
        logger.error(f"Couldn't generate HTML: {e}")
