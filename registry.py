import winreg, sys, os

bms_version = "4.38"
callsign = "wsy"

if sys.platform == 'win32' or sys.platform == 'cygwin':
    baseSubKey = r"SOFTWARE\WOW6432Node\Benchmark Sims\Falcon BMS " + bms_version + r"\\"
    regHandle = winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE)
    keyHandle = winreg.OpenKey(regHandle, baseSubKey)
    base_dir_win = winreg.QueryValueEx(keyHandle, "baseDir")[0]
    briefing_location = os.path.join(base_dir_win, "User", "Briefings", "briefing.txt")
    callsignini_location = os.path.join(base_dir_win, "User", "Config", callsign + ".ini")
    print(f"Brifieng location: {briefing_location}")
    print(f"Callsign.ini location: {callsignini_location}")



