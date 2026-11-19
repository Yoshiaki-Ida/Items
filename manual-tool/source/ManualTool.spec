# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path(SPECPATH)
plantuml_runtime = project_root / "runtime" / "plantuml"
runtime_data = [(str(plantuml_runtime), "runtime/plantuml")] if plantuml_runtime.is_dir() else []


a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "static"), "static"),
        (str(project_root / "config"), "config"),
        (str(project_root / "scripts" / "convert-vector-to-png.ps1"), "scripts"),
    ] + runtime_data,
    hiddenimports=["manual_tool.app"],
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
    name="ManualTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ManualTool",
)
