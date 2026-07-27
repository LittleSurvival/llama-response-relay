# -*- mode: python ; coding: utf-8 -*-

from importlib.util import find_spec
from pathlib import Path


project_root = Path(SPECPATH)
icon_path = project_root / "assets" / "LlamaCppLauncher.ico"
if not icon_path.is_file():
    raise RuntimeError(f"Missing application icon: {icon_path}")
missing = [
    dependency
    for dependency in ("aiohttp", "PyQt6")
    if find_spec(dependency) is None
]
if missing:
    raise RuntimeError(
        "Missing build dependencies: "
        + ", ".join(missing)
        + '. Run build.bat or install the project with: pip install -e ".[dev]"'
    )
analysis = Analysis(
    [str(project_root / "launcher.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(icon_path), "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt6.QtBluetooth",
        "PyQt6.QtDesigner",
        "PyQt6.QtHelp",
        "PyQt6.QtMultimedia",
        "PyQt6.QtNetworkAuth",
        "PyQt6.QtNfc",
        "PyQt6.QtOpenGL",
        "PyQt6.QtPdf",
        "PyQt6.QtPositioning",
        "PyQt6.QtQml",
        "PyQt6.QtQuick",
        "PyQt6.QtRemoteObjects",
        "PyQt6.QtSensors",
        "PyQt6.QtSerialPort",
        "PyQt6.QtSql",
        "PyQt6.QtSvg",
        "PyQt6.QtTest",
        "PyQt6.QtWebChannel",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebSockets",
        "PyQt6.QtXml",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="LlamaCppLauncher",
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
    icon=str(icon_path),
)
