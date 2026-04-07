# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path.cwd()
src_root = project_root / "src"
resources_root = src_root / "z3950_search_for_marc" / "resources"

a = Analysis(
    ["main.py"],
    pathex=[str(src_root)],
    binaries=[],
    datas=[
        (str(resources_root / "app_icon.ico"), "z3950_search_for_marc/resources"),
        (str(resources_root / "servers.json"), "z3950_search_for_marc/resources"),
    ],
    hiddenimports=[],
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
    name="z3950_search_for_marc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(resources_root / "app_icon.ico")],
)
