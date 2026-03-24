import os, sys, logging, configparser
from lib.theater_paths import read_theater_center, resolve_target_folder_from_theater

logger = logging.getLogger('html_brief_log')
logger_ui = logging.getLogger('ui_logger')

class BmsConfig:
    callsign = ""
    base_dir = ""
    theater = ""
    theater_config = None
    target_folder_failed = False
    kto_target_folder = ""
    theater_center_latitude = None
    theater_center_longitude = None
    theater_center_source = ""

    def __init__(self, cfg, theater_ini_pattern = None):
        version = cfg['bms']['bms_version']
        self.version = version
        if sys.platform == 'linux':
            try:
                wine_prefix = cfg['system']['wine_prefix']
                with open(os.path.join(wine_prefix, "system.reg"), "r") as reg_file:
                    reg_file_contents = reg_file.readlines()
                entry_start = next(i for i,l in enumerate(reg_file_contents) if l.startswith("[Software\\\\Wow6432Node\\\\Benchmark Sims\\\\Falcon BMS " + version + "]"))
                base_dir_win = next(l for l in reg_file_contents[entry_start:] if l.strip('\"').startswith("baseDir")).split('=')[1].strip('\"\n')
                callsign_reg = next(l for l in reg_file_contents[entry_start:] if l.strip('\"').startswith("PilotCallsign")).split('=')[1].strip('\"\n')
                self.callsign = ''.join([chr(int(c, 16)) for c in callsign_reg.split(':')[-1].split(',')]).strip('\x00')
                self.base_dir = os.path.join(wine_prefix, "drive_" + base_dir_win.split(":\\")[0].lower(), *base_dir_win.split("\\")[1:])
                self.theater = next(l for l in reg_file_contents[entry_start:] if l.strip('\"').startswith("curTheater")).split('=')[1].strip('\"\n')
            except Exception as e:
                logger.error(e)


        if sys.platform == 'win32' or sys.platform == 'cygwin':
            import winreg
            baseSubKey = r"SOFTWARE\WOW6432Node\Benchmark Sims\Falcon BMS " + version + r"\\"
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, baseSubKey) as keyHandle:
                    callsign_reg = winreg.QueryValueEx(keyHandle, "PilotCallsign")[0]
                    self.base_dir = winreg.QueryValueEx(keyHandle, "baseDir")[0]
                    self.theater = winreg.QueryValueEx(keyHandle, "curTheater")[0]
                self.callsign = callsign_reg.decode('utf-8').strip('\x00 \n')
            except Exception as e:
                logger.error(e)
        
        if cfg.has_option('override', 'callsign'):
            self.callsign = cfg['override']['callsign']

        if cfg.has_option('override', 'base_dir'):
            self.base_dir = cfg['override']['base_dir']

        if cfg.has_option('override', 'theater'):
            self.theater = cfg['override']['theater']

        self.kto_target_folder = os.path.join(self.base_dir, 'Data', 'TerrData', 'Objects', 'KoreaObj')
        self.theater_center_latitude = None
        self.theater_center_longitude = None
        self.theater_center_source = ""

        if getattr(sys, 'frozen', False):
            script_dir = os.path.dirname(sys.executable)
        else:
            script_dir = os.environ.get("BMS_BRIEF_HOME", os.path.dirname(sys.argv[0]))
        script_dir = os.path.abspath(script_dir)
        self.script_dir = script_dir

        # Resolve theater config path:
        # - default: theaters_<version>.ini
        # - override: user-provided pattern, optionally containing {version}
        if theater_ini_pattern:
            try:
                theater_ini_path = theater_ini_pattern.format(version=version)
            except Exception:
                theater_ini_path = theater_ini_pattern
            self.theater_ini_path = os.path.abspath(theater_ini_path)
        else:
            self.theater_ini_path = os.path.join(self.script_dir, f"theaters_{version}.ini")

        # try to get the target folder from theater file first
        self.theater_config = configparser.ConfigParser()
        try:
            if os.path.exists(self.theater_ini_path):
                self.theater_config.read(self.theater_ini_path, encoding="utf-8")
        except Exception as e:
            logger.warning(f"Couldn't read theater config file: {e}")

        tgt_folder_ini = ''
        try:
            tgt_folder_ini = self.theater_config[self.theater]['target_folder']
        except Exception as e:
            logger.warning(f"Couldn't read theater info for {self.theater} from the config file: {e}")

        if tgt_folder_ini == '':
            if not self.theater_config.has_section(self.theater):
                self.theater_config[self.theater] = {}
                self.theater_config[self.theater]['copy_to_kto'] = 'False'
            try:
                target_folder = resolve_target_folder_from_theater(self.base_dir, self.theater)
                if target_folder is not None:
                    self.theater_config[self.theater]['target_folder'] = str(target_folder)
                else:
                    self.target_folder_failed = True

            except Exception as e:
                logger.error(e)
                self.target_folder_failed = True

        try:
            center_latitude, center_longitude, center_source = read_theater_center(self.base_dir, self.theater)
            self.theater_center_latitude = center_latitude
            self.theater_center_longitude = center_longitude
            self.theater_center_source = str(center_source) if center_source is not None else ""
        except Exception as e:
            logger.warning(f"Couldn't resolve theater center for {self.theater}: {e}")
