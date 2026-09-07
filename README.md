<div align="center">

<img src="assets/TimePulse.png" alt="TimePulse icon" width="96" />

# TimePulse v1.0

**A Windows focus alarm that helps you respect your own deadlines.**

[![Tests](https://github.com/khubaibadeel/TimePulse/actions/workflows/tests.yml/badge.svg)](https://github.com/khubaibadeel/TimePulse/actions/workflows/tests.yml)
[![Build](https://github.com/khubaibadeel/TimePulse/actions/workflows/build.yml/badge.svg)](https://github.com/khubaibadeel/TimePulse/actions/workflows/build.yml)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D4?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

---

## Overview

**TimePulse is a time-focused Windows alarm application designed to create a clear stopping point for your work.**

Set a deadline, focus on the task, and when the scheduled time arrives TimePulse sounds the alarm and gives you a short opportunity to act before locking the Windows workstation.

The idea is simple:

**Set a deadline → Stay focused → Alarm fires → Time ends → PC locks**

Unlike a normal alarm that can simply be ignored, TimePulse helps enforce the end of a work or study session.

> **TimePulse locks the Windows workstation. It does not sign you out of Windows, close your programs, or shut down the computer.**

---

## How It Works

When an alarm reaches its scheduled time:

1. The selected ringtone starts playing.
2. The TimePulse alarm window appears.
3. You can choose:
   - **Snooze (3m)** — gives you another 3 minutes.
   - **Lock Now** — locks the workstation immediately.
4. If you take no action, TimePulse automatically locks the workstation after **30 seconds**.

This makes TimePulse useful for:

- Focused study sessions
- Programming and work blocks
- Time-boxing tasks
- Scheduled breaks
- Limiting time spent on one task
- Enforcing personal stop times
- Building better time-management habits

---

## Features

- Create, edit, enable, disable, and delete alarms
- One-time, daily, weekly, and monthly repeat schedules
- Quick timers for short focus sessions
- Automatic workstation lock after 30 seconds
- Immediate **Lock Now** action
- **3-minute Snooze**
- Seven bundled WAV ringtones
- Per-alarm ringtone selection
- Ringtone preview
- Live clock and next-alarm countdown
- Alarm history and missed-alarm tracking
- Optional password protection for sensitive actions
- Light and dark appearance modes
- System-tray operation
- Automatic launch at Windows sign-in
- Single-instance protection
- Windows session-lock detection
- Atomic JSON persistence with backup/recovery handling
- PyInstaller executable packaging

---

# Installation

## Option 1 — Use the Windows Application

This is the recommended method for normal users.

### 1. Download TimePulse

Download the latest packaged:

```text
TimePulse.exe
```

from the repository's **Releases** section.

Python is **not required** when using the packaged Windows executable.

---

### 2. Place TimePulse in a Permanent Folder

Because TimePulse automatically registers itself for Windows startup, keep the executable in a permanent location.

For example:

```text
C:\Users\<YourUser>\AppData\Local\TimePulse\
```

Place:

```text
TimePulse.exe
```

inside that folder.

Avoid moving the executable after TimePulse has registered itself for automatic startup.

---

### 3. Run TimePulse

Double-click:

```text
TimePulse.exe
```

The normal TimePulse window will appear.

Administrator privileges are not required.

On startup, TimePulse automatically creates or repairs its per-user Windows Startup entry.

---

# First-Time Setup

## Create an Alarm

1. Open TimePulse.
2. Go to the **Alarms** section.
3. Select **New Alarm**.
4. Choose the required date and time.
5. Add a label if desired.
6. Select a ringtone.
7. Select a repeat schedule if required.
8. Save the alarm.

Supported schedules include:

- One-time
- Daily
- Weekly
- Monthly

---

## Quick Timers

Quick timers are useful when you want a short focus session without manually selecting a future date and time.

Set a duration and TimePulse creates the corresponding alarm for you.

---

## Choose a Ringtone

Each alarm can use its own ringtone.

TimePulse includes seven bundled WAV files and supports ringtone preview before selection.

The default ringtone is:

```text
Soft_Arrival.wav
```

Bundled sounds are stored in:

```text
ringtones/
```

---

## Password Protection

TimePulse provides optional password protection for sensitive actions.

This can help prevent alarms from being casually changed, disabled, or deleted during a focused session.

Password protection can be configured from the application settings.

Passwords are stored using **PBKDF2-HMAC-SHA256 hashing**.

> Password protection controls actions inside TimePulse. It does not encrypt the alarm data file.

---

# Windows Tray

Closing the main TimePulse window with **X** does not terminate the application.

Instead, TimePulse remains active in the Windows system tray.

While hidden:

- Alarms continue running
- Timers remain active
- Alarm windows can still appear
- The tray icon remains available

Use:

```text
Tray → Show
```

to restore the main window.

Use:

```text
Tray → Exit
```

to completely terminate TimePulse.

---

# Automatic Startup

TimePulse automatically starts when the current Windows user signs in.

It uses the current user's Windows Startup folder and does not require Administrator privileges.

The startup file is:

```text
TimePulse Startup.cmd
```

TimePulse automatically creates or repairs this entry when required.

Only **one TimePulse instance** is allowed to run for the same Windows user session.

---

# Alarm Behavior

### No action taken

```text
Alarm fires
     ↓
30-second warning
     ↓
Windows workstation locks
```

### Snooze selected

```text
Alarm fires
     ↓
Snooze (3m)
     ↓
3-minute extension
     ↓
Alarm fires again
```

### Lock Now selected

```text
Alarm fires
     ↓
Lock Now
     ↓
Windows workstation locks immediately
```

Locking Windows does not close your open programs or documents.

---

# Running From Source

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer
- Python 3.12 recommended

Clone the repository:

```cmd
git clone https://github.com/khubaibadeel/TimePulse.git
cd TimePulse
```

Create a virtual environment:

```cmd
python -m venv .venv
```

Activate it:

```cmd
.venv\Scripts\activate
```

Upgrade pip:

```cmd
python -m pip install --upgrade pip
```

Install the application dependencies:

```cmd
python -m pip install -r requirements.txt
```

Run TimePulse:

```cmd
python TimePulse.py
```

You can also use the provided development scripts:

```text
setup_development.bat
RUN_TIMEPULSE.bat
```

---

# Building TimePulse

Install the development dependencies:

```cmd
python -m pip install -r requirements-dev.txt
```

Build the Windows executable:

```cmd
python -m PyInstaller --clean TimePulse.spec
```

The startup-optimized package is generated as:

```text
dist\TimePulse\TimePulse.exe
```

This is a PyInstaller **onedir** build: launch `TimePulse.exe` from its folder,
and distribute the whole `dist\TimePulse` directory through an installer if a
single download is desired. Do not convert it back to onefile—the onefile
bootloader extracts the full application into `%TEMP%` every launch. The build
script copies `ringtones\` alongside the executable so the 67 MB audio set is
never extracted at startup.

To collect five comparable source or packaged-startup samples:

```cmd
python benchmark_startup.py --source --runs 5
python benchmark_startup.py --exe dist\TimePulse\TimePulse.exe --runs 5
```

Generated build artifacts are intentionally excluded from the Git repository:

```text
build/
dist/
__pycache__/
*.pyc
*.pyo
*.exe
*.msi
*.pkg
```

These files should remain local and should not be committed.

---

# Runtime Data

TimePulse maintains local runtime data including:

```text
alarms.json
alarms.json.bak
Alarm History/
└── alarm_history.txt
```

These files can contain personal alarm schedules, labels, history, and password-related data and are therefore excluded from Git.

Do not manually edit these files while TimePulse is running.

---

# Important Notes

- TimePulse **locks** Windows; it does not log the user out.
- Locking Windows does not close running applications.
- TimePulse does not shut down or restart the computer.
- TimePulse does not wake a sleeping or powered-off computer.
- Snoozing delays the alarm for **3 minutes** without locking the workstation.
- An unattended alarm attempts to lock the workstation after **30 seconds**.
- A stale one-time alarm detected after TimePulse starts is treated as missed rather than unexpectedly firing.
- Closing the main application window keeps TimePulse running in the system tray.
- Use **Tray → Exit** when you want to stop TimePulse completely.

---

# Testing

Install the development dependencies if necessary:

```cmd
python -m pip install -r requirements-dev.txt
```

Run the automated test suite:

```cmd
python -m pytest -q
```

Automated tests cover core application behavior including scheduling, password handling, ringtone validation, persistence, and reliability helpers.

Windows-specific behavior requires manual testing, including:

- Alarm playback
- Snooze behavior
- 30-second automatic locking
- **Lock Now**
- System-tray operation
- Windows lock/unlock handling
- Automatic startup
- Single-instance behavior
- Packaged executable behavior

Additional testing information is available in:

```text
docs/TESTING.md
```

---

# Technology

| Layer | Technology |
|---|---|
| Language | Python |
| Interface | CustomTkinter, Tkinter |
| Tray integration | pystray, Pillow |
| Storage | Local JSON files |
| Audio | Windows MCI through `ctypes`, with `winsound` fallback |
| Windows integration | Win32 APIs, WTS session notifications, Startup folder |
| Packaging | PyInstaller |
| Testing | pytest, GitHub Actions |

---

# Project Structure

```text
TimePulse/
├── TimePulse.py
├── TimePulse.spec
├── version_info.txt
├── assets/
│   ├── TimePulse.ico
│   └── TimePulse.png
├── docs/
├── ringtones/
├── tests/
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── LICENSE
└── VERSION
```

---

# License

This project is licensed under the [MIT License](LICENSE).

---

# Author

Developed by **khubaibadeel**.
