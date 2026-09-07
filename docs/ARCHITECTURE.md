# TimePulse Architecture

## Scope

TimePulse is a Windows-only desktop application written as a single Python module. The main window is implemented by `TimePulse`, a subclass of `customtkinter.CTk`.

## Main components

### User interface

- `TimePulse`: application lifecycle, tabs, alarm list, settings, tray integration, and alarm checking.
- `EditDialog`: alarm editing.
- `PwDialog`: password verification.
- `RingtoneSelector`: themed custom ringtone menu with delayed hover preview.
- `NumberStepper` and `DatePickerField`: reusable input controls.

### Scheduling

The application checks enabled alarms once per second through Tkinter's `after()` scheduler. Alarm IDs are tracked while a popup is active to prevent duplicate firing. Repeating alarms are advanced after dismissal:

- Daily: one day forward.
- Weekly: seven days forward.
- Monthly: same preferred day, clamped to the last day of shorter months.

A snoozed alarm is moved three minutes into the future while retaining its original schedule for repeat calculations.

### Persistence

Alarm data is stored in `%LOCALAPPDATA%\TimePulse\alarms.json` on Windows. Writes use a temporary file, `fsync()`, and `os.replace()` to reduce the chance of partial data. Three rotating backups are retained. Invalid or structurally unsafe data is preserved as a timestamped backup and the user is shown a recovery warning.

History is appended as UTF-8 text under `Alarm History/alarm_history.txt`.

### Security

Password protection is optional. New passwords are stored as salted PBKDF2-HMAC-SHA256 hashes using 600,000 iterations. Verified legacy unsalted SHA-256 hashes are automatically upgraded. This protects selected actions inside the UI; it does not encrypt alarm data on disk.

### Audio

`AudioManager` uses Windows MCI through `winmm.mciSendStringW` for WAV playback and independent aliases for alarm and preview audio. `winsound` provides a fallback if MCI playback fails. Preview timers and generation tokens prevent stale hover requests from creating overlapping audio.

### Windows integration

- `pystray` provides the system-tray icon.
- A user-controlled setting can create or remove a command file in the current user's Startup folder.
- Earlier Task Scheduler entries are removed on a best-effort basis for migration.
- WTS session notifications detect workstation locking and stop all active audio.
- Dismissing an alarm invokes `LockWorkStation` through `rundll32.exe`.
- A named mutex prevents multiple active instances.

### Packaging

`TimePulse.spec` builds a windowed PyInstaller **onedir** distribution at
`dist\TimePulse\TimePulse.exe`. It bundles:

- CustomTkinter package assets.
- `assets/TimePulse.ico`.
- CustomTkinter and the icon within the application directory.

The build script copies the complete `ringtones/` directory beside the
executable. External WAV files there take priority, and the audio files are not
embedded in an archive that must be extracted on every application launch.


## Reliability boundaries

- A Windows named mutex enforces one TimePulse process per user session.
- Due alarms are presented independently to avoid merging labels, ringtones, or snooze state.
- UI mutations are rolled back when durable persistence fails.
- Dismissal state is persisted before workstation locking and rolled back if locking fails.
