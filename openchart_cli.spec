# -*- mode: python ; coding: utf-8 -*-
# One-file console build: pyinstaller openchart_cli.spec

a = Analysis(
    ['openchart_cli.py'],
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
    hiddenimports=['openchart.fonts', 'openchart.assets'],
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
    a.binaries,
    a.datas,
    [],
    name='openchart_cli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
