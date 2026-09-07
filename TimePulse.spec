# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_data_files


PROJECT_DIR = Path(SPECPATH)
PYTHON_DIR = Path(sys.base_prefix)

# Use the application's actual icon file.
ICON_PATH = PROJECT_DIR / "assets" / "TimePulse.ico"
if not ICON_PATH.is_file():
    raise FileNotFoundError(
        f"Required application icon not found: {ICON_PATH}"
    )

datas = collect_data_files("customtkinter")

# Some Windows Python installations do not expose Tcl/Tk metadata that the
# PyInstaller hook expects, even though tkinter itself works. Bundle the known
# runtime explicitly so a production onedir package still launches.
TCL_DATA = PYTHON_DIR / "tcl" / "tcl8.6"
TK_DATA = PYTHON_DIR / "tcl" / "tk8.6"
TK_DLLS = [
    PYTHON_DIR / "DLLs" / "_tkinter.pyd",
    PYTHON_DIR / "DLLs" / "tcl86t.dll",
    PYTHON_DIR / "DLLs" / "tk86t.dll",
]
TKINTER_PACKAGE = PYTHON_DIR / "Lib" / "tkinter"
if (
    not TCL_DATA.is_dir()
    or not TK_DATA.is_dir()
    or not TKINTER_PACKAGE.is_dir()
    or not all(path.is_file() for path in TK_DLLS)
):
    raise FileNotFoundError("A complete Tcl/Tk runtime is required to package TimePulse.")
# PyInstaller's Tk hook probes these environment variables during Analysis.
# Set them explicitly for Python distributions that omit configure-time values.
os.environ["TCL_LIBRARY"] = str(TCL_DATA)
os.environ["TK_LIBRARY"] = str(TK_DATA)
datas.extend([
    (str(TCL_DATA), "_tcl_data"),
    (str(TK_DATA), "_tk_data"),
    # Keep a filesystem copy as a fallback for Python distributions whose
    # PyInstaller tkinter pre-hook marks the package unavailable.
    (str(TKINTER_PACKAGE), "tkinter"),
])

datas.append((str(ICON_PATH), "assets"))

a = Analysis(
    [str(PROJECT_DIR / "TimePulse.py")],
    pathex=[str(PROJECT_DIR)],
    binaries=[(str(path), ".") for path in TK_DLLS],
    datas=datas,
    hiddenimports=["tkinter", "_tkinter"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(PROJECT_DIR / "pyi_rth_timepulse_tk.py")],
    # TimePulse does not use these scientific packages. Excluding them avoids
    # needless distribution size and Windows AV scanning work.
    excludes=["numpy", "scipy", "matplotlib", "unittest", "xmlrpc", "pydoc"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="TimePulse",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    exclude_binaries=True,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH),
    version=str(PROJECT_DIR / "version_info.txt"),
)

# A directory build starts without extracting a temporary _MEI archive. The
# build script copies ringtones beside this launcher as ordinary files.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TimePulse",
)
