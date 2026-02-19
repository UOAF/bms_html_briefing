import os, sys, logging, configparser

logger = logging.getLogger('html_brief_log')
logger_ui = logging.getLogger('ui_logger')

class BmsConfig:
    callsign = ""
    base_dir = ""
    theater = ""
    theater_config = None
    target_folder_failed = False
    kto_target_folder = ""

    def __init__(self, cfg):
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
        self.kto_target_folder = os.path.join(self.base_dir, 'Data', 'TerrData', 'Objects', 'KoreaObj')

        if getattr(sys, 'frozen', False):
            script_dir = os.path.dirname(sys.executable)
        else:
            script_dir = os.environ.get("BMS_BRIEF_HOME", os.path.dirname(sys.argv[0]))
        script_dir = os.path.abspath(script_dir)
        self.script_dir = script_dir

        # try to get the target folder from theater file first
        self.theater_config = configparser.ConfigParser()
        try:
            self.theater_config.read(os.path.join(self.script_dir, 'theaters_'+version+'.ini'))
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
                if os.path.exists(os.path.join(self.base_dir, 'Data', 'TerrData', 'TheaterDefinition', 'theater.lst')):
                    with open(os.path.join(self.base_dir, 'Data', 'TerrData', 'TheaterDefinition', 'theater.lst'), "r") as theater_lst:
                        theater_lst_contents = theater_lst.readlines()
                else:
                    with open(os.path.join(self.base_dir, 'Data', 'TerrData', 'TheaterDefinition', 'Theater.lst'), "r") as theater_lst:
                        theater_lst_contents = theater_lst.readlines()


                tdf_location = next(l for l in theater_lst_contents if l.strip('\n ').endswith('\\' + self.theater + '.tdf')).strip('\n ').split('\\')
                with open(os.path.join(self.base_dir, 'Data', *tdf_location), "r") as theater_tdf:
                    theater_tdf_contents = theater_tdf.readlines()

                datadir_l = next(l for l in theater_tdf_contents if l.strip('\n ').startswith('3ddatadir'))
                datadir = ' '.join(datadir_l.split(' ')[1:]).strip('\n ').split('\\')
                self.theater_config[self.theater]['target_folder'] = os.path.join(self.base_dir, 'Data', *datadir, "KoreaObj")

                if not os.path.exists(self.theater_config[self.theater]['target_folder']):
                # attempt to fix:
                    datadir = ["TerrData" if w.capitalize() == "Terrdata" else w.capitalize() for w in datadir]
                    self.theater_config[self.theater]['target_folder'] = os.path.join(self.base_dir, 'Data', *datadir, "KoreaObj")
                if not os.path.exists(self.theater_config[self.theater]['target_folder']):
                    self.target_folder_failed = True
# Commenting this out to prevent unprompted config save to disk
#                try:
#                    with open(os.path.join(self.script_dir, 'theaters_'+version+'.ini'), 'w+') as f:
#                        self.theater_config.write(f)
#                except Exception as e:
#                    logger.error(e)

            except Exception as e:
                logger.error(e)
                self.target_folder_failed = True
