import logging
logger = logging.getLogger('html_brief_log')

class Callsign_ini:
    def __init__(self, file_contents = None):
        self.tgtsteerpoints = self.fill_tgtsteerpoints(file_contents)
        self.cmds = self.fill_cmds(file_contents)

    class TgtSteerpoint:
        def __init__(self, line_contents = None):
            for attr in ["number", "name"]:
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
                return int(line_contents.split("=")[0].strip("target_")) + 1

        def init_name(self, line_contents):
            if line_contents == None:
                return ""
            else:
                return line_contents.split(", ")[-1].strip(" \n")

    def fill_tgtsteerpoints(self, file_contents = None):
        if file_contents == None:
            return []
        else:
            try:
                s = [l for l in file_contents if l.startswith("target_") and l.split(", ")[-1].strip(" \n") != "Not set"]
                return [self.TgtSteerpoint(x) for x in s]
            except Exception as e:
                logger.warning(f"Error reading target steerpoints: {e}")
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
                logger.warning(f"Error reading cmds: {e}")
                return prgrms
