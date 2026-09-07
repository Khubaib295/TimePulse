import os
import sys
import time
import threading

_STARTUP_T0 = time.perf_counter()

class _StartupProfiler:
    def __init__(self):
        self.enabled = (
            os.environ.get("TIMEPULSE_PROFILE_STARTUP") == "1"
            or os.environ.get("TIMEPULSE_PROFILE") == "1"
            or "--profile-startup" in sys.argv
            or "--profile" in sys.argv
        )
        self.t0 = _STARTUP_T0
        self.milestones = [("process_entry", 0.0)]
        self._lock = threading.Lock() if "threading" in sys.modules else None

    def mark(self, name):
        if self.enabled:
            elapsed_ms = (time.perf_counter() - self.t0) * 1000.0
            if self._lock:
                with self._lock:
                    self.milestones.append((name, elapsed_ms))
            else:
                self.milestones.append((name, elapsed_ms))

    def dump(self):
        if self.enabled:
            lines = ["", "=" * 55, "  TIMEPULSE STARTUP PERFORMANCE AUDIT PROFILE", "=" * 55]
            prev = 0.0
            milestones = list(self.milestones)
            for name, elapsed in milestones:
                delta = elapsed - prev
                lines.append(f"  {name:<32} : {elapsed:7.2f} ms (+{delta:6.2f} ms)")
                prev = elapsed
            lines.extend(["=" * 55, ""])
            report = "\n".join(lines)
            print(report, flush=True)
            report_path = os.environ.get("TIMEPULSE_PROFILE_STARTUP_FILE")
            if report_path:
                try:
                    with open(report_path, "w", encoding="utf-8", newline="\n") as report_file:
                        report_file.write(report)
                except OSError as exc:
                    print(f"Failed to write startup profile: {exc}", flush=True)

PROFILER = _StartupProfiler()

import customtkinter as ctk
import calendar
import json
import hashlib
import hmac
import shutil
import queue
import subprocess
import uuid
import tempfile
import ctypes
import atexit
from ctypes import wintypes
import getpass

WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM)
GWL_WNDPROC = -4
NOTIFY_FOR_THIS_SESSION = 0
DEFAULT_RINGTONE = "Soft_Arrival.wav"
ERROR_ALREADY_EXISTS = 183
# Preserve the legacy-compatible identifier so KRONOS and TimePulse cannot run together.
MUTEX_NAME_PREFIX = "Local\\KRONOS_Alarm_"

from pathlib import Path
from datetime import datetime, timedelta, date
from tkinter import messagebox

PROFILER.mark("imports_complete")

# ---------------- Helpers ----------------
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

def executable_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return APP_DIR


def get_single_instance_mutex_name():
    """Return a stable, per-user mutex name in the current Windows session."""
    account = f"{os.environ.get('USERDOMAIN', '')}\\{getpass.getuser()}"
    account_hash = hashlib.sha256(account.encode("utf-8")).hexdigest()[:32]
    return f"{MUTEX_NAME_PREFIX}{account_hash}"


def acquire_single_instance_mutex():
    """Return a mutex handle, False for an existing instance, or None on error."""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.GetLastError.restype = wintypes.DWORD
        kernel32.SetLastError.argtypes = [wintypes.DWORD]
        kernel32.SetLastError(0)
        handle = kernel32.CreateMutexW(None, False, get_single_instance_mutex_name())
        last_error = kernel32.GetLastError()
        if not handle:
            print(f"Failed to create KRONOS single-instance mutex: {ctypes.WinError(last_error)}")
            return None
        if last_error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        return handle
    except Exception as exc:
        print(f"Failed to create KRONOS single-instance mutex: {exc}")
        return None


def release_single_instance_mutex(handle):
    if not handle:
        return
    try:
        ctypes.windll.kernel32.CloseHandle(handle)
    except Exception as exc:
        print(f"Failed to release KRONOS single-instance mutex: {exc}")


_SINGLE_INSTANCE_HANDLE = None


def acquire_single_instance():
    """Acquire the hardened per-user mutex using the former TimePulse API."""
    global _SINGLE_INSTANCE_HANDLE
    if os.name != "nt":
        return True
    handle = acquire_single_instance_mutex()
    if not handle:
        return handle
    _SINGLE_INSTANCE_HANDLE = handle
    atexit.register(release_single_instance)
    return True


def release_single_instance():
    """Release a mutex obtained through :func:`acquire_single_instance`."""
    global _SINGLE_INSTANCE_HANDLE
    if _SINGLE_INSTANCE_HANDLE:
        release_single_instance_mutex(_SINGLE_INSTANCE_HANDLE)
        _SINGLE_INSTANCE_HANDLE = None
# ---------------- Configuration ----------------
APP_DIR = os.path.dirname(os.path.abspath(__file__))

def resolve_icon_path():
    """Return the bundled or executable-side TimePulse icon path."""
    search_roots = []

    if getattr(sys, "frozen", False):
        # Prefer an external asset beside TimePulse.exe, then the bundled copy.
        search_roots.append(os.path.dirname(sys.executable))

    search_roots.extend([
        APP_DIR,
        getattr(sys, "_MEIPASS", None),
    ])

    for root in search_roots:
        if not root:
            continue

        candidate = os.path.join(root, "assets", "TimePulse.ico")
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)

    return None

ICON_PATH = resolve_icon_path()
# For persistent data, we want it next to the EXE, not in the temp bundle dir
if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.dirname(sys.executable)
else:
    DATA_DIR = APP_DIR

DATA_FILE  = os.path.join(DATA_DIR, "alarms.json")
HISTORY_DIR = os.path.join(DATA_DIR, "Alarm History")
HISTORY_FILE = os.path.join(HISTORY_DIR, "alarm_history.txt")
DEFAULT_HASH = None # None means password protection is disabled
DEFAULT_ALLOW_SNOOZE = True
DEFAULT_PROTECT_EDIT_DELETE = True
PASSWORD_HASH_PREFIX = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 600_000

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

BG      = ("#F4F7FB", "#0D1117")
CARD    = ("#FFFFFF", "#161B22")
ACCENT  = "#4F46E5"
ACCENT2 = "#D83A63"
TEXT    = ("#111827", "#F3F4F6")
SUBTEXT = ("#4B5563", "#B8C0CC")
SUCCESS = "#15803D"
DANGER  = "#DC2626"
BORDER  = ("#D1D5DB", "#303846")
MUTED   = ("#E5E7EB", "#232B36")
INPUT   = ("#F9FAFB", "#202938")
ON_ACCENT = "#FFFFFF"

def center_window(window, width, height):
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


_icon_warning_shown = False
_icon_photo_cache = {}
_native_icon_handles = {}

def apply_window_icon(window):
    """
    Apply assets/TimePulse.ico to a Tk/CustomTkinter root window or popup.

    WM_SETICON is used for the real Windows title-bar icon. Tk iconphoto and
    iconbitmap remain as fallbacks.
    """
    global _icon_warning_shown

    if not ICON_PATH:
        if not _icon_warning_shown:
            print(
                "Application icon not found. Expected assets/TimePulse.ico."
            )
            _icon_warning_shown = True
        return

    def _apply():
        global _icon_warning_shown

        try:
            if not window.winfo_exists():
                return
        except Exception:
            return

        errors = []
        native_icon_applied = False

        # Native Windows caption icon: this is the reliable path for CTkToplevel.
        if os.name == "nt":
            try:
                hwnd = int(window.winfo_id())

                user32 = ctypes.windll.user32
                IMAGE_ICON = 1
                LR_LOADFROMFILE = 0x0010
                WM_SETICON = 0x0080
                ICON_SMALL = 0
                ICON_BIG = 1

                user32.LoadImageW.argtypes = [
                    wintypes.HINSTANCE,
                    wintypes.LPCWSTR,
                    wintypes.UINT,
                    ctypes.c_int,
                    ctypes.c_int,
                    wintypes.UINT,
                ]
                user32.LoadImageW.restype = wintypes.HANDLE
                user32.SendMessageW.argtypes = [
                    wintypes.HWND,
                    wintypes.UINT,
                    wintypes.WPARAM,
                    wintypes.LPARAM,
                ]
                user32.SendMessageW.restype = wintypes.LRESULT

                cache_key = os.path.abspath(ICON_PATH)
                handles = _native_icon_handles.get(cache_key)

                if handles is None:
                    small_icon = user32.LoadImageW(
                        None, cache_key, IMAGE_ICON, 16, 16, LR_LOADFROMFILE
                    )
                    big_icon = user32.LoadImageW(
                        None, cache_key, IMAGE_ICON, 32, 32, LR_LOADFROMFILE
                    )

                    if not small_icon and not big_icon:
                        raise ctypes.WinError(ctypes.get_last_error())

                    handles = (small_icon, big_icon)
                    _native_icon_handles[cache_key] = handles

                small_icon, big_icon = handles

                if small_icon:
                    user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small_icon)
                if big_icon:
                    user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big_icon)

                # Keep references on the window as well.
                window._native_small_icon = small_icon
                window._native_big_icon = big_icon
                native_icon_applied = True
            except Exception as exc:
                errors.append(f"WM_SETICON failed: {exc}")

        # Loading Pillow and decoding an icon is unnecessary on Windows when
        # WM_SETICON succeeded. Keep that import off the first-paint path.
        if not native_icon_applied:
            try:
                from PIL import Image, ImageTk

                cache_key = os.path.abspath(ICON_PATH)
                photo = _icon_photo_cache.get(cache_key)
                if photo is None:
                    with Image.open(ICON_PATH) as icon_image:
                        icon_image = icon_image.convert("RGBA")
                        photo = ImageTk.PhotoImage(icon_image)
                    _icon_photo_cache[cache_key] = photo
                window._app_icon_photo = photo
                window.iconphoto(False, photo)
            except Exception as exc:
                errors.append(f"iconphoto failed: {exc}")

            try:
                window.iconbitmap(default=ICON_PATH)
            except Exception as exc:
                errors.append(f"iconbitmap failed: {exc}")

        if len(errors) == 3 and not _icon_warning_shown:
            print("Failed to apply assets/TimePulse.ico: " + " | ".join(errors))
            _icon_warning_shown = True

    # Apply after the native window is fully created. The delayed pass is
    # important for CustomTkinter Toplevel windows.
    try:
        _apply()
        # A single idle retry covers windows that are not realized yet without
        # forcing an update or doing redundant image decoding during startup.
        window.after_idle(_apply)
    except Exception:
        _apply()


def log_history_event(alarm, event):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    label = alarm.get("label", "Alarm")
    log_entry = f"{timestamp} - {label} ({event})\n"

    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        with open(HISTORY_FILE, "a") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"Failed to log event: {e}")


def _normalize_data(data):
    """Validate persisted alarms and repair safe legacy omissions."""
    if not isinstance(data, dict):
        raise ValueError("The data root must be an object.")
    alarms = data.get("alarms")
    if not isinstance(alarms, list):
        raise ValueError("'alarms' must be a list.")
    password = data.get("password")
    if password is not None and not isinstance(password, str):
        raise ValueError("'password' must be null or a string.")
    allow_snooze = data.get("allow_snooze", DEFAULT_ALLOW_SNOOZE)
    if not isinstance(allow_snooze, bool):
        raise ValueError("'allow_snooze' must be a boolean.")
    protect_edit_delete = data.get("protect_edit_delete", DEFAULT_PROTECT_EDIT_DELETE)
    if not isinstance(protect_edit_delete, bool):
        raise ValueError("'protect_edit_delete' must be a boolean.")
    normalized = dict(data)
    normalized["password"] = password
    normalized["allow_snooze"] = allow_snooze
    normalized["protect_edit_delete"] = protect_edit_delete
    normalized["alarms"] = []
    seen_ids = set()
    now = datetime.now()
    for index, raw_alarm in enumerate(alarms):
        if not isinstance(raw_alarm, dict):
            raise ValueError(f"Alarm #{index + 1} must be an object.")
        alarm = dict(raw_alarm)
        alarm_id = alarm.get("id")
        if not isinstance(alarm_id, str) or not alarm_id.strip() or alarm_id in seen_ids:
            alarm_id = str(uuid.uuid4())
            alarm["id"] = alarm_id
        seen_ids.add(alarm_id)
        if "datetime" not in alarm:
            time_value = alarm.get("time")
            if not isinstance(time_value, str):
                raise ValueError(f"Alarm {alarm_id} has no valid time.")
            date_value = alarm.get("date", now.strftime("%Y-%m-%d"))
            alarm["date"] = date_value
            alarm["datetime"] = f"{date_value}T{time_value}:00"
        alarm_dt = parse_alarm_datetime(alarm.get("datetime"))
        if alarm_dt is None:
            raise ValueError(f"Alarm {alarm_id} has an invalid datetime.")
        if "date" in alarm:
            alarm["date"] = alarm_dt.strftime("%Y-%m-%d")
        if "time" in alarm:
            alarm["time"] = alarm_dt.strftime("%H:%M")
        alarm["datetime"] = alarm_dt.strftime("%Y-%m-%dT%H:%M:%S")
        repeat = str(alarm.get("repeat", "none")).lower()
        if repeat not in {"none", "daily", "weekly", "monthly"}:
            raise ValueError(f"Alarm {alarm_id} has an invalid repeat value.")
        if "repeat" in alarm:
            alarm["repeat"] = repeat
        if "enabled" in alarm:
            alarm["enabled"] = bool(alarm["enabled"])
        if "status" in alarm:
            alarm["status"] = str(alarm["status"])
        if "label" in alarm:
            alarm["label"] = str(alarm["label"])
        if "ringtone" in alarm:
            alarm["ringtone"] = str(alarm["ringtone"])
        if repeat == "monthly":
            try:
                repeat_day = int(alarm.get("repeat_day", alarm_dt.day))
            except (TypeError, ValueError):
                repeat_day = alarm_dt.day
            alarm["repeat_day"] = min(31, max(1, repeat_day))
        if repeat == "none" and alarm.get("enabled", True) and alarm_dt < now:
            alarm["enabled"] = False
            alarm["status"] = "missed"
        normalized["alarms"].append(alarm)
    return normalized
def load_data():
    default_data = {
        "password": DEFAULT_HASH,
        "allow_snooze": DEFAULT_ALLOW_SNOOZE,
        "protect_edit_delete": DEFAULT_PROTECT_EDIT_DELETE,
        "alarms": [],
    }
    if not os.path.exists(DATA_FILE):
        return default_data

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        data = _normalize_data(raw_data)
        if data != raw_data and not save_data(data):
            print("Warning: Normalized alarm data could not be saved.")
        return data
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        try:
            backup_path = f"{DATA_FILE}.{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
            if os.path.exists(DATA_FILE):
                shutil.copy2(DATA_FILE, backup_path)
        except OSError:
            pass
        return default_data
def save_data(data):
    temp_path = None
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=DATA_DIR,
            prefix=".alarms.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = temp_file.name
            json.dump(data, temp_file, indent=2)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        if os.path.exists(DATA_FILE):
            try:
                shutil.copy2(DATA_FILE, f"{DATA_FILE}.bak")
            except Exception as backup_error:
                print(f"Failed to back up data: {backup_error}")

        os.replace(temp_path, DATA_FILE)
        return True
    except Exception as e:
        print(f"Failed to save data: {e}")
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return False


def get_alarm_popup_actions(allow_snooze, is_snoozed=False):
    """Return the actions rendered for an alarm popup."""
    if allow_snooze and not is_snoozed:
        return ("Snooze (3m)", "Lock Now")
    return ("Lock Now",)


def requires_alarm_change_auth(protect_edit_delete):
    """Return whether edit and delete actions require authentication."""
    return bool(protect_edit_delete)
# ---------------- Windows Startup Logic ----------------
STARTUP_FILE_NAME = "TimePulse Startup.cmd"
LEGACY_STARTUP_FILE_NAMES = ("Alarm App Startup.cmd",)
LEGACY_TASK_NAMES = ("AlarmApp_AutoStart", "AlarmApp_AutoStart_Login")
STARTUP_MIGRATION_VERSION = 1

def get_app_launch_details():
    """Return the executable and arguments used by the Windows Startup entry."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""

    script_path = str(Path(__file__).resolve())
    python_executable = Path(sys.executable)

    # Prefer pythonw.exe so login startup does not open a console window.
    pythonw_path = python_executable.with_name("pythonw.exe")
    launcher = str(pythonw_path if pythonw_path.exists() else python_executable)
    return launcher, f'"{script_path}"'


def get_startup_folder():
    """Return the current user's Windows Startup folder."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None

    return os.path.join(
        appdata,
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "Startup",
    )


def get_startup_file_path():
    startup_dir = get_startup_folder()
    if not startup_dir:
        return None
    return os.path.join(startup_dir, STARTUP_FILE_NAME)


def is_auto_start_enabled():
    startup_file = get_startup_file_path()
    return bool(startup_file and os.path.isfile(startup_file))


def _remove_legacy_startup_files():
    """Remove only exact Startup-folder filenames created by earlier app versions."""
    startup_dir = get_startup_folder()
    if not startup_dir:
        return True

    success = True
    for filename in LEGACY_STARTUP_FILE_NAMES:
        legacy_path = os.path.join(startup_dir, filename)
        try:
            if os.path.isfile(legacy_path):
                os.remove(legacy_path)
        except Exception as exc:
            print(f"Failed to remove legacy startup entry '{filename}': {exc}")
            success = False
    return success


def _remove_legacy_scheduled_tasks():
    """Best-effort cleanup of tasks created by earlier app versions."""
    success = True
    for task_name in LEGACY_TASK_NAMES:
        try:
            result = subprocess.run(
                ["schtasks", "/Delete", "/TN", task_name, "/F"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode:
                details = (result.stderr or result.stdout or "").strip()
                if "cannot find" not in details.lower() and "not exist" not in details.lower():
                    print(f"Failed to remove legacy startup task '{task_name}': {details or result.returncode}")
                    success = False
        except Exception as exc:
            print(f"Failed to remove legacy startup task '{task_name}': {exc}")
            success = False
    return success


def enable_auto_start():
    """
    Create a per-user Startup-folder command file.

    This does not require administrator rights and runs once when the current
    Windows user signs in.
    """
    startup_file = get_startup_file_path()
    if not startup_file:
        print("Automatic startup is unavailable because APPDATA is not set.")
        return False

    executable, arguments = get_app_launch_details()

    try:
        os.makedirs(os.path.dirname(startup_file), exist_ok=True)

        command = f'@echo off\r\nstart "" "{executable}"'
        if arguments:
            command += f" {arguments}"
        command += "\r\nexit /b 0\r\n"

        with open(startup_file, "w", encoding="utf-8", newline="") as startup_script:
            startup_script.write(command)

        return os.path.isfile(startup_file)
    except Exception as exc:
        print(f"Failed to create Windows Startup entry: {exc}")
        return False


def ensure_login_auto_start():
    """Ensure the app starts automatically at Windows sign-in."""
    startup_file = get_startup_file_path()
    if not startup_file:
        return False

    executable, arguments = get_app_launch_details()
    expected = f'@echo off\r\nstart "" "{executable}"'
    if arguments:
        expected += f" {arguments}"
    expected += "\r\nexit /b 0\r\n"

    if os.path.isfile(startup_file):
        try:
            with open(startup_file, "r", encoding="utf-8", newline="") as f:
                content = f.read()
            if content == expected:
                return True
        except Exception:
            pass

    return enable_auto_start()


def run_startup_migration(data, data_lock):
    """Run legacy Startup/Task Scheduler cleanup once and record completion.

    This deliberately accepts the in-memory settings dictionary so its marker
    remains backward-compatible with existing alarms.json files (unknown keys
    are already preserved by the normalizer). Call it from a worker thread.
    """
    try:
        with data_lock:
            current_version = int(data.get("startup_migration_version", 0) or 0)
        if current_version >= STARTUP_MIGRATION_VERSION:
            return False
    except (TypeError, ValueError):
        current_version = 0

    files_ok = _remove_legacy_startup_files()
    tasks_ok = _remove_legacy_scheduled_tasks()
    if not (files_ok and tasks_ok):
        print("Startup migration encountered errors; marker will not be saved so it can be retried.")
        return False

    with data_lock:
        try:
            current_version = int(data.get("startup_migration_version", 0) or 0)
        except (TypeError, ValueError):
            current_version = 0
        if current_version >= STARTUP_MIGRATION_VERSION:
            return False
        data["startup_migration_version"] = STARTUP_MIGRATION_VERSION
        if save_data(data):
            return True
        data.pop("startup_migration_version", None)
        print("Startup migration will be retried because its completion marker could not be saved.")
        return False


def disable_auto_start():
    startup_file = get_startup_file_path()
    if not startup_file:
        return False

    try:
        if os.path.exists(startup_file):
            os.remove(startup_file)
        return not os.path.exists(startup_file)
    except Exception as exc:
        print(f"Failed to remove Windows Startup entry: {exc}")
        return False


def hash_password(password):
    """Create a salted PBKDF2-HMAC-SHA256 password hash."""
    if not password:
        return None

    salt = os.urandom(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return (
        f"{PASSWORD_HASH_PREFIX}${PASSWORD_HASH_ITERATIONS}"
        f"${salt.hex()}${derived_key.hex()}"
    )

def _is_legacy_sha256_hash(stored_hash):
    if not isinstance(stored_hash, str) or len(stored_hash) != 64:
        return False
    try:
        bytes.fromhex(stored_hash)
        return True
    except ValueError:
        return False

def verify_password(password, stored_hash):
    """Verify PBKDF2 hashes and legacy unsalted SHA-256 hashes."""
    if not password or not isinstance(stored_hash, str):
        return False

    if stored_hash.startswith(f"{PASSWORD_HASH_PREFIX}$"):
        try:
            algorithm, iterations_text, salt_hex, expected_hex = stored_hash.split("$")
            if algorithm != PASSWORD_HASH_PREFIX:
                return False

            iterations = int(iterations_text)
            if not 100_000 <= iterations <= 2_000_000:
                return False

            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(expected_hex)
            if len(salt) < 16 or len(expected) != 32:
                return False

            actual = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                iterations,
                dklen=len(expected),
            )
            return hmac.compare_digest(actual, expected)
        except (TypeError, ValueError):
            return False

    if _is_legacy_sha256_hash(stored_hash):
        legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy_hash, stored_hash)

    return False

def validate_new_password(password):
    """Return a user-facing validation error, or None when valid."""
    if not password:
        return "New password cannot be empty."
    if not password.strip():
        return "Password cannot contain only spaces."
    if len(password) < 6:
        return "Password must be at least 6 characters long."
    return None

def lock_screen():
    try:
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=True)
        return True
    except Exception as exc:
        print(f"Failed to lock workstation: {exc}")
        return False

def to_24h(h, m, ampm):
    h = int(h); m = int(m)
    if ampm == "AM":
        h = 0 if h == 12 else h
    else:
        h = h if h == 12 else h + 12
    return h, m

def to_12h(time24):
    h, m = map(int, time24.split(":"))
    ampm = "AM" if h < 12 else "PM"
    return f"{h % 12 or 12:02d}", f"{m:02d}", ampm

def sort_alarms(alarms):
    return sorted(alarms, key=lambda a: (0 if a.get("enabled", True) else 1, a.get("datetime", a.get("time", "99:99"))))

def build_alarm_datetime(date_str, time_str):
    """ Builds ISO datetime from YYYY-MM-DD and HH:MM """
    return f"{date_str}T{time_str}:00"

def parse_alarm_datetime(dt_str):
    """ Parses ISO datetime string """
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None

def next_repeat_datetime(alarm, now=None):
    """Return the next future occurrence for a supported repeating alarm."""
    repeat = str(alarm.get("repeat", "none")).lower()
    if repeat not in {"daily", "weekly", "monthly"}:
        return None

    now = now or datetime.now()
    base_dt = parse_alarm_datetime(
        alarm.get("snooze_original_datetime") or alarm.get("datetime")
    )
    if not base_dt:
        return None

    if repeat in {"daily", "weekly"}:
        interval = timedelta(days=1 if repeat == "daily" else 7)
        intervals_elapsed = max(1, ((now - base_dt) // interval) + 1)
        return base_dt + (interval * intervals_elapsed)

    try:
        preferred_day = int(alarm.get("repeat_day", base_dt.day))
    except (TypeError, ValueError):
        preferred_day = base_dt.day
    preferred_day = max(1, min(31, preferred_day))

    months_ahead = max(
        1,
        ((now.year - base_dt.year) * 12) + now.month - base_dt.month,
    )

    def occurrence_after_months(months):
        month_index = (base_dt.year * 12 + base_dt.month - 1) + months
        year, zero_based_month = divmod(month_index, 12)
        month = zero_based_month + 1
        day = min(preferred_day, calendar.monthrange(year, month)[1])
        return base_dt.replace(year=year, month=month, day=day)

    candidate = occurrence_after_months(months_ahead)
    if candidate <= now:
        candidate = occurrence_after_months(months_ahead + 1)
    return candidate

# ---------------- Audio Manager and Ringtone Selector ----------------
class AudioManager:
    def __init__(self, app):
        self.app = app
        self.current_preview_path = None
        self.hover_timer_id = None
        self.stop_timer_id = None
        self.alarm_playing = False
        self.current_alarm_path = None
        self.preview_generation = 0
        self._beep_stop_event = None
        self._beep_thread = None
        self._audio_warning_shown = False
        self._mci = ctypes.windll.winmm.mciSendStringW
        self._mci.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_uint, wintypes.HWND]
        self._mci.restype = ctypes.c_uint

    def _mci_command(self, command, raise_errors=True):
        buffer = ctypes.create_unicode_buffer(255)
        result = self._mci(command, buffer, len(buffer), None)
        if result and raise_errors:
            raise RuntimeError(f"MCI command failed ({result}): {command}")
        return buffer.value

    def _close_alias(self, alias):
        self._mci_command(f"stop {alias}", raise_errors=False)
        self._mci_command(f"close {alias}", raise_errors=False)

    def _open_alias(self, alias, path):
        self._close_alias(alias)
        safe_path = str(path).replace('"', '')
        self._mci_command(f'open "{safe_path}" type waveaudio alias {alias}')

    def _log_audio_error(self, message):
        if not self._audio_warning_shown:
            print(message)
            self._audio_warning_shown = True

    def preview_ringtone(self, path):
        self.cancel_timers()
        self.stop_preview()

        if self.alarm_playing:
            return

        self.preview_generation += 1
        generation = self.preview_generation
        self.current_preview_path = path
        self.hover_timer_id = self.app.after(250, lambda: self._play_preview_impl(path, generation))

    def _play_preview_impl(self, path, generation):
        self.hover_timer_id = None
        if generation != self.preview_generation or self.alarm_playing:
            return
        if not path or not os.path.exists(path):
            return

        try:
            self._open_alias("preview_sound", path)
            self._mci_command("play preview_sound")
            self.stop_timer_id = self.app.after(4000, self.stop_preview)
        except Exception as e:
            self.current_preview_path = None
            self._close_alias("preview_sound")
            self._log_audio_error(f"Error playing preview: {e}")

    def stop_preview(self):
        self.preview_generation += 1
        self.cancel_timers()
        if self.current_preview_path:
            self.current_preview_path = None
        self._close_alias("preview_sound")

    def cancel_timers(self):
        if self.hover_timer_id:
            try:
                self.app.after_cancel(self.hover_timer_id)
            except Exception as exc:
                self._log_audio_error(f"Failed to cancel preview timer: {exc}")
            self.hover_timer_id = None
        if self.stop_timer_id:
            try:
                self.app.after_cancel(self.stop_timer_id)
            except Exception as exc:
                self._log_audio_error(f"Failed to cancel preview stop timer: {exc}")
            self.stop_timer_id = None

    def play_alarm(self, path):
        self.stop_preview()
        self.stop_alarm()
        self.alarm_playing = True
        self.current_alarm_path = path

        sound_path = path
        if not sound_path or not os.path.exists(sound_path):
            sound_path = self.app.resolve_ringtone_path(DEFAULT_RINGTONE)

        success = False
        if sound_path and os.path.exists(sound_path):
            try:
                # MCI preview playback works well, but "play ... repeat" is not
                # reliable for every valid WAV encoding. Use Windows PlaySound
                # for the actual looping alarm instead.
                import winsound
                winsound.PlaySound(
                    sound_path,
                    winsound.SND_FILENAME
                    | winsound.SND_ASYNC
                    | winsound.SND_LOOP
                    | winsound.SND_NODEFAULT,
                )
                success = True
            except Exception as e:
                self._log_audio_error(f"Failed to play selected alarm WAV: {e}")

        if not success:
            self._beep_stop_event = threading.Event()
            self._beep_thread = threading.Thread(
                target=self._play_beep_fallback,
                args=(self._beep_stop_event,),
                daemon=True
            )
            self._beep_thread.start()

    def _play_beep_fallback(self, stop_event):
        try:
            import winsound
            while not stop_event.is_set():
                for _ in range(3):
                    if stop_event.is_set(): break
                    winsound.Beep(880,  300); time.sleep(0.1)
                    winsound.Beep(1100, 300); time.sleep(0.1)
                    winsound.Beep(1320, 400); time.sleep(0.3)
                time.sleep(0.5)
        except Exception as exc:
            self._log_audio_error(f"Failed to play beep fallback: {exc}")

    def stop_alarm(self):
        self.alarm_playing = False
        self.current_alarm_path = None

        if self._beep_stop_event:
            self._beep_stop_event.set()
            self._beep_stop_event = None

        # Stop any looping WAV started by winsound.PlaySound.
        try:
            import winsound
            winsound.PlaySound(None, 0)
        except Exception as exc:
            self._log_audio_error(f"Failed to stop alarm sound: {exc}")

        # Also close the old MCI alias for compatibility with any playback
        # started before this update.
        self._close_alias("alarm_sound")

    def stop_all(self):
        self.stop_preview()
        self.stop_alarm()


class RingtoneSelector(ctk.CTkFrame):
    def __init__(self, master, current_value, on_select, audio_manager, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.audio_manager = audio_manager
        self.on_select = on_select
        self.current_value = current_value
        self.popup = None
        self.item_widgets = []
        self._outside_click_bind_id = None
        self._escape_bind_id = None
        self._bind_after_id = None

        self.btn = ctk.CTkButton(
            self,
            text=self.audio_manager.app.get_friendly_name(self.current_value),
            height=34,
            corner_radius=7,
            fg_color=INPUT,
            hover_color=MUTED,
            border_width=2,
            border_color=BORDER,
            text_color=TEXT,
            font=("Segoe UI", 12),
            anchor="w",
            command=self.toggle_dropdown
        )
        self.btn.pack(fill="x", expand=True)

    def set_value(self, filename):
        self.current_value = filename
        self.btn.configure(text=self.audio_manager.app.get_friendly_name(filename))
        if self.on_select:
            self.on_select(filename)

    def toggle_dropdown(self):
        if self.popup and self.popup.winfo_exists():
            self.close_dropdown()
        else:
            self.open_dropdown()

    def open_dropdown(self):
        self.audio_manager.stop_preview()

        if self.popup and self.popup.winfo_exists():
            self.close_dropdown()

        self.popup = ctk.CTkToplevel(self)
        apply_window_icon(self.popup)
        self.popup.withdraw()
        self.popup.overrideredirect(True)
        self.popup.configure(fg_color=CARD)
        self.popup.attributes("-topmost", True)

        self.update_idletasks()
        x = self.btn.winfo_rootx()
        y = self.btn.winfo_rooty() + self.btn.winfo_height() + 2
        width = max(self.btn.winfo_width(), 1)
        height = 200

        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        if x + width > screen_width:
            x = max(0, screen_width - width)
        if y + height > screen_height:
            y = max(0, self.btn.winfo_rooty() - height - 2)

        self.popup.geometry(f"{width}x{height}+{x}+{y}")

        container = ctk.CTkFrame(
            self.popup,
            fg_color=CARD,
            border_width=1,
            border_color=BORDER,
            corner_radius=7
        )
        container.pack(fill="both", expand=True)

        scroll = ctk.CTkScrollableFrame(
            container,
            fg_color="transparent",
            scrollbar_button_color=BORDER,
            corner_radius=7
        )
        scroll.pack(fill="both", expand=True, padx=2, pady=2)

        ringtones = self.audio_manager.app.get_available_ringtones()
        self.item_widgets = []

        for rt in ringtones:
            friendly = self.audio_manager.app.get_friendly_name(rt)
            is_selected = (rt == self.current_value)

            item_frame = ctk.CTkFrame(
                scroll,
                fg_color=ACCENT if is_selected else "transparent",
                corner_radius=5,
                height=30
            )
            item_frame.pack(fill="x", pady=1, padx=2)
            item_frame.pack_propagate(False)

            lbl = ctk.CTkLabel(
                item_frame,
                text=friendly,
                text_color=ON_ACCENT if is_selected else TEXT,
                font=("Segoe UI", 11, "bold" if is_selected else "normal"),
                anchor="w"
            )
            lbl.pack(fill="both", expand=True, padx=8)

            for widget in (item_frame, lbl):
                widget.bind(
                    "<Enter>",
                    lambda e, r=rt, f=item_frame, l=lbl: self.on_item_enter(r, f, l)
                )
                widget.bind(
                    "<Leave>",
                    lambda e, f=item_frame, l=lbl: self.on_item_leave(f, l)
                )
                widget.bind("<Button-1>", lambda e, r=rt: self.on_item_click(r))

            self.item_widgets.append((rt, item_frame, lbl, is_selected))

        self.popup.deiconify()
        self.popup.lift()

        # Bind only after the opening click has completed. This prevents the
        # same click from being interpreted as an outside click.
        self._bind_after_id = self.after_idle(self._install_popup_bindings)

    def _install_popup_bindings(self):
        self._bind_after_id = None
        if not self.popup or not self.popup.winfo_exists():
            return

        top = self.winfo_toplevel()
        self._outside_click_bind_id = top.bind(
            "<Button-1>",
            self._on_global_click,
            add="+"
        )
        self._escape_bind_id = top.bind(
            "<Escape>",
            lambda event: self.close_dropdown(),
            add="+"
        )

    @staticmethod
    def _is_descendant(widget, ancestor):
        while widget is not None:
            if widget == ancestor:
                return True
            try:
                widget = widget.master
            except Exception:
                return False
        return False

    def _on_global_click(self, event):
        if not self.popup or not self.popup.winfo_exists():
            return

        top = self.winfo_toplevel()
        try:
            clicked = top.winfo_containing(event.x_root, event.y_root)
        except Exception:
            clicked = None

        if clicked is None:
            self.close_dropdown()
            return

        if self._is_descendant(clicked, self.popup):
            return

        if self._is_descendant(clicked, self):
            return

        self.close_dropdown()

    def on_item_enter(self, rt, frame, label):
        is_sel = False
        for r, f, l, sel in self.item_widgets:
            if r == rt:
                is_sel = sel
                break

        if not is_sel:
            frame.configure(fg_color=BORDER)

        path = self.audio_manager.app.resolve_ringtone_path(rt)
        if path:
            self.audio_manager.preview_ringtone(path)

    def on_item_leave(self, frame, label):
        is_sel = False
        for r, f, l, sel in self.item_widgets:
            if f == frame:
                is_sel = sel
                break

        if not is_sel:
            frame.configure(fg_color="transparent")

        self.audio_manager.stop_preview()

    def on_item_click(self, rt):
        self.set_value(rt)
        self.close_dropdown()

    def close_dropdown(self):
        self.audio_manager.stop_preview()

        if self._bind_after_id:
            try:
                self.after_cancel(self._bind_after_id)
            except Exception:
                pass
            self._bind_after_id = None

        top = self.winfo_toplevel()

        if self._outside_click_bind_id:
            try:
                top.unbind("<Button-1>", self._outside_click_bind_id)
            except Exception:
                pass
            self._outside_click_bind_id = None

        if self._escape_bind_id:
            try:
                top.unbind("<Escape>", self._escape_bind_id)
            except Exception:
                pass
            self._escape_bind_id = None

        popup = self.popup
        self.popup = None
        self.item_widgets = []

        if popup and popup.winfo_exists():
            popup.destroy()

    def destroy(self):
        self.close_dropdown()
        super().destroy()


# ---------------- Main App ----------------
class NumberStepper(ctk.CTkFrame):
    def __init__(self, master, min_value, max_value, value, width=98, height=34, command=None):
        super().__init__(master, fg_color="transparent")
        self.min_value = min_value
        self.max_value = max_value
        self.command = command
        self.var = ctk.StringVar()

        btn_w = 24
        entry_w = max(38, width - (btn_w * 2))

        self.minus_btn = ctk.CTkButton(
            self, text="-", width=btn_w, height=height, corner_radius=7,
            fg_color=BORDER, hover_color=ACCENT, text_color=TEXT,
            font=("Segoe UI", 12, "bold"), command=lambda: self._step(-1)
        )
        self.minus_btn.grid(row=0, column=0)

        self.entry = ctk.CTkEntry(
            self, textvariable=self.var, width=entry_w, height=height,
            fg_color=INPUT, border_color=ACCENT, text_color=TEXT,
            font=("Segoe UI Black", 14), justify="center"
        )
        self.entry.grid(row=0, column=1, padx=2)
        self.entry.bind("<FocusOut>", lambda _: self._commit(True))
        self.entry.bind("<Return>", lambda _: self._commit(True))

        self.plus_btn = ctk.CTkButton(
            self, text="+", width=btn_w, height=height, corner_radius=7,
            fg_color=BORDER, hover_color=ACCENT, text_color=TEXT,
            font=("Segoe UI", 12, "bold"), command=lambda: self._step(1)
        )
        self.plus_btn.grid(row=0, column=2)
        self.set(value)

    def get(self):
        return self._commit(False)

    def set(self, value, notify=False):
        try:
            value = int(value)
        except Exception:
            value = self.min_value
        value = max(self.min_value, min(self.max_value, value))
        self.var.set(f"{value:02d}")
        if notify and self.command:
            self.command()

    def _commit(self, notify):
        raw = self.var.get().strip()
        try:
            value = int(raw)
        except Exception:
            value = self.min_value
        self.set(value, notify=notify)
        return self.var.get()

    def _step(self, delta):
        value = int(self.get()) + delta
        if value > self.max_value:
            value = self.min_value
        elif value < self.min_value:
            value = self.max_value
        self.set(value, notify=True)


class DatePickerField(ctk.CTkFrame):
    def __init__(self, master, variable, width=270, command=None):
        super().__init__(master, fg_color="transparent")
        self.var = variable
        self.command = command
        self.popup = None
        self.previous_grab = None
        self.selected_date = self._parse_var() or date.today()
        self.visible_month = self.selected_date.replace(day=1)

        self.grid_columnconfigure(0, weight=1)
        self.display_btn = ctk.CTkButton(
            self, text="", height=34, width=width, corner_radius=7,
            fg_color=INPUT, hover_color=MUTED, border_width=2,
            border_color=ACCENT, text_color=TEXT, font=("Segoe UI Black", 13),
            anchor="w", command=self._open_calendar
        )
        self.display_btn.grid(row=0, column=0, columnspan=3, sticky="ew")

        shortcut_style = {
            "height": 28, "corner_radius": 7, "fg_color": BORDER,
            "hover_color": ACCENT, "text_color": TEXT,
            "font": ("Segoe UI", 10, "bold")
        }
        ctk.CTkButton(
            self, text="Today", width=74, command=lambda: self.set_date(date.today(), True),
            **shortcut_style
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))
        ctk.CTkButton(
            self, text="Tomorrow", width=92,
            command=lambda: self.set_date(date.today() + timedelta(days=1), True),
            **shortcut_style
        ).grid(row=1, column=1, sticky="w", padx=(6, 0), pady=(5, 0))
        ctk.CTkButton(
            self, text="Calendar", width=92, command=self._open_calendar,
            **shortcut_style
        ).grid(row=1, column=2, sticky="e", padx=(6, 0), pady=(5, 0))
        self._refresh_display()

    def set_date(self, value, notify=False):
        parsed = self._coerce_date(value)
        if not parsed:
            parsed = date.today()
        self.selected_date = parsed
        self.visible_month = parsed.replace(day=1)
        self.var.set(parsed.strftime("%Y-%m-%d"))
        self._refresh_display()
        if self.popup and self.popup.winfo_exists():
            self._draw_calendar()
        if notify and self.command:
            self.command()

    def _parse_var(self):
        return self._coerce_date(self.var.get())

    def _coerce_date(self, value):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
        except Exception:
            return None

    def _refresh_display(self):
        self.display_btn.configure(text=self.selected_date.strftime("%a, %d %b %Y"))

    def _open_calendar(self):
        if self.command:
            self.command()
        if self.popup and self.popup.winfo_exists():
            self.popup.focus()
            return

        self.visible_month = self.selected_date.replace(day=1)
        self.previous_grab = self.grab_current()
        self.popup = ctk.CTkToplevel(self)
        apply_window_icon(self.popup)
        self.popup.title("Choose Date")
        self.popup.configure(fg_color=BG)
        self.popup.geometry("300x330")
        self.popup.resizable(False, False)
        self.popup.attributes("-topmost", True)
        self.popup.transient(self.winfo_toplevel())
        self.popup.protocol("WM_DELETE_WINDOW", self._close_popup)

        self._position_popup()
        self._draw_calendar()
        self.popup.grab_set()

    def _position_popup(self):
        self.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 6
        self.popup.geometry(f"+{x}+{y}")

    def _draw_calendar(self):
        for child in self.popup.winfo_children():
            child.destroy()

        panel = ctk.CTkFrame(self.popup, fg_color=CARD, corner_radius=10)
        panel.pack(fill="both", expand=True, padx=10, pady=10)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(10, 8))
        ctk.CTkButton(header, text="<", width=34, height=30, corner_radius=7,
                      fg_color=BORDER, hover_color=ACCENT, text_color=TEXT,
                      command=lambda: self._change_month(-1)).pack(side="left")
        ctk.CTkLabel(header, text=self.visible_month.strftime("%B %Y"),
                     font=("Segoe UI", 13, "bold"), text_color=TEXT).pack(side="left", expand=True)
        ctk.CTkButton(header, text=">", width=34, height=30, corner_radius=7,
                      fg_color=BORDER, hover_color=ACCENT, text_color=TEXT,
                      command=lambda: self._change_month(1)).pack(side="right")

        grid = ctk.CTkFrame(panel, fg_color="transparent")
        grid.pack(padx=10, pady=(0, 8))

        for col, weekday in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
            ctk.CTkLabel(grid, text=weekday, width=35, font=("Segoe UI", 9, "bold"),
                         text_color=SUBTEXT).grid(row=0, column=col, padx=1, pady=(0, 3))

        today = date.today()
        month_days = calendar.monthcalendar(self.visible_month.year, self.visible_month.month)
        for row_index, week in enumerate(month_days, start=1):
            for col, day_num in enumerate(week):
                if day_num == 0:
                    ctk.CTkLabel(grid, text="", width=35, height=30).grid(row=row_index, column=col, padx=1, pady=1)
                    continue

                current = date(self.visible_month.year, self.visible_month.month, day_num)
                is_selected = current == self.selected_date
                is_today = current == today
                ctk.CTkButton(
                    grid, text=str(day_num), width=35, height=30, corner_radius=7,
                    fg_color=ACCENT if is_selected else (MUTED if is_today else INPUT),
                    hover_color="#5349D6", text_color=ON_ACCENT if is_selected else TEXT,
                    font=("Segoe UI", 10, "bold" if is_selected or is_today else "normal"),
                    command=lambda d=current: self._select_from_calendar(d)
                ).grid(row=row_index, column=col, padx=1, pady=1)

    def _change_month(self, delta):
        year = self.visible_month.year
        month = self.visible_month.month + delta
        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1
        self.visible_month = date(year, month, 1)
        self._draw_calendar()

    def _select_from_calendar(self, selected):
        self.set_date(selected, notify=True)
        self._close_popup()

    def _close_popup(self):
        if self.popup and self.popup.winfo_exists():
            self.popup.destroy()
        if self.previous_grab and self.previous_grab.winfo_exists():
            try:
                self.previous_grab.grab_set()
            except Exception:
                pass
        self.previous_grab = None


class AlarmApp(ctk.CTk):
    def __init__(self):
        PROFILER.mark("app_construction_begin")
        # Reading the small settings file is essential, but creating a Tk
        # window first makes that work part of the perceived first paint.
        initial_data = load_data()
        PROFILER.mark("config_data_load_complete")
        super().__init__()
        self.title("TimePulse")
        width, height = 430, 650
        self.geometry(f"{width}x{height}")
        center_window(self, width, height)
        self.minsize(390, 560)
        self.resizable(True, True)

        self.configure(fg_color=BG)
        
        # Set window icon
        apply_window_icon(self)
        PROFILER.mark("root_window_created")

        self.data = initial_data
        self.data_lock = threading.Lock()
        self.audio_manager = AudioManager(self)
        self.hwnd = None
        self.original_wndproc = None
        self._wndproc_cb = None
        self._session_notifications_registered = False
        self._alarm_check_after_id = None
        self._clock_after_id = None
        self._shutting_down = False
        self._instance_mutex_handle = None
        self.tray = None
        self._tray_thread = None
        self._tray_ready = False
        self._tray_starting = False
        self._tray_ready_event = threading.Event()
        self._tray_failed = False
        self._tray_events = queue.Queue()
        self._hide_requested = False
        self.tab_frames = {}
        self._ringtone_path_cache = {}
        self._alarm_render_generation = 0
        self._render_cards_after_id = None
        self.auto_sync_active = True # New: Auto-sync alarm setter with clock
        self.active_alarm_ids = set() # Track alarms currently firing
        self._alarm_check_running = False # Avoid duplicate scheduled loops
        self.new_alarm_popup = None
        self.history_popup = None
        self.hist_container = None
        
        # Expensive integrations start only after the visible shell gets an
        # idle turn. They never gate the first window paint.
        self.protocol("WM_DELETE_WINDOW", self._withdraw_window)

        self._build_header()
        PROFILER.mark("header_created")
        self._build_clock()
        PROFILER.mark("clock_created")
        self._build_tabs()
        PROFILER.mark("tab_navigation_created")
        self._build_alarm_tab()
        PROFILER.mark("alarms_shell_created")
        self._show_tab("alarms", refresh_alarms=False)
        self._start_clock()
        PROFILER.mark("app_construction_complete")
        self.after_idle(self._on_first_idle)

    def _on_first_idle(self):
        """Let Tk draw the shell before populating potentially long card lists."""
        if self._shutting_down:
            return
        PROFILER.mark("first_idle_callback")
        # Start alarm checker immediately so alarm reliability never depends on UI rendering
        self._start_alarm_checker()
        PROFILER.mark("alarm_checker_initialized")
        self._refresh_alarm_list(batch_size=25)
        self.after_idle(self._deferred_startup)

    def _deferred_startup(self):
        if self._shutting_down:
            return
        self._setup_tray()
        self.after_idle(self._initialize_session_notifications)
        threading.Thread(
            target=self._run_background_startup,
            name="TimePulseStartup",
            daemon=True,
        ).start()
        PROFILER.mark("deferred_startup_dispatched")
        self.after(500, self._finish_startup_profile)

    def _initialize_session_notifications(self):
        if self._shutting_down:
            return
        self._setup_session_notifications()
        PROFILER.mark("session_notifications_initialized")

    def _run_background_startup(self):
        """Perform Windows-file and Task Scheduler work outside Tk's thread."""
        PROFILER.mark("auto_start_migration_initialized")
        if not ensure_login_auto_start():
            print(
                "Automatic login startup could not be enabled. "
                "The app will continue running normally."
            )
        run_startup_migration(self.data, self.data_lock)
        PROFILER.mark("auto_start_migration_complete")
        PROFILER.mark("deferred_startup_complete")

    def _finish_startup_profile(self):
        if not PROFILER.enabled or self._shutting_down:
            return
        if self._tray_starting and (time.perf_counter() - _STARTUP_T0) < 5:
            self.after(100, self._finish_startup_profile)
            return
        PROFILER.dump()

    def get_ringtones_dir(self):
        dirs = self.get_ringtone_dirs()
        return dirs[0] if dirs else os.path.join(APP_DIR, "ringtones")

    def get_ringtone_dirs(self):
        candidates = []
        external_dir = os.path.join(executable_dir(), "ringtones")
        bundled_dir = resource_path("ringtones")
        source_dir = os.path.join(APP_DIR, "ringtones")

        for candidate in (external_dir, bundled_dir, source_dir):
            resolved = os.path.realpath(candidate)
            if resolved not in candidates and os.path.isdir(resolved):
                candidates.append(resolved)
        return candidates

    def get_available_ringtones(self):
        ringtones = {}
        for ringtones_dir in self.get_ringtone_dirs():
            try:
                for file in os.listdir(ringtones_dir):
                    valid_name = self.validate_ringtone_filename(file, require_exists=False)
                    if not valid_name:
                        continue
                    full_path = self.resolve_ringtone_path(valid_name)
                    if full_path and os.path.isfile(full_path):
                        ringtones.setdefault(valid_name.lower(), valid_name)
            except Exception as e:
                print(f"Error listing ringtones directory '{ringtones_dir}': {e}")

        return sorted(ringtones.values(), key=lambda name: self.get_friendly_name(name).lower())

    def get_friendly_name(self, filename):
        name_without_ext = os.path.splitext(filename or DEFAULT_RINGTONE)[0]
        return name_without_ext.replace("_", " ")

    def validate_ringtone_filename(self, filename, require_exists=True):
        if not filename or not isinstance(filename, str):
            return None
        if filename != os.path.basename(filename):
            return None
        if os.path.isabs(filename) or filename.startswith(("\\\\", "//")):
            return None
        if any(sep in filename for sep in ("/", "\\")):
            return None
        if os.path.splitext(filename)[1].lower() != ".wav":
            return None
        if require_exists and not self.resolve_ringtone_path(filename):
            return None
        return filename

    def resolve_ringtone_path(self, filename):
        valid_name = self.validate_ringtone_filename(filename, require_exists=False)
        if not valid_name:
            return None

        cache = getattr(self, "_ringtone_path_cache", None)
        if cache is not None and valid_name in cache:
            return cache[valid_name]

        for ringtones_dir in self.get_ringtone_dirs():
            try:
                resolved_dir = os.path.realpath(ringtones_dir)
                resolved_file = os.path.realpath(os.path.join(resolved_dir, valid_name))
                if os.path.commonpath([resolved_dir, resolved_file]) != resolved_dir:
                    continue
                if os.path.isfile(resolved_file):
                    if cache is not None:
                        cache[valid_name] = resolved_file
                    return resolved_file
            except Exception as exc:
                print(f"Error resolving ringtone '{valid_name}': {exc}")
        if cache is not None:
            cache[valid_name] = None
        return None

    def _setup_session_notifications(self):
        if self._session_notifications_registered:
            return
        try:
            self.update_idletasks()
            hwnd = self.winfo_id()
            if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
                print("Failed to setup session notifications: invalid window handle")
                return
            self.hwnd = hwnd

            ctypes.windll.wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
            ctypes.windll.wtsapi32.WTSRegisterSessionNotification.restype = wintypes.BOOL
            if not ctypes.windll.wtsapi32.WTSRegisterSessionNotification(self.hwnd, NOTIFY_FOR_THIS_SESSION):
                print("Failed to register session notifications")
                return
            self._session_notifications_registered = True

            def wnd_proc(hwnd, msg, wparam, lparam):
                if msg == WM_WTSSESSION_CHANGE:
                    session_callback = None
                    if wparam == WTS_SESSION_LOCK:
                        session_callback = self._on_session_lock
                    elif wparam == WTS_SESSION_UNLOCK:
                        session_callback = self._on_session_unlock
                    if session_callback:
                        try:
                            self.after(0, session_callback)
                        except Exception as exc:
                            print(f"Failed to schedule session-change handling: {exc}")
                if self.original_wndproc:
                    return ctypes.windll.user32.CallWindowProcW(self.original_wndproc, hwnd, msg, wparam, lparam)
                return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._wndproc_cb = WNDPROC(wnd_proc)

            try:
                set_window_long = ctypes.windll.user32.SetWindowLongPtrW
            except AttributeError:
                set_window_long = ctypes.windll.user32.SetWindowLongW

            set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            set_window_long.restype = ctypes.c_void_p
            ctypes.windll.user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
            ctypes.windll.user32.CallWindowProcW.restype = LRESULT
            ctypes.windll.user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]
            ctypes.windll.user32.DefWindowProcW.restype = LRESULT

            self.original_wndproc = set_window_long(self.hwnd, GWL_WNDPROC, ctypes.cast(self._wndproc_cb, ctypes.c_void_p))
        except Exception as e:
            print(f"Failed to setup session notifications: {e}")
            self._cleanup_session_notifications()

    def _cleanup_session_notifications(self):
        try:
            if self.hwnd and ctypes.windll.user32.IsWindow(self.hwnd):
                if self.original_wndproc:
                    try:
                        set_window_long = ctypes.windll.user32.SetWindowLongPtrW
                    except AttributeError:
                        set_window_long = ctypes.windll.user32.SetWindowLongW
                    set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
                    set_window_long.restype = ctypes.c_void_p
                    set_window_long(self.hwnd, GWL_WNDPROC, self.original_wndproc)
                    self.original_wndproc = None

                if self._session_notifications_registered:
                    ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
                    ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification.restype = wintypes.BOOL
                    ctypes.windll.wtsapi32.WTSUnRegisterSessionNotification(self.hwnd)
                    self._session_notifications_registered = False
        except Exception as e:
            print(f"Failed to cleanup session notifications: {e}")
        finally:
            self._wndproc_cb = None

    def _on_session_lock(self):
        """Stop transient audio only; a workstation lock is not an app exit."""
        if self._shutting_down:
            return
        if hasattr(self, 'audio_manager'):
            self.audio_manager.stop_all()

    def _on_session_unlock(self):
        """Restore non-native runtime services after a session transition."""
        if self._shutting_down:
            return
        self._ensure_alarm_checker_running()
        if not self._session_notifications_registered:
            self._setup_session_notifications()

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=50)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        
        txt_grp = ctk.CTkFrame(hdr, fg_color="transparent")
        txt_grp.pack(side="left", padx=(16, 0), pady=7)
        ctk.CTkLabel(txt_grp, text="TimePulse", font=("Segoe UI Black", 14, "bold"), text_color=TEXT).pack(anchor="w")
        
        dev_lbl = ctk.CTkFrame(txt_grp, fg_color="transparent")
        dev_lbl.pack(anchor="w")
        ctk.CTkLabel(dev_lbl, text="Developed by ", font=("Segoe UI", 8), text_color=SUBTEXT).pack(side="left")
        ctk.CTkLabel(dev_lbl, text="Muhammad Khubaib Adeel", font=("Segoe UI", 8, "bold"), text_color=SUBTEXT).pack(side="left")
        
        # Theme Toggle (Default Light mode icon is sun)
        self.theme_btn = ctk.CTkButton(hdr, text="Light", width=62, height=30, corner_radius=7,
                                       fg_color=BORDER, hover_color=ACCENT, text_color=TEXT,
                                       font=("Segoe UI", 11, "bold"), command=self._toggle_theme)
        self.theme_btn.pack(side="right", padx=16)

    def _toggle_theme(self):
        if ctk.get_appearance_mode() == "Dark":
            ctk.set_appearance_mode("Light")
            self.theme_btn.configure(text="Light")
        else:
            ctk.set_appearance_mode("Dark")
            self.theme_btn.configure(text="Dark")

    def _setup_tray(self):
        if self._shutting_down or self._tray_ready:
            return self._tray_ready
        if self._tray_starting:
            return False
        if not ICON_PATH:
            print("System tray icon disabled because no icon file was found.")
            return False

        # pystray and Pillow are intentionally imported inside the worker. A
        # slow tray backend must never freeze CustomTkinter's event loop.
        PROFILER.mark("tray_initialization_start")
        self._tray_starting = True
        self._tray_failed = False
        self._tray_ready_event.clear()

        def run_tray():
            tray = None
            image = None
            try:
                import pystray
                from PIL import Image

                image = Image.open(ICON_PATH)
                menu = pystray.Menu(
                    pystray.MenuItem("Show", self._show_window, default=True),
                    pystray.MenuItem("Exit", self._quit_app),
                )
                tray = pystray.Icon("TimePulse", image, "TimePulse Alarm", menu)

                def tray_setup(icon):
                    if self._shutting_down:
                        icon.stop()
                        return
                    icon.visible = True
                    self._tray_ready_event.set()
                    self._tray_events.put(("ready", tray, image))

                tray.run(setup=tray_setup)
            except Exception as exc:
                self._tray_ready_event.set()
                self._tray_events.put(("failed", None, None))
                print(f"Tray error: {exc}")

        self._tray_thread = threading.Thread(
            target=run_tray, name="TimePulseTray", daemon=False
        )
        self._tray_thread.start()
        self.after(50, self._poll_tray_events)
        return False

    def _poll_tray_events(self):
        """Apply worker results on Tk's thread without waiting for the tray."""
        if self._shutting_down:
            return
        try:
            while True:
                status, tray, image = self._tray_events.get_nowait()
                self._tray_starting = False
                if status == "ready":
                    self.tray = tray
                    self._tray_image = image
                    self._tray_ready = True
                    PROFILER.mark("tray_initialization_complete")
                    if self._hide_requested:
                        self.withdraw()
                else:
                    self._tray_failed = True
                    self.tray = None
                    self._tray_ready = False
                    if self._hide_requested:
                        self._hide_requested = False
                        self.deiconify()
                        self.lift()
        except queue.Empty:
            pass
        if self._tray_starting:
            if self._tray_thread and not self._tray_thread.is_alive():
                self._tray_starting = False
                self._tray_failed = True
                self._tray_ready = False
                if self._hide_requested:
                    self._hide_requested = False
                    self.deiconify()
                    self.lift()
            else:
                self.after(50, self._poll_tray_events)

    def _withdraw_window(self):
        if hasattr(self, 'audio_manager'):
            self.audio_manager.stop_preview()
        if self._tray_ready:
            self._hide_requested = True
            self.withdraw()
            return
        self._hide_requested = True
        if not self._setup_tray() and not self._tray_starting:
            self._hide_requested = False
            self.deiconify()
            self.lift()

    def _show_window(self):
        def restore_window():
            if self._shutting_down or not self.winfo_exists():
                return
            self._hide_requested = False
            self.deiconify()
            self.lift()
            self.focus_force()

        try:
            self.after(0, restore_window)
        except Exception:
            pass

    def _quit_app(self):
        try:
            self.after(0, self._quit_app_main_thread)
        except Exception:
            self._stop_tray_for_shutdown()

    def _quit_app_main_thread(self):
        if self._shutting_down:
            return
        self._shutdown_cleanup()
        self._stop_tray_for_shutdown()
        self.destroy()

    def _stop_tray_for_shutdown(self):
        """Stop and join the one native tray loop before Tk is destroyed."""
        tray = self.tray
        tray_thread = self._tray_thread
        try:
            if tray:
                tray.stop()
        except Exception as exc:
            print(f"Failed to stop tray: {exc}")
        finally:
            if tray_thread and tray_thread is not threading.current_thread():
                tray_thread.join(timeout=2)
            self.tray = None
            self._tray_ready = False
            self._tray_thread = None

    def _shutdown_cleanup(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        for timer_id in (
            self._alarm_check_after_id,
            self._clock_after_id,
            getattr(self, "_render_cards_after_id", None),
        ):
            if timer_id:
                try:
                    self.after_cancel(timer_id)
                except Exception as exc:
                    print(f"Failed to cancel scheduled callback: {exc}")
        self._alarm_check_after_id = None
        self._clock_after_id = None
        self._render_cards_after_id = None
        if hasattr(self, 'audio_manager'):
            self.audio_manager.stop_all()

        if self.new_alarm_popup and self.new_alarm_popup.winfo_exists():
            self._close_new_alarm_popup()
        if self.history_popup and self.history_popup.winfo_exists():
            self._close_history_popup()

        self._cleanup_session_notifications()


    def _build_clock(self):
        cf = ctk.CTkFrame(self, fg_color=CARD, corner_radius=11)
        cf.pack(fill="x", padx=16, pady=(10, 0))
        self.clock_lbl = ctk.CTkLabel(cf, text="12:00:00 AM", font=("Segoe UI Black", 32, "bold"), text_color=ACCENT)
        self.clock_lbl.pack(pady=(10, 0))
        self.date_lbl  = ctk.CTkLabel(cf, text="", font=("Segoe UI", 11, "bold"), text_color=SUBTEXT)
        self.date_lbl.pack(pady=(0, 7))

        # Next Alarm Summary Label
        self.next_alarm_lbl = ctk.CTkLabel(cf, text="No upcoming alarms", font=("Segoe UI", 11, "bold"), text_color=ACCENT2)
        self.next_alarm_lbl.pack(pady=(0, 10))

    def _start_clock(self):
        if self._shutting_down:
            return
        now = datetime.now()
        self.clock_lbl.configure(text=now.strftime("%I:%M:%S %p"))
        self.date_lbl.configure(text=now.strftime("%A, %d %B %Y"))
        self._update_next_alarm_summary()
        
        # New: Auto-sync alarm setter if active
        if self.auto_sync_active:
            self._sync_setter_to_now()
            
        self._clock_after_id = self.after(1000, self._start_clock)

    def _update_next_alarm_summary(self):
        now = datetime.now()
        next_alarm = None
        min_diff = float('inf')

        with self.data_lock:
            alarms = list(self.data.get("alarms", []))

        for alarm in alarms:
            if not alarm.get("enabled", True):
                continue

            dt_str = alarm.get("datetime")
            if dt_str:
                alarm_dt = parse_alarm_datetime(dt_str)
            else:
                ah, am = map(int, alarm["time"].split(":"))
                alarm_dt = now.replace(hour=ah, minute=am, second=0, microsecond=0)
                if alarm_dt <= now:
                    alarm_dt += timedelta(days=1)

            if not alarm_dt or alarm_dt <= now:
                continue

            diff = (alarm_dt - now).total_seconds()
            if diff < min_diff:
                min_diff = diff
                next_alarm = alarm_dt

        if next_alarm:
            hours = int(min_diff // 3600)
            minutes = int((min_diff % 3600) // 60)
            seconds = int(min_diff % 60)

            if next_alarm.date() == now.date():
                time_str = f"Next alarm: Today {next_alarm.strftime('%I:%M %p')}, in "
            else:
                time_str = f"Next alarm: {next_alarm.strftime('%d %b, %I:%M %p')}, in "

            if hours > 0:
                time_str += f"{hours}h {minutes}m {seconds}s"
            else:
                time_str += f"{minutes}m {seconds}s"
            self.next_alarm_lbl.configure(text=time_str)

            # Update Tray Tooltip
            if self.tray and self._tray_ready:
                try:
                    tray_msg = f"TimePulse: Next alarm in {int(min_diff // 60)} minutes"
                    self.tray.title = tray_msg
                except Exception:
                    pass
        else:
            self.next_alarm_lbl.configure(text="No upcoming alarms")
            if self.tray and self._tray_ready:
                try:
                    self.tray.title = "TimePulse: No alarms"
                except Exception:
                    pass
    def _build_tabs(self):
        bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10, height=42)
        bar.pack(fill="x", padx=16, pady=(8, 0)); bar.pack_propagate(False)
        bar.grid_columnconfigure((0, 1, 2), weight=1, uniform="tabs")
        
        self.tab_btns = {}
        tabs = [("Alarms", "alarms"), ("Timers", "timers"), ("Settings", "settings")]
        for i, (label, key) in enumerate(tabs):
            b = ctk.CTkButton(bar, text=label, font=("Segoe UI", 12, "bold"),
                              fg_color="transparent", text_color=SUBTEXT,
                              hover_color=BORDER, corner_radius=8, height=32,
                              command=lambda k=key: self._show_tab(k))
            b.grid(row=0, column=i, sticky="ew", padx=4, pady=4)
            self.tab_btns[key] = b

    def _show_tab(self, key, refresh_alarms=True):
        if key == "timers" and key not in self.tab_frames:
            self._build_timer_tab()
            PROFILER.mark("timers_tab_created")
        elif key == "settings" and key not in self.tab_frames:
            self._build_settings_tab()
            PROFILER.mark("settings_tab_created")

        for k, f in self.tab_frames.items():
            if k == key:
                f.pack(fill="both", expand=True, padx=16, pady=8)
                self.tab_btns[k].configure(fg_color=ACCENT, text_color=ON_ACCENT)
            else:
                f.pack_forget()
                self.tab_btns[k].configure(fg_color="transparent", text_color=SUBTEXT)
        if key == "alarms" and refresh_alarms:
            self._refresh_alarm_list()
        elif key == "settings":
            self._refresh_password_controls()
    # ---------------- Alarms Tab ----------------
    def _build_alarm_tab(self):
        f = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_frames["alarms"] = f

        action_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=12)
        action_card.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            action_card,
            text="Alarm Actions",
            font=("Segoe UI", 13, "bold"),
            text_color=TEXT
        ).pack(pady=(12, 8))

        button_row = ctk.CTkFrame(action_card, fg_color="transparent")
        button_row.pack(fill="x", padx=14, pady=(0, 12))
        button_row.grid_columnconfigure((0, 1), weight=1, uniform="alarm_actions")

        ctk.CTkButton(
            button_row,
            text="Create New",
            height=38,
            corner_radius=8,
            fg_color=ACCENT,
            hover_color="#3730A3",
            text_color=ON_ACCENT,
            font=("Segoe UI", 12, "bold"),
            command=self._open_new_alarm_popup
        ).grid(row=0, column=0, sticky="ew", padx=(0, 5))

        ctk.CTkButton(
            button_row,
            text="Alarm History",
            height=38,
            corner_radius=8,
            fg_color=BORDER,
            hover_color=ACCENT,
            text_color=TEXT,
            font=("Segoe UI", 12, "bold"),
            command=self._open_history_popup
        ).grid(row=0, column=1, sticky="ew", padx=(5, 0))

        ctk.CTkLabel(
            f,
            text="Active Alarms",
            font=("Segoe UI", 12, "bold"),
            text_color=SUBTEXT
        ).pack(anchor="w", pady=(1, 4))

        self.alarm_scroll = ctk.CTkScrollableFrame(
            f,
            fg_color="transparent",
            scrollbar_button_color=BORDER
        )
        self.alarm_scroll.pack(fill="both", expand=True)

    def _open_new_alarm_popup(self):
        if self.new_alarm_popup and self.new_alarm_popup.winfo_exists():
            self.new_alarm_popup.deiconify()
            self.new_alarm_popup.lift()
            self.new_alarm_popup.focus_force()
            return

        self.auto_sync_active = True
        popup = ctk.CTkToplevel(self)
        apply_window_icon(popup)
        self.new_alarm_popup = popup
        popup.title("Create New Alarm")
        popup.configure(fg_color=BG)
        popup.geometry("410x475")
        popup.minsize(390, 450)
        popup.resizable(False, False)
        popup.transient(self)
        popup.attributes("-topmost", True)
        popup.protocol("WM_DELETE_WINDOW", self._close_new_alarm_popup)
        center_window(popup, 410, 475)

        add_card = ctk.CTkFrame(popup, fg_color=CARD, corner_radius=12)
        add_card.pack(fill="both", expand=True, padx=14, pady=14)

        header = ctk.CTkFrame(add_card, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(
            header,
            text="New Alarm",
            font=("Segoe UI", 15, "bold"),
            text_color=TEXT
        ).pack(side="left")
        ctk.CTkButton(
            header,
            text="X",
            width=32,
            height=30,
            corner_radius=7,
            fg_color=BORDER,
            hover_color=DANGER,
            text_color=TEXT,
            font=("Segoe UI", 11, "bold"),
            command=self._close_new_alarm_popup
        ).pack(side="right")

        row = ctk.CTkFrame(add_card, fg_color="transparent")
        row.pack(padx=14, pady=(0, 8), anchor="w")

        self.hour_var = ctk.StringVar(value="07")
        self.min_var = ctk.StringVar(value="00")
        self.ampm_var = ctk.StringVar(value="AM")

        ctk.CTkLabel(
            row, text="Hour", font=("Segoe UI", 9, "bold"), text_color=SUBTEXT
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            row, text="Minute", font=("Segoe UI", 9, "bold"), text_color=SUBTEXT
        ).grid(row=0, column=2, sticky="w")

        now = datetime.now()
        h12, minute, ampm = to_12h(now.strftime("%H:%M"))

        self.hour_cb = NumberStepper(
            row, 1, 12, h12, width=92, height=34,
            command=self._on_user_interaction
        )
        self.hour_cb.grid(row=1, column=0)

        ctk.CTkLabel(
            row, text=":", font=("Segoe UI Black", 22), text_color=ACCENT
        ).grid(row=1, column=1, padx=5)

        self.min_cb = NumberStepper(
            row, 0, 59, minute, width=92, height=34,
            command=self._on_user_interaction
        )
        self.min_cb.grid(row=1, column=2)

        self.ampm_menu = ctk.CTkOptionMenu(
            row,
            values=["AM", "PM"],
            width=68,
            height=34,
            variable=self.ampm_var,
            fg_color=INPUT,
            button_color=ACCENT,
            button_hover_color="#5349D6",
            dropdown_fg_color=CARD,
            dropdown_hover_color=BORDER,
            dropdown_text_color=TEXT,
            text_color=TEXT,
            corner_radius=7,
            command=lambda _: self._on_user_interaction()
        )
        self.ampm_menu.grid(row=1, column=3, padx=(9, 0))
        self.ampm_var.set(ampm)

        date_row = ctk.CTkFrame(add_card, fg_color="transparent")
        date_row.pack(padx=14, pady=(0, 6), fill="x")
        ctk.CTkLabel(
            date_row, text="Date", font=("Segoe UI", 9, "bold"), text_color=SUBTEXT
        ).pack(anchor="w")

        self.date_var = ctk.StringVar(value=now.strftime("%Y-%m-%d"))
        self.date_picker = DatePickerField(
            date_row,
            self.date_var,
            command=self._on_user_interaction
        )
        self.date_picker.pack(fill="x", pady=(3, 0))

        rt_row = ctk.CTkFrame(add_card, fg_color="transparent")
        rt_row.pack(padx=14, pady=(0, 6), fill="x")
        ctk.CTkLabel(
            rt_row, text="Ringtone", font=("Segoe UI", 9, "bold"), text_color=SUBTEXT
        ).pack(anchor="w")

        self.ringtone_var = ctk.StringVar(value=DEFAULT_RINGTONE)
        self.ringtone_selector = RingtoneSelector(
            rt_row,
            self.ringtone_var.get(),
            lambda value: self.ringtone_var.set(value),
            self.audio_manager
        )
        self.ringtone_selector.pack(fill="x", pady=(3, 0))

        self.label_var = ctk.StringVar(value="")
        ctk.CTkEntry(
            add_card,
            textvariable=self.label_var,
            placeholder_text="Label (optional)",
            fg_color=INPUT,
            border_color=BORDER,
            text_color=TEXT,
            placeholder_text_color=SUBTEXT,
            font=("Segoe UI", 12),
            height=34
        ).pack(fill="x", padx=14, pady=(1, 0))

        ctk.CTkButton(
            add_card,
            text="Set Alarm",
            font=("Segoe UI", 12, "bold"),
            fg_color=ACCENT,
            hover_color="#3730A3",
            text_color=ON_ACCENT,
            corner_radius=8,
            height=38,
            command=self._add_alarm
        ).pack(fill="x", padx=14, pady=(10, 14))

        popup.after(50, popup.grab_set)

    def _close_new_alarm_popup(self):
        self.audio_manager.stop_preview()

        popup = self.new_alarm_popup
        self.new_alarm_popup = None

        if popup and popup.winfo_exists():
            try:
                popup.grab_release()
            except Exception:
                pass
            popup.destroy()

        for name in (
            "hour_cb", "min_cb", "ampm_menu", "date_picker",
            "ringtone_selector", "hour_var", "min_var", "ampm_var",
            "date_var", "ringtone_var", "label_var"
        ):
            if hasattr(self, name):
                try:
                    delattr(self, name)
                except Exception:
                    pass

    def _open_history_popup(self):
        if self.history_popup and self.history_popup.winfo_exists():
            self.history_popup.deiconify()
            self.history_popup.lift()
            self.history_popup.focus_force()
            self._refresh_history()
            return

        popup = ctk.CTkToplevel(self)
        apply_window_icon(popup)
        self.history_popup = popup
        popup.title("Alarm History")
        popup.configure(fg_color=BG)
        popup.geometry("410x500")
        popup.minsize(380, 420)
        popup.resizable(True, True)
        popup.transient(self)
        popup.attributes("-topmost", True)
        popup.protocol("WM_DELETE_WINDOW", self._close_history_popup)
        center_window(popup, 410, 500)

        card = ctk.CTkFrame(popup, fg_color=CARD, corner_radius=12)
        card.pack(fill="both", expand=True, padx=14, pady=14)

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 8))

        ctk.CTkLabel(
            header,
            text="Alarm History",
            font=("Segoe UI", 15, "bold"),
            text_color=TEXT
        ).pack(side="left")

        button_group = ctk.CTkFrame(header, fg_color="transparent")
        button_group.pack(side="right")

        ctk.CTkButton(
            button_group,
            text="Close",
            width=64,
            height=32,
            corner_radius=7,
            fg_color=BORDER,
            hover_color=ACCENT,
            text_color=TEXT,
            font=("Segoe UI", 10, "bold"),
            command=self._close_history_popup
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            button_group,
            text="Delete History",
            width=112,
            height=32,
            corner_radius=7,
            fg_color=BORDER,
            hover_color=DANGER,
            text_color=TEXT,
            font=("Segoe UI", 10, "bold"),
            command=self._delete_history_with_auth
        ).pack(side="left")

        self.hist_container = ctk.CTkScrollableFrame(
            card,
            fg_color="transparent",
            scrollbar_button_color=BORDER
        )
        self.hist_container.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        self._refresh_history()
        popup.after(50, popup.grab_set)

    def _close_history_popup(self):
        popup = self.history_popup
        self.history_popup = None
        self.hist_container = None

        if popup and popup.winfo_exists():
            try:
                popup.grab_release()
            except Exception:
                pass
            popup.destroy()

    def _on_user_interaction(self):
        self.auto_sync_active = False

    def _sync_setter_to_now(self):
        if not (
            self.new_alarm_popup
            and self.new_alarm_popup.winfo_exists()
            and hasattr(self, "hour_cb")
            and hasattr(self, "min_cb")
            and hasattr(self, "ampm_var")
        ):
            return

        now = datetime.now()
        h12, minute, ampm = to_12h(now.strftime("%H:%M"))
        if self.hour_cb.get() != h12:
            self.hour_cb.set(h12)
        if self.min_cb.get() != minute:
            self.min_cb.set(minute)
        if self.ampm_var.get() != ampm:
            self.ampm_var.set(ampm)
        if hasattr(self, "date_picker"):
            self.date_picker.set_date(now.date())

    def _add_timer_alarm(self, minutes):
        target = datetime.now() + timedelta(minutes=minutes)
        date_str = target.strftime("%Y-%m-%d")
        time_str = target.strftime("%H:%M")
        dt_str = target.strftime("%Y-%m-%dT%H:%M:00")
        
        alarm = {
            "id": str(uuid.uuid4()),
            "date": date_str,
            "time": time_str,
            "datetime": dt_str,
            "label": f"{minutes}m Timer",
            "enabled": True,
            "repeat": "none",
            "status": "scheduled",
            "ringtone": "Soft_Arrival.wav",
            "created_at": datetime.now().isoformat()
        }
        
        with self.data_lock:
            self.data["alarms"].append(alarm)
            save_data(self.data)
            self._log_event(alarm, "Created")
        messagebox.showinfo("Timer Set", f"Alarm set for {target.strftime('%Y-%m-%d %I:%M %p')}")
        self._refresh_alarm_list()

    def _refresh_alarm_list(self, batch_size=None):
        """Render cards separately from alarm scheduling/checking.

        ``batch_size`` is only used at initial startup. It lets a large saved
        alarm list remain responsive while the checker is already active.
        """
        self._alarm_render_generation += 1
        generation = self._alarm_render_generation
        for w in self.alarm_scroll.winfo_children():
            w.destroy()
        with self.data_lock:
            self.data["alarms"] = sort_alarms(self.data.get("alarms", []))
            alarms = list(self.data["alarms"])
        if not alarms:
            empty_f = ctk.CTkFrame(self.alarm_scroll, fg_color="transparent")
            empty_f.pack(pady=40, expand=True)
            ctk.CTkLabel(empty_f, text="No alarms", font=("Segoe UI Black", 24, "bold"), text_color=TEXT).pack()
            ctk.CTkLabel(empty_f, text="No alarms set yet.\nStart by creating one above!",
                         font=("Segoe UI", 14), text_color=SUBTEXT, justify="center").pack(pady=10)
            PROFILER.mark("alarm_cards_rendered")
            return

        self._render_alarm_cards(alarms, generation, batch_size)

    def _render_alarm_cards(self, alarms, generation, batch_size=None, start=0):
        if self._shutting_down or generation != self._alarm_render_generation:
            return
        if not self.winfo_exists() or not self.alarm_scroll.winfo_exists():
            return
        end = len(alarms) if not batch_size else min(start + batch_size, len(alarms))
        for alarm in alarms[start:end]:
            self._alarm_card(self.alarm_scroll, alarm)
        if end < len(alarms):
            self._render_cards_after_id = self.after(1, lambda: self._render_alarm_cards(
                alarms, generation, batch_size, end
            ))
            return
        self._render_cards_after_id = None
        PROFILER.mark("alarm_cards_rendered")

    def _alarm_card(self, parent, alarm):
        enabled = alarm.get("enabled", True)
        alarm_id = alarm["id"]
        card = ctk.CTkFrame(
            parent,
            fg_color=CARD if enabled else MUTED,
            corner_radius=8,
            border_width=1,
            border_color=BORDER
        )
        card.pack(fill="x", pady=3)

        left = ctk.CTkFrame(card, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(12, 6), pady=7)
        h_s, m_s, ampm = to_12h(alarm["time"])
        
        dt_obj = parse_alarm_datetime(alarm.get("datetime"))
        date_display = dt_obj.strftime("%d %b %Y") if dt_obj else alarm.get("date", "")

        time_row = ctk.CTkFrame(left, fg_color="transparent")
        time_row.pack(anchor="w")
        ctk.CTkLabel(time_row, text=f"{h_s}:{m_s} {ampm}",
                     font=("Segoe UI Black", 18, "bold"),
                     text_color=ACCENT if enabled else SUBTEXT).pack(side="left")
        if date_display:
            ctk.CTkLabel(time_row, text=f"  {date_display}",
                         font=("Segoe UI", 10, "bold"),
                         text_color=SUBTEXT).pack(side="left", padx=(6, 0), pady=(4, 0))

        # Long label fix: truncate label if it's too long
        label_text = alarm.get("label","") or "Alarm"
        if len(label_text) > 34:
            label_text = label_text[:31] + "..."
            
        rt_name = self.get_friendly_name(self.validate_ringtone_filename(alarm.get("ringtone", DEFAULT_RINGTONE)) or DEFAULT_RINGTONE)
        ctk.CTkLabel(left, text=f"{label_text}  •  🎵 {rt_name}",
                     font=("Segoe UI", 11), text_color=SUBTEXT).pack(anchor="w", pady=(1, 0))

        right = ctk.CTkFrame(card, fg_color="transparent")
        right.pack(side="right", padx=(0, 10), pady=8)

        # Toggle Switch
        switch_var = ctk.BooleanVar(value=enabled)
        tog = ctk.CTkSwitch(right, text="", variable=switch_var, width=34,
                            progress_color=SUCCESS,
                            command=lambda aid=alarm_id, v=switch_var: self._auth_then(self._toggle_alarm, aid, v))
        tog.pack(side="left", padx=(0, 6))

        ctk.CTkButton(right, text="Edit", width=50, height=30, corner_radius=7,
                      fg_color=BORDER, hover_color=ACCENT, text_color=TEXT,
                      font=("Segoe UI", 10, "bold"),
                      command=lambda aid=alarm_id: self._edit_with_auth(aid)
                      ).pack(side="left", padx=3)
        ctk.CTkButton(right, text="X", width=32, height=30, corner_radius=7,
                      fg_color=BORDER, hover_color=DANGER, text_color=TEXT,
                      font=("Segoe UI", 11, "bold"),
                      command=lambda aid=alarm_id: self._delete_with_auth(aid)
                      ).pack(side="left", padx=3)

    def _delete_with_auth(self, alarm_id):
        if requires_alarm_change_auth(self.data.get("protect_edit_delete")):
            self._auth_then(
                self._delete_alarm,
                alarm_id,
                message="Secure deletion requires your configured password.",
            )
        else:
            self._delete_alarm(alarm_id)

    def _edit_with_auth(self, alarm_id):
        if requires_alarm_change_auth(self.data.get("protect_edit_delete")):
            self._auth_then(self._edit_alarm, alarm_id)
        else:
            self._edit_alarm(alarm_id)

    def _delete_history_with_auth(self):
        self._auth_then(
            self._delete_history,
            message="Secure deletion requires your configured password.",
        )

    def _delete_history(self):
        try:
            if os.path.exists(HISTORY_FILE):
                os.remove(HISTORY_FILE)
            self._refresh_history()
            messagebox.showinfo("Success", "Alarm history deleted successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete history: {e}")
    def _add_alarm(self):
        try:
            h = int(self.hour_cb.get()); m = int(self.min_cb.get())
            assert 1 <= h <= 12 and 0 <= m <= 59
            
            date_str = self.date_var.get().strip()
            # Validate date format
            datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            messagebox.showerror("Invalid Input", "Please choose a valid date and time.")
            return

        h24, m24 = to_24h(h, m, self.ampm_var.get())
        time_str = f"{h24:02d}:{m24:02d}"
        dt_str = build_alarm_datetime(date_str, time_str)
        alarm_dt = parse_alarm_datetime(dt_str)
        
        if alarm_dt <= datetime.now():
            messagebox.showerror("Invalid Date/Time", "Alarm must be set in the future.")
            return

        rt_file = self.validate_ringtone_filename(self.ringtone_var.get()) or DEFAULT_RINGTONE
        alarm = {
            "id": str(uuid.uuid4()),
            "date": date_str,
            "time": time_str,
            "datetime": dt_str,
            "label": self.label_var.get().strip(),
            "enabled": True,
            "repeat": "none",
            "status": "scheduled",
            "ringtone": rt_file,
            "created_at": datetime.now().isoformat()
        }
        with self.data_lock:
            self.data["alarms"].append(alarm)
            save_data(self.data)
            self._log_event(alarm, "Created")
        self.label_var.set("")
        self.ringtone_var.set(DEFAULT_RINGTONE)
        self.ringtone_selector.set_value(DEFAULT_RINGTONE)
        self._refresh_alarm_list()
        self._close_new_alarm_popup()

    def _auth_then(self, callback, *args, message=None, on_cancel=None):
        # Skip if password is disabled.
        if self.data.get("password") is None:
            callback(*args)
            return

        dialog_options = {
            "on_password_upgraded": self._upgrade_password_hash,
        }
        if message is not None:
            dialog_options["message"] = message

        # CustomTkinter updates a switch before its command runs, so preserve
        # the existing alarm-toggle rollback behavior when no callback is given.
        if on_cancel is None and callback == self._toggle_alarm and len(args) > 1:
            switch_var = args[1]
            on_cancel = lambda: switch_var.set(not switch_var.get())

        PwDialog(
            self,
            self.data["password"],
            lambda: callback(*args),
            on_cancel,
            **dialog_options,
        )

    def _upgrade_password_hash(self, upgraded_hash):
        with self.data_lock:
            current_hash = self.data.get("password")
            if _is_legacy_sha256_hash(current_hash):
                self.data["password"] = upgraded_hash
                save_data(self.data)

    def _verify_configured_password(self, password):
        current_hash = self.data.get("password")
        if not verify_password(password, current_hash):
            return False

        if _is_legacy_sha256_hash(current_hash):
            self._upgrade_password_hash(hash_password(password))
        return True

    def _find_alarm_by_id(self, alarm_id):
        with self.data_lock:
            for alarm in self.data.get("alarms", []):
                if alarm.get("id") == alarm_id:
                    return alarm
        return None

    def _find_alarm_index_by_id(self, alarm_id):
        with self.data_lock:
            for i, alarm in enumerate(self.data.get("alarms", [])):
                if alarm.get("id") == alarm_id:
                    return i
        return -1

    def _delete_alarm(self, alarm_id):
        with self.data_lock:
            for alarm in list(self.data.get("alarms", [])):
                if alarm.get("id") == alarm_id:
                    if alarm_id in self.active_alarm_ids:
                        self.audio_manager.stop_alarm()
                        self.active_alarm_ids.discard(alarm_id)
                    self.data["alarms"].remove(alarm)
                    save_data(self.data)
                    self._log_event(alarm, "Deleted")
                    break
        self._refresh_alarm_list()

    def _toggle_alarm(self, alarm_id, switch_var=None):
        with self.data_lock:
            for alarm in list(self.data.get("alarms", [])):
                if alarm.get("id") == alarm_id:
                    alarm["enabled"] = not alarm.get("enabled", True)
                    if not alarm["enabled"] and alarm_id in self.active_alarm_ids:
                        self.audio_manager.stop_alarm()
                        self.active_alarm_ids.discard(alarm_id)
                    save_data(self.data)
                    status = "Enabled" if alarm["enabled"] else "Disabled"
                    self._log_event(alarm, f"Toggled {status}")
                    break
        self._refresh_alarm_list()

    def _edit_alarm(self, alarm_id):
        EditDialog(self, self.data, alarm_id)

    def _build_timer_tab(self):
        f = ctk.CTkFrame(self, fg_color="transparent")
        self.tab_frames["timers"] = f
        
        card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=12)
        card.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(card, text="Quick Timers", font=("Segoe UI", 13, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 5))
        
        # Grid layout for a cleaner look in its own tab
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 10))
        
        durations = [5, 10, 15, 20, 25, 30, 35, 40, 45, 60]
        for i, mins in enumerate(durations):
            btn = ctk.CTkButton(grid, text=f"{mins} min", height=36,
                                fg_color=BORDER, text_color=TEXT, hover_color=ACCENT,
                                font=("Segoe UI", 12, "bold"), corner_radius=8,
                                command=lambda m=mins: self._add_timer_alarm(m))
            btn.grid(row=i//2, column=i%2, padx=4, pady=4, sticky="ew")
        grid.columnconfigure((0, 1), weight=1)
    # ---------------- Settings Tab ----------------
    def _build_settings_tab(self):
        f = ctk.CTkScrollableFrame(self, fg_color="transparent", scrollbar_button_color=BORDER)
        self.tab_frames["settings"] = f

        card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=12)
        card.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(card, text="Manage Password", font=("Segoe UI", 13, "bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 3))
        self.password_help_lbl = ctk.CTkLabel(
            card, text="", font=("Segoe UI", 10), text_color=SUBTEXT
        )
        self.password_help_lbl.pack(anchor="w", padx=14)
        
        self.old_pw = ctk.CTkEntry(card, placeholder_text="Current password", show="*",
                                   fg_color=INPUT, border_color=BORDER, text_color=TEXT,
                                   placeholder_text_color=SUBTEXT, font=("Segoe UI", 12), height=34)
        self.old_pw.pack(fill="x", padx=14, pady=(7,3))
        self.new_pw = ctk.CTkEntry(card, placeholder_text="New password (minimum 6 characters)", show="*",
                                   fg_color=INPUT, border_color=BORDER, text_color=TEXT,
                                   placeholder_text_color=SUBTEXT, font=("Segoe UI", 12), height=34)
        self.new_pw.pack(fill="x", padx=14, pady=(0,3))
        self.confirm_pw = ctk.CTkEntry(card, placeholder_text="Confirm new password", show="*",
                                       fg_color=INPUT, border_color=BORDER, text_color=TEXT,
                                       placeholder_text_color=SUBTEXT, font=("Segoe UI", 12), height=34)
        self.confirm_pw.pack(fill="x", padx=14, pady=(0,7))
        
        btn_f = ctk.CTkFrame(card, fg_color="transparent")
        btn_f.pack(fill="x", padx=14, pady=(0,10))
        self.password_update_btn = ctk.CTkButton(
            btn_f, text="Update Password", font=("Segoe UI", 11, "bold"),
            fg_color=ACCENT, hover_color="#3730A3", text_color=ON_ACCENT,
            corner_radius=8, height=34, command=self._change_password
        )
        self.password_update_btn.pack(side="left", expand=True, fill="x", padx=(0,4))
        self.password_remove_btn = ctk.CTkButton(
            btn_f, text="Remove Password", font=("Segoe UI", 11, "bold"),
            fg_color=BORDER, hover_color=DANGER, corner_radius=8, height=34,
            command=self._remove_password
        )
        self.password_remove_btn.pack(side="left", expand=True, fill="x", padx=(4,0))
        self._refresh_password_controls()

        protection_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=12)
        protection_card.pack(fill="x", pady=(0, 8))
        protection_text = ctk.CTkFrame(protection_card, fg_color="transparent")
        protection_text.pack(side="left", fill="x", expand=True, padx=14, pady=10)
        ctk.CTkLabel(
            protection_text,
            text="Password Protect Edit & Delete",
            font=("Segoe UI", 13, "bold"),
            text_color=TEXT,
        ).pack(anchor="w")
        ctk.CTkLabel(
            protection_text,
            text="Require your password before editing or deleting alarms.",
            font=("Segoe UI", 10),
            text_color=SUBTEXT,
        ).pack(anchor="w", pady=(3, 0))
        self.protect_edit_delete_var = ctk.BooleanVar(
            value=self.data.get(
                "protect_edit_delete", DEFAULT_PROTECT_EDIT_DELETE
            )
        )
        ctk.CTkSwitch(
            protection_card,
            text="",
            variable=self.protect_edit_delete_var,
            progress_color=SUCCESS,
            command=self._toggle_protect_edit_delete_setting,
        ).pack(side="right", padx=14, pady=12)

        snooze_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=12)
        snooze_card.pack(fill="x", pady=(0, 8))
        snooze_text = ctk.CTkFrame(snooze_card, fg_color="transparent")
        snooze_text.pack(side="left", fill="x", expand=True, padx=14, pady=10)
        ctk.CTkLabel(
            snooze_text,
            text="Allow 3-Minute Snooze",
            font=("Segoe UI", 13, "bold"),
            text_color=TEXT,
        ).pack(anchor="w")
        ctk.CTkLabel(
            snooze_text,
            text="Show the Snooze (3m) option when an alarm fires.",
            font=("Segoe UI", 10),
            text_color=SUBTEXT,
        ).pack(anchor="w", pady=(3, 0))
        self.snooze_var = ctk.BooleanVar(
            value=self.data.get("allow_snooze", DEFAULT_ALLOW_SNOOZE)
        )
        ctk.CTkSwitch(
            snooze_card,
            text="",
            variable=self.snooze_var,
            progress_color=SUCCESS,
            command=self._toggle_snooze_setting,
        ).pack(side="right", padx=14, pady=12)


        # Automatic login startup is always enabled for this application.
        as_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=12)
        as_card.pack(fill="x", pady=(0, 8))

        as_text = ctk.CTkFrame(as_card, fg_color="transparent")
        as_text.pack(side="left", fill="x", expand=True, padx=14, pady=10)

        ctk.CTkLabel(
            as_text,
            text="Automatic Start",
            font=("Segoe UI", 13, "bold"),
            text_color=TEXT
        ).pack(anchor="w")

        ctk.CTkLabel(
            as_text,
            text="Enabled through your personal Windows Startup folder.",
            font=("Segoe UI", 10),
            text_color=SUBTEXT
        ).pack(anchor="w", pady=(3, 0))

        # The original switch affordance is retained as a status indicator.
        # Mandatory startup must not be user-disableable in the hardened app.
        self.auto_start_var = ctk.BooleanVar(value=True)
        ctk.CTkSwitch(
            as_card,
            text="Enabled",
            variable=self.auto_start_var,
            state="disabled",
            progress_color=SUCCESS,
            button_color=SUCCESS,
        ).pack(side="right", padx=14, pady=12)



    def _toggle_snooze_setting(self):
        self._authenticate_boolean_setting_change(
            "allow_snooze",
            self.snooze_var,
            DEFAULT_ALLOW_SNOOZE,
            "Allow 3-Minute Snooze",
        )

    def _toggle_protect_edit_delete_setting(self):
        self._authenticate_boolean_setting_change(
            "protect_edit_delete",
            self.protect_edit_delete_var,
            DEFAULT_PROTECT_EDIT_DELETE,
            "Password Protect Edit & Delete",
        )

    def _authenticate_boolean_setting_change(
        self, setting_key, switch_var, default, setting_name
    ):
        requested = bool(switch_var.get())
        with self.data_lock:
            previous = self.data.get(setting_key, default)
        if requested == previous:
            return

        self._auth_then(
            self._save_boolean_setting,
            setting_key,
            requested,
            previous,
            switch_var,
            setting_name,
            message=f"Changing {setting_name} requires your configured password.",
            on_cancel=lambda: switch_var.set(previous),
        )

    def _save_boolean_setting(
        self, setting_key, requested, previous, switch_var, setting_name
    ):
        with self.data_lock:
            self.data[setting_key] = requested
            saved = save_data(self.data)
            if not saved:
                self.data[setting_key] = previous
        if not saved:
            switch_var.set(previous)
            messagebox.showerror(
                "Save Failed",
                f"{setting_name} could not be saved. Check that the data folder is writable.",
            )

    def _refresh_password_controls(self):
        if not hasattr(self, "password_help_lbl"):
            return
        password_enabled = self.data.get("password") is not None
        if password_enabled:
            self.password_help_lbl.configure(
                text="Enter the current password before changing or removing it."
            )
            self.old_pw.configure(
                state="normal",
                placeholder_text="Current password",
            )
            self.password_update_btn.configure(text="Change Password")
            self.password_remove_btn.configure(state="normal")
        else:
            self.password_help_lbl.configure(
                text="Set a password to protect alarm changes and deletions."
            )
            self.old_pw.configure(state="normal")
            self.old_pw.delete(0, "end")
            self.old_pw.configure(
                state="disabled",
                placeholder_text="No current password required",
            )
            self.password_update_btn.configure(text="Set Password")
            self.password_remove_btn.configure(state="disabled")

    def _change_password(self):
        old, new, conf = self.old_pw.get(), self.new_pw.get(), self.confirm_pw.get()
        current_hash = self.data.get("password")

        if current_hash is not None:
            if not old:
                messagebox.showerror(
                    "Current Password Required",
                    "Enter the current password before changing it.",
                )
                return
            if not self._verify_configured_password(old):
                messagebox.showerror(
                    "Wrong Password",
                    "The current password is incorrect.",
                )
                return

        validation_error = validate_new_password(new)
        if validation_error:
            messagebox.showerror("Invalid Password", validation_error)
            return
        if new != conf:
            messagebox.showerror(
                "Passwords Do Not Match",
                "Enter the same new password in both fields.",
            )
            return

        was_enabled = current_hash is not None
        with self.data_lock:
            self.data["password"] = hash_password(new)
            save_data(self.data)
        for e in (self.old_pw, self.new_pw, self.confirm_pw): e.delete(0, "end")
        self._refresh_password_controls()
        success_message = (
            "Password changed successfully."
            if was_enabled
            else "Password protection enabled successfully."
        )
        messagebox.showinfo("Success", success_message)

    def _remove_password(self):
        old = self.old_pw.get()
        current_hash = self.data.get("password")

        if current_hash is None:
            messagebox.showinfo(
                "Password Protection",
                "Password protection is already disabled.",
            )
            return
        if not old:
            messagebox.showerror(
                "Current Password Required",
                "Enter the current password before removing protection.",
            )
            return
        if not self._verify_configured_password(old):
            messagebox.showerror(
                "Wrong Password",
                "The current password is incorrect.",
            )
            return

        if messagebox.askyesno("Confirm", "Are you sure you want to disable password protection?"):
            with self.data_lock:
                self.data["password"] = None
                save_data(self.data)
            for e in (self.old_pw, self.new_pw, self.confirm_pw): e.delete(0, "end")
            self._refresh_password_controls()
            messagebox.showinfo("Success", "Password protection disabled.")

    def _format_history_line(self, line):
        """Convert leading history timestamps from 24-hour to 12-hour AM/PM."""
        if not line:
            return line

        try:
            timestamp_text, separator, remainder = line.partition(" - ")
            if not separator:
                return line

            parsed = datetime.strptime(timestamp_text.strip(), "%Y-%m-%d %H:%M")
            formatted = parsed.strftime("%Y-%m-%d %I:%M %p")
            return f"{formatted} - {remainder}"
        except (TypeError, ValueError):
            return line

    def _refresh_history(self):
        if not self.hist_container or not self.hist_container.winfo_exists():
            return

        for widget in self.hist_container.winfo_children():
            widget.destroy()

        if not os.path.exists(HISTORY_FILE):
            ctk.CTkLabel(
                self.hist_container,
                text="No history yet.",
                font=("Segoe UI", 13),
                text_color=SUBTEXT
            ).pack(anchor="w", pady=6)
            return

        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as history_file:
                lines = [line.strip() for line in history_file if line.strip()]

            if not lines:
                ctk.CTkLabel(
                    self.hist_container,
                    text="No history yet.",
                    font=("Segoe UI", 13),
                    text_color=SUBTEXT
                ).pack(anchor="w", pady=6)
                return

            for line in reversed(lines):
                row = ctk.CTkFrame(
                    self.hist_container,
                    fg_color=INPUT,
                    corner_radius=7
                )
                row.pack(fill="x", pady=3)

                ctk.CTkLabel(
                    row,
                    text=self._format_history_line(line),
                    font=("Segoe UI", 11),
                    text_color=TEXT,
                    anchor="w",
                    justify="left"
                ).pack(fill="x", padx=10, pady=8)

        except Exception as exc:
            print(f"Failed to load alarm history: {exc}")
            ctk.CTkLabel(
                self.hist_container,
                text="Error loading history.",
                font=("Segoe UI", 13),
                text_color=SUBTEXT
            ).pack(anchor="w", pady=6)

    def _log_event(self, alarm, event):
        log_history_event(alarm, event)
    # ---------------- Alarm Checker ----------------
    def _start_alarm_checker(self):
        if self._alarm_check_running:
            return
        self._alarm_check_running = True
        self.fired_alarms_this_minute = set()
        self.last_check_minute = -1
        self._schedule_alarm_check()

    def _ensure_alarm_checker_running(self):
        """Restore the recurring checker if a session transition interrupted it."""
        if self._shutting_down:
            return False
        if self._alarm_check_after_id is not None:
            return True
        if self._alarm_check_running:
            self._schedule_alarm_check()
        else:
            self._start_alarm_checker()
        return self._alarm_check_after_id is not None

    def _schedule_alarm_check(self):
        if self._shutting_down:
            return
        self._check_alarms()
        if not self._shutting_down:
            self._alarm_check_after_id = self.after(1000, self._schedule_alarm_check)

    def _check_alarms(self):
        now = datetime.now()

        with self.data_lock:
            alarms = self.data.get("alarms", [])
            triggered = []

            for alarm in alarms:
                if not alarm.get("enabled", True):
                    continue

                alarm_id = alarm.get("id")
                if alarm_id in self.active_alarm_ids:
                    continue

                dt_str = alarm.get("datetime")
                if not dt_str:
                    continue

                alarm_dt = parse_alarm_datetime(dt_str)
                if not alarm_dt:
                    continue

                if alarm_dt <= now:
                    # Fire!
                    self.active_alarm_ids.add(alarm_id)
                    triggered.append(dict(alarm))

        if triggered:
            try:
                self._fire_alarm(triggered)
            except Exception as exc:
                self._release_active_alarms(triggered)
                print(f"Failed to open alarm window: {exc}")

    def _release_active_alarms(self, alarms):
        for alarm in alarms:
            self.active_alarm_ids.discard(alarm.get("id"))

    def _fire_alarm(self, triggered):
        try:
            rt_file = triggered[0].get("ringtone", DEFAULT_RINGTONE)
            rt_file = self.validate_ringtone_filename(rt_file) or DEFAULT_RINGTONE
            rt_path = self.resolve_ringtone_path(rt_file) or self.resolve_ringtone_path(DEFAULT_RINGTONE)

            self.audio_manager.play_alarm(rt_path)

            for t in triggered:
                self._log_event(t, "Triggered")

            self._open_alarm_popup(triggered)
        except Exception as exc:
            if hasattr(self, 'audio_manager'):
                self.audio_manager.stop_alarm()
            self._release_active_alarms(triggered)
            print(f"Failed to fire alarm: {exc}")
            raise

    def _open_alarm_popup(self, triggered):
        h_s, m_s, ampm = to_12h(triggered[0]["time"])
        label = triggered[0].get("label","") or "Alarm"
        is_snoozed = triggered[0].get("snoozed", False)
        with self.data_lock:
            popup_actions = get_alarm_popup_actions(
                self.data.get("allow_snooze", DEFAULT_ALLOW_SNOOZE),
                is_snoozed,
            )

        dt_obj = parse_alarm_datetime(triggered[0].get("datetime"))
        date_str = dt_obj.strftime("%d %b %Y") if dt_obj else triggered[0].get("date", "")

        win = ctk.CTkToplevel(self)
        apply_window_icon(win)
        win.title("ALARM!")
        width, height = 440, 360 if not is_snoozed else 306
        win.geometry(f"{width}x{height}")
        center_window(win, width, height)
        win.configure(fg_color=BG)
        win.attributes("-topmost", True)
        win.grab_set(); win.resizable(False, False)

        ctk.CTkLabel(win, text="ALARM", font=("Segoe UI Black", 24, "bold"), text_color=ACCENT2).pack(pady=(28, 2))
        ctk.CTkLabel(win, text=f"{h_s}:{m_s} {ampm}",
                     font=("Segoe UI Black", 36, "bold"), text_color=ACCENT).pack()
        ctk.CTkLabel(win, text=date_str, font=("Segoe UI", 14, "bold"), text_color=TEXT).pack(pady=(2, 0))
        ctk.CTkLabel(win, text=label, font=("Segoe UI", 16, "bold"), text_color=ACCENT2).pack(pady=(8, 0))
        
        status_lbl = ctk.CTkLabel(win, text="Screen locks in 30 seconds...",
                                  font=("Segoe UI", 14), text_color=SUBTEXT)
        status_lbl.pack(pady=8)

        dismissed_flag = [False]
        auto_lock_timer = None

        def dismiss(is_auto=False):
            nonlocal dismissed_flag, auto_lock_timer
            if dismissed_flag[0]: return
            dismissed_flag[0] = True

            if auto_lock_timer:
                try:
                    win.after_cancel(auto_lock_timer)
                except Exception:
                    pass
                auto_lock_timer = None

            self.audio_manager.stop_alarm()

            # Keep the popup and alarm state intact if locking fails.
            if not lock_screen():
                dismissed_flag[0] = False
                status_lbl.configure(text="Screen lock failed. Please try again.")
                auto_lock_timer = win.after(30000, lambda: dismiss(True))
                messagebox.showerror(
                    "Lock Failed",
                    "Failed to lock workstation. The alarm has not been dismissed.",
                    parent=win,
                )
                return

            with self.data_lock:
                for t in triggered:
                    alarm_id = t.get("id")
                    for a in list(self.data.get("alarms", [])):
                        if a.get("id") == alarm_id:
                            event = "Auto-Locked" if is_auto else "Dismissed"
                            self._log_event(a, event)

                            repeat = str(a.get("repeat", "none")).lower()
                            next_dt = next_repeat_datetime(a) if repeat != "none" else None
                            if next_dt:
                                a["date"] = next_dt.strftime("%Y-%m-%d")
                                a["time"] = next_dt.strftime("%H:%M")
                                a["datetime"] = next_dt.strftime("%Y-%m-%dT%H:%M:%S")
                                if repeat == "monthly":
                                    a.setdefault(
                                        "repeat_day",
                                        parse_alarm_datetime(
                                            a.get("snooze_original_datetime")
                                            or t.get("datetime")
                                        ).day,
                                    )
                                a["enabled"] = True
                                a["status"] = "scheduled"
                            else:
                                a["enabled"] = False
                                a["status"] = "completed"

                            a["snoozed"] = False
                            a.pop("snooze_original_datetime", None)
                            break
                save_data(self.data)

            self._release_active_alarms(triggered)
            try:
                win.destroy()
            except Exception:
                pass
            self._refresh_alarm_list()


        def snooze():
            nonlocal dismissed_flag
            if dismissed_flag[0]: return
            dismissed_flag[0] = True
            if auto_lock_timer: win.after_cancel(auto_lock_timer)
            self.audio_manager.stop_alarm()
            
            now_plus_3 = datetime.now() + timedelta(minutes=3)
            snooze_date = now_plus_3.strftime("%Y-%m-%d")
            snooze_time = now_plus_3.strftime("%H:%M")
            snooze_dt = now_plus_3.strftime("%Y-%m-%dT%H:%M:00")
            
            with self.data_lock:
                for t in triggered:
                    alarm_id = t.get("id")
                    for a in list(self.data.get("alarms", [])):
                        if a.get("id") == alarm_id:
                            self._log_event(a, "Snoozed")
                            if not a.get("snoozed"):
                                a["snooze_original_datetime"] = a.get("datetime")
                            a["date"] = snooze_date
                            a["time"] = snooze_time
                            a["datetime"] = snooze_dt
                            a["snoozed"] = True
                            a["enabled"] = True
                            a["status"] = "scheduled"
                            break
                save_data(self.data)
            self._refresh_alarm_list()

            self._release_active_alarms(triggered)
            
            try: win.destroy()
            except: pass

        win.protocol("WM_DELETE_WINDOW", lambda: dismiss(False))

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=36, pady=14)

        if "Snooze (3m)" in popup_actions:
            btn_row.grid_columnconfigure(0, weight=1)
            btn_row.grid_columnconfigure(1, weight=1)
            ctk.CTkButton(btn_row, text="Snooze (3m)", fg_color=ACCENT, hover_color="#3730A3",
                          text_color=ON_ACCENT, font=("Segoe UI", 15, "bold"), height=50, corner_radius=11,
                          command=snooze).grid(row=0, column=0, padx=(0, 5), sticky="ew")

            ctk.CTkButton(btn_row, text="Lock Now", fg_color=ACCENT2, hover_color="#BE123C",
                          text_color=ON_ACCENT, font=("Segoe UI", 15, "bold"), height=50, corner_radius=11,
                          command=lambda: dismiss(False)).grid(row=0, column=1, padx=(5, 0), sticky="ew")
        else:
            ctk.CTkButton(btn_row, text="Lock Now", fg_color=ACCENT2, hover_color="#BE123C",
                          text_color=ON_ACCENT, font=("Segoe UI", 15, "bold"), height=50, corner_radius=11,
                          command=lambda: dismiss(False)).pack(fill="x")
        
        auto_lock_timer = win.after(30000, lambda: dismiss(True))


# Compatibility alias for integrations built against the original TimePulse UI.
TimePulse = AlarmApp

# ---------------- Password Dialog ----------------
class PwDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        pw_hash,
        on_success,
        on_cancel=None,
        message="Required to modify this alarm.",
        on_password_upgraded=None,
    ):
        super().__init__(parent)
        apply_window_icon(self)
        self.pw_hash = pw_hash; self.on_success = on_success; self.on_cancel = on_cancel
        self.on_password_upgraded = on_password_upgraded
        self.title("Authentication")
        width, height = 360, 240
        self.geometry(f"{width}x{height}")
        center_window(self, width, height)
        self.configure(fg_color=BG)
        self.attributes("-topmost", True); self.grab_set(); self.resizable(False, False)
        
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
        ctk.CTkLabel(self, text="Enter Password",
                     font=("Segoe UI", 16, "bold"), text_color=TEXT).pack(pady=(24,6))
        ctk.CTkLabel(self, text=message,
                     font=("Segoe UI", 12), text_color=SUBTEXT, wraplength=300).pack()
        self.entry = ctk.CTkEntry(self, show="*", width=270, height=40,
                                  fg_color=INPUT, border_color=ACCENT, text_color=TEXT, font=("Segoe UI", 13))
        self.entry.pack(pady=16)
        self.entry.bind("<Return>", lambda e: self._verify())
        
        btn_f = ctk.CTkFrame(self, fg_color="transparent")
        btn_f.pack()
        ctk.CTkButton(btn_f, text="Confirm", fg_color=ACCENT, hover_color="#3730A3",
                      text_color=ON_ACCENT, width=116, font=("Segoe UI", 13, "bold"), height=40, corner_radius=8,
                      command=self._verify).pack(side="left", padx=4)
        ctk.CTkButton(btn_f, text="Cancel", fg_color=BORDER, hover_color=DANGER,
                      width=116, font=("Segoe UI", 13, "bold"), height=40, corner_radius=8,
                      command=self._on_close).pack(side="left", padx=4)

    def _verify(self):
        password = self.entry.get()
        if verify_password(password, self.pw_hash):
            if (
                self.on_password_upgraded
                and _is_legacy_sha256_hash(self.pw_hash)
            ):
                upgraded_hash = hash_password(password)
                self.on_password_upgraded(upgraded_hash)
                self.pw_hash = upgraded_hash

            self.on_cancel = None # Prevent cancel callback on success
            self.destroy(); self.on_success()
        else:
            messagebox.showerror("Wrong Password", "Incorrect password.", parent=self)
            self.entry.delete(0, "end")

    def _on_close(self):
        if self.on_cancel: self.on_cancel()
        self.destroy()


# ---------------- Edit Dialog ----------------
class EditDialog(ctk.CTkToplevel):
    def __init__(self, parent, data, alarm_id):
        super().__init__(parent)
        apply_window_icon(self)
        self.data = data; self.alarm_id = alarm_id
        
        # Find the alarm by ID
        alarm = None
        for a in data.get("alarms", []):
            if a.get("id") == alarm_id:
                alarm = a
                break
        if not alarm:
            self.destroy()
            return

        self.title("Edit Alarm")
        width, height = 340, 425
        self.geometry(f"{width}x{height}")
        center_window(self, width, height)
        self.configure(fg_color=BG)
        self.attributes("-topmost", True); self.grab_set(); self.resizable(False, False)

        ctk.CTkLabel(self, text="Edit Alarm",
                     font=("Segoe UI", 14, "bold"), text_color=TEXT).pack(pady=(16,8))
        
        h_s, m_s, ampm = to_12h(alarm["time"])
        
        row = ctk.CTkFrame(self, fg_color="transparent"); row.pack()
        self.h_cb = NumberStepper(row, 1, 12, h_s, width=92, height=34)
        self.h_cb.grid(row=0, column=0)
        self.h_cb.set(h_s)

        ctk.CTkLabel(row, text=":", font=("Segoe UI Black", 22),
                     text_color=ACCENT).grid(row=0, column=1, padx=5)

        self.m_cb = NumberStepper(row, 0, 59, m_s, width=92, height=34)
        self.m_cb.grid(row=0, column=2)
        self.m_cb.set(m_s)

        self.ampm = ctk.StringVar(value=ampm)

        self.ampm_menu = ctk.CTkOptionMenu(row, values=["AM", "PM"], width=68, height=34,
                                            variable=self.ampm,
                                            fg_color=INPUT,
                                            button_color=ACCENT, button_hover_color="#5349D6",
                                            dropdown_fg_color=CARD, dropdown_hover_color=BORDER,
                                            dropdown_text_color=TEXT, text_color=TEXT, corner_radius=7)
        self.ampm_menu.grid(row=0, column=3, padx=(9,0))

        ctk.CTkLabel(self, text="Date", font=("Segoe UI", 9, "bold"), text_color=SUBTEXT).pack(anchor="w", padx=36, pady=(12,0))
        self.date_var = ctk.StringVar(value=alarm.get("date", datetime.now().strftime("%Y-%m-%d")))
        self.date_picker = DatePickerField(self, self.date_var, width=270)
        self.date_picker.pack(pady=(3, 6), padx=36, fill="x")

        ctk.CTkLabel(self, text="Ringtone", font=("Segoe UI", 9, "bold"), text_color=SUBTEXT).pack(anchor="w", padx=36, pady=(6,0))
        initial_ringtone = self.master.validate_ringtone_filename(alarm.get("ringtone", DEFAULT_RINGTONE)) or DEFAULT_RINGTONE
        self.ringtone_var = ctk.StringVar(value=initial_ringtone)
        self.ringtone_selector = RingtoneSelector(
            self,
            self.ringtone_var.get(),
            lambda val: self.ringtone_var.set(val),
            parent.audio_manager
        )
        self.ringtone_selector.pack(pady=(3, 6), padx=36, fill="x")

        self.label_var = ctk.StringVar(value=alarm.get("label",""))
        ctk.CTkEntry(self, textvariable=self.label_var, placeholder_text="Label",
                     fg_color=INPUT, border_color=BORDER, text_color=TEXT,
                     placeholder_text_color=SUBTEXT, font=("Segoe UI", 12), width=270, height=34).pack(pady=6)
        ctk.CTkButton(self, text="Save Changes", fg_color=SUCCESS, hover_color="#166534",
                      text_color=ON_ACCENT, font=("Segoe UI", 12, "bold"), height=36,
                      width=270, corner_radius=8,
                      command=self._save).pack(pady=(4, 0))

    def _save(self):
        try:
            h = int(self.h_cb.get()); m = int(self.m_cb.get())
            assert 1 <= h <= 12 and 0 <= m <= 59
            
            date_str = self.date_var.get().strip()
            datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            messagebox.showerror("Invalid", "Please choose a valid date and time.", parent=self); return
        
        h24, m24 = to_24h(h, m, self.ampm.get())
        time_str = f"{h24:02d}:{m24:02d}"
        dt_str = build_alarm_datetime(date_str, time_str)
        
        if parse_alarm_datetime(dt_str) <= datetime.now():
            messagebox.showerror("Invalid", "Alarm must be set in the future.", parent=self); return

        with self.master.data_lock:
            alarm = None
            for a in self.data.get("alarms", []):
                if a.get("id") == self.alarm_id:
                    alarm = a
                    break
            if alarm:
                rt_file = self.master.validate_ringtone_filename(self.ringtone_var.get()) or DEFAULT_RINGTONE
                alarm.update({
                    "date": date_str,
                    "time": time_str,
                    "datetime": dt_str,
                    "label": self.label_var.get().strip(),
                    "status": "scheduled",
                    "ringtone": rt_file,
                    "enabled": True
                })
                save_data(self.data)
                self.master._log_event(alarm, "Edited")
        self.destroy()
        self.master._refresh_alarm_list()

    def destroy(self):
        if hasattr(self, 'ringtone_selector') and self.ringtone_selector:
            self.ringtone_selector.close_dropdown()
        if hasattr(self.master, 'audio_manager'):
            self.master.audio_manager.stop_preview()
        super().destroy()


if __name__ == "__main__":
    instance_mutex_handle = acquire_single_instance_mutex()
    if instance_mutex_handle is False:
        print("KRONOS is already running.")
        sys.exit(0)
    if instance_mutex_handle is None:
        sys.exit(1)

    app = None
    try:
        app = AlarmApp()
        app._instance_mutex_handle = instance_mutex_handle
        PROFILER.mark("mainloop_reached")
        app.mainloop()
    finally:
        if app:
            try:
                app._stop_tray_for_shutdown()
            except Exception:
                pass
            release_single_instance_mutex(app._instance_mutex_handle)
            app._instance_mutex_handle = None
        else:
            release_single_instance_mutex(instance_mutex_handle)
