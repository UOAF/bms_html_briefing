# -*- mode: python ; coding: utf-8 -*-

hiddenimports = ['pystray._win32', 'lib.pdf_worker', 'lib._version', 'openchart.fonts']

a = Analysis(
    ['html_brief.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('openchart/assets/*.svg', 'openchart/assets'),
        ('openchart/assets/*.csv', 'openchart/assets'),
        ('openchart/fonts/*.otf', 'openchart/fonts'),
        ('openchart/fonts/LICENSE', 'openchart/fonts'),
        ('openchart/third_party_licenses/*.md', 'openchart/third_party_licenses'),
        ('licenses/python/openchart-OpenTaxiway-LICENSE.md', 'licenses/python'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
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
    icon=['assets\\icon.png'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='html_brief_win',
)
