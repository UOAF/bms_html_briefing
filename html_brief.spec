# -*- mode: python ; coding: utf-8 -*-

import sys

hiddenimports = []
hooksconfig = {}
if sys.platform == "win32":
    hiddenimports.append("pystray._win32")
elif sys.platform.startswith("linux"):
    hiddenimports.extend([
        "gi",
        "gi.repository.DBus",
        "gi.repository.Gio",
        "gi.repository.GLib",
        "gi.repository.GObject",
        "gi.repository.Gtk",
        "gi.repository.AyatanaAppIndicator3",
        "pystray._gtk",
        "pystray._appindicator",
        "pystray._util.gtk",
        "pystray._util.notify_dbus",
    ])
    hooksconfig = {
        "gi": {
            "icons": [],
            "themes": ["Adwaita"],
            "languages": [],
            "module-versions": {
                "AyatanaAppIndicator3": "0.1",
                "DBus": "1.0",
                "Gio": "2.0",
                "GLib": "2.0",
                "GObject": "2.0",
                "Gtk": "3.0",
            },
        },
    }

a = Analysis(
    ['html_brief.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig=hooksconfig,
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='html_brief',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='html_brief',
)
