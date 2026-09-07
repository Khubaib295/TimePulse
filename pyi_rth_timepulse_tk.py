"""Set Tcl/Tk lookup paths for TimePulse's explicit PyInstaller payload."""

import os
import sys


if getattr(sys, "frozen", False):
    bundle_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    if bundle_dir not in sys.path:
        sys.path.insert(0, bundle_dir)
    os.environ.setdefault("TCL_LIBRARY", os.path.join(bundle_dir, "_tcl_data"))
    os.environ.setdefault("TK_LIBRARY", os.path.join(bundle_dir, "_tk_data"))
