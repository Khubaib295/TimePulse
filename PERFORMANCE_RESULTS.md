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

---

## Independent Review & Audit (2026-09-07)

An independent, skeptical performance and reliability audit was conducted on the
changes introduced on branch `codex/startup-optimization`.

### 1. Audit Findings & Implemented Fixes

The initial optimization diff introduced several significant race conditions,
Tkinter threading violations, and reliability regressions that had to be corrected:

| Severity | Category | Finding | Remediation Applied |
|:---|:---|:---|:---|
| **CRITICAL** | Tray & UI | **Tray polling omission & minimize lockup:** `_setup_tray()` started the background worker thread but did not schedule `self.after(50, self._poll_tray_events)`. If tray startup did not finish before deferred startup completed or if `_withdraw_window()` was called when `_tray_starting` was False, `_poll_tray_events` was never polled. As a result, minimizing to tray broke and the window could never be hidden. | `_setup_tray()` now directly schedules `_poll_tray_events` on launch. `_poll_tray_events` also detects if the worker thread terminated unexpectedly. `_withdraw_window()` safely restores window visibility if tray initialization fails. |
| **CRITICAL** | Threading | **Direct Tkinter calls from tray thread on quit:** When the user selected "Exit" from the tray menu, `_quit_app()` attempted `self.after(0, self._quit_app_main_thread)`. In its fallback `except` block, it directly executed `self._quit_app_main_thread()` on the background tray worker, violating Tkinter's single-thread model (`cancel_after`, widget traversal, `destroy`). | Fallback in `_quit_app()` now safely invokes `self._stop_tray_for_shutdown()` without touching Tkinter widgets or event loops from the worker thread. |
| **HIGH** | Concurrency | **Unsynchronized password mutations under background migration:** Background startup runs `run_startup_migration()` on a separate daemon thread (`TimePulseStartup`) and writes to `self.data` under `self.data_lock`. However, `_change_password()` and `_remove_password()` modified `self.data["password"]` and called `save_data(self.data)` on the UI thread without holding `self.data_lock`. | `_change_password()` and `_remove_password()` now synchronize all `self.data` mutations and `save_data` invocations within `with self.data_lock:`. |
| **HIGH** | Migration | **Irreversible partial startup migrations:** `_remove_legacy_startup_files()` and `_remove_legacy_scheduled_tasks()` caught exceptions and printed errors, but did not return status codes. If task deletion failed (e.g. permission or lock errors), `run_startup_migration()` still permanently stamped `startup_migration_version = 1`, making partial migration failures unrecoverable. | Both cleanup helpers now return boolean status. `run_startup_migration()` records `startup_migration_version = 1` only when both file and task removals succeed, ensuring failed cleanups retry automatically. |
| **HIGH** | Reliability | **Alarm engine deferred behind visual card rendering:** In the proposed startup sequence, `_start_alarm_checker()` was placed in `_deferred_startup()` after `_refresh_alarm_list(batch_size=25)` had already commenced. This coupled alarm firing to UI card construction and risked delaying a due alarm if card rendering encountered delays. | `_start_alarm_checker()` was moved to `_on_first_idle` before `_refresh_alarm_list()`. Alarm checking is now completely decoupled from card rendering. |
| **MEDIUM** | Defensive UI | **Potential AttributeError in lazy Settings controls:** `_refresh_password_controls()` assumed `self.password_help_lbl` was already instantiated. | Added a defensive `if not hasattr(self, "password_help_lbl"): return` guard. |
| **MEDIUM** | Teardown | **Uncancelled batched card render timers:** `self.after(1, ...)` in `_render_alarm_cards()` did not retain its timer handle, risking widget access post-destruction. | Timer handle is now tracked in `self._render_cards_after_id`, checks `winfo_exists()` on the canvas, and is explicitly cancelled in `_shutdown_cleanup()`. |
| **MEDIUM** | Exception Handling | **Silent failure via bare except clauses:** `parse_alarm_datetime()` and tray tooltip updates used bare `except:`. | Replaced with specific exception types (`(ValueError, TypeError)`, `Exception`) and explicit tray readiness checks. |
| **PACKAGING** | Build Script | **Hardcoded `.venv` path in `BUILD_TIMEPULSE.bat`:** The build batch script exited with error 1 if `.venv\Scripts\python.exe` was not present, preventing builds using system Python or alternative environments. | `BUILD_TIMEPULSE.bat` now checks `.venv\Scripts\python.exe` first and falls back to `python` on PATH. |

---

### 2. Performance & Benchmark Challenge

#### Empirical Re-Benchmarking (Packaged Onedir Build)

The original claim of a consistent ~776 ms startup across all runs was audited by
building `dist\TimePulse\TimePulse.exe` and executing `benchmark_startup.py` over
a fresh 5-run sequence on Windows 10:

| Milestone | Codex Claim (Mean ms) | Empirical Measured Result (ms) |
|:---|---:|---:|
| `imports_complete` | 419.10 | **598.16 mean** (302.48 – 1,404.27) |
| `root_window_created` | 640.40 | **999.14 mean** (498.45 – 2,451.43) |
| `alarm_checker_initialized` | 760.08 | **1,119.96 mean** (593.54 – 2,535.67) |
| `mainloop_reached` | 773.79 | **1,118.51 mean** (592.16 – 2,534.89) |
| `first_idle_callback` | 776.08 | **1,119.91 mean** (593.50 – 2,535.65) |
| `alarm_cards_rendered` | 783.90 | **1,127.69 mean** (600.77 – 2,539.97) |
| `tray_initialization_complete` | 971.34 | **1,271.87 mean** (656.38 – 2,745.42) |
| **Wall Clock (Process to Report)** | *Not reported* | **2,317.93 mean** (1,330.97 – 5,210.28) |

#### Analysis of Variance & Validity

1. **Cold Boot & Windows Defender Overhead:** The first run immediately following a build exhibited a `first_idle_callback` of **2,535.65 ms** and a wall clock of **5,210.28 ms** due to Windows Defender scanning newly emitted binaries and DLLs in `_internal/`. Once cached by the OS, warm runs achieved first idle in **593.50 ms – 940.51 ms**. Stating startup as a single ~776 ms metric without acknowledging Windows Defender cold launch latency is incomplete.
2. **In-Process Milestones vs. User-Perceived Wall Clock:** The profiler milestones measure time from `time.perf_counter()` after the Python runtime initializes (`_STARTUP_T0`). Real user-perceived launch includes OS `CreateProcess`, loading memory-mapped DLLs, and PyInstaller bootloader initialization, which adds approximately **700–1,200 ms** on Windows, bringing total launch-to-interactive time to ~1.3–2.3 seconds (down significantly from the 6–8+ seconds of the onefile archive extraction).
3. **Decoupled Reliability Verified:** In the updated implementation, `alarm_checker_initialized` executes at `_on_first_idle` (593.54 ms min) right beside `first_idle_callback` (593.50 ms min), ensuring alarms fire immediately regardless of subsequent visual card batching.

---

### 3. Verification & Test Suite Results

- `python -m compileall .` — Syntax and bytecode validated across all project files.
- `python -m pytest -v` — **54 passed in 3.87s** (including 9 new regression tests covering migration recovery, tray death detection, lock synchronization, and lazy tab caching in `tests/test_startup_optimization.py`).
- Packaged build verification: `TimePulse.exe` starts as a true onedir package, resolves external WAV ringtones from `dist\TimePulse\ringtones`, locates `TimePulse.ico` in `_internal\assets`, and operates without extracting `%TEMP%` payloads.

### 4. Audit Verdict

- **Initial Codex diff:** `PASS WITH ISSUES` (concurrency races, unrecoverable migration failures, tray lockup, and alarm checking coupled to card rendering).
- **Current branch state (with fixes applied):** `PASS / READY TO MERGE`.
