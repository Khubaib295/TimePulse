# TimePulse Startup Optimization Results

## Executive summary

TimePulse now reaches its first Tk idle callback without waiting for alarm-card
construction, tray startup, Task Scheduler cleanup, or hidden tabs. The
production package is an onedir build, so it no longer extracts an application
archive to a fresh `_MEI` directory at every launch.

## Measured benchmark

Environment: Windows 10 (19045), Python 3.12.10, PyInstaller 6.15.0. The
benchmark uses `benchmark_startup.py`, enables only the opt-in startup profiler,
waits for its report, then terminates the test process. It measures process
entry to named in-process milestones; **first idle is the closest automated
proxy for a responsive, first-painted window**, not a pixel-based screenshot
measurement.

| Milestone | 5-run packaged result (ms) |
|---|---:|
| imports complete | 419.10 mean (312.92–512.81) |
| root window created | 640.40 mean (509.66–756.25) |
| visible shell construction complete | 773.76 mean (587.88–926.92) |
| mainloop reached | 773.79 mean (587.91–926.94) |
| first idle callback | 776.08 mean (590.59–929.79) |
| alarm cards rendered | 783.90 mean (595.35–937.85) |
| tray initialization complete | 971.34 mean (787.60–1154.96) |

The prior onefile executable was 96,161,882 bytes and the repository's
pre-change audit recorded 5.5–8.5 seconds from double-click to interactive UI.
That historical range was not re-measured with the new helper because the old
binary did not contain profiling instrumentation. Do not treat it as a
like-for-like automated comparison. The five new packaged measurements above
are actual data; the improvement from avoiding onefile extraction is an
architectural guarantee, not a newly timed old-versus-new claim.

## Changes that remove startup bottlenecks

- `TimePulse.spec` now emits `dist\TimePulse\TimePulse.exe` through `COLLECT`,
  uses `upx=False`, excludes unused scientific packages, and keeps ringtones
  external.
- `AlarmApp` loads critical settings before creating the root, then constructs
  only the header, clock, navigation, and Alarms shell before `mainloop()`.
  Timers and Settings are cached after first selection.
- Alarm cards are rendered from `after_idle()` in batches of 25. Alarm checking
  starts independently, so rendering never delays a due alarm.
- `pystray` and Pillow's tray image are imported in a tray worker. The Tk thread
  polls a queue; it never calls `Event.wait()` during startup.
- Task Scheduler cleanup now runs once under `startup_migration_version` in the
  background. The ordinary Startup-folder entry is still checked and repaired.
- Pillow icon decoding is a fallback only; Windows uses the native icon path
  first. The unused XML import and import-time history-directory creation were
  removed.

## Distribution and resources

| Item | Actual size |
|---|---:|
| Legacy onefile `dist\TimePulse.exe` | 96,161,882 bytes |
| New onedir package, including ringtones | 114,714,769 bytes |
| Ringtones (7 WAVs, external) | 70,724,130 bytes |
| Largest ringtone: `Input_Restricted.wav` | 26,860,110 bytes |

The onedir package is larger on disk because it includes the explicitly
validated Tcl/Tk runtime and does not compress the payload into one archive.
This is intentional: startup avoids per-launch decompression/extraction and
the audio files remain normal installed files. No ringtone was recompressed or
removed.

## Validation performed

- `python -m py_compile TimePulse.py benchmark_startup.py pyi_rth_timepulse_tk.py`
- `python -m pytest -q` — 45 passed.
- `python -m PyInstaller --clean --noconfirm TimePulse.spec` — completed.
- One packaged launch initially exposed a missing-Tk payload from this Python
  installation. The spec now explicitly bundles Tcl/Tk and `tkinter`; a
  subsequent packaged profile completed successfully, followed by the five-run
  benchmark above.

## Remaining risks and deliberately deferred work

- The profiler measures idle readiness, not a captured screen pixel. Keep using
  the included helper on release hardware, especially systems with aggressive
  antivirus scanning.
- Full manual validation of tray menu clicks, minimize/restore, lock/unlock,
  actual alarm playback, Windows sign-in startup, and an installer is still
  required before release. The automated launches confirmed the packaged app
  starts and reports milestones, but they intentionally terminate it early.
- Ringtones were not recompressed because alarm audibility and user assets take
  priority over a smaller download. The startup win comes from externalizing
  them, not altering their quality.

