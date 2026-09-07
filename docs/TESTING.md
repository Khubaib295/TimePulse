# Testing TimePulse

## Automated checks

From the repository root:

```cmd
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m py_compile TimePulse.py
```

The test suite verifies logic that does not require an interactive Windows desktop:

- 12-hour and 24-hour time conversion.
- Daily, weekly, and monthly next-occurrence calculations.
- Salted password hashing and legacy-hash compatibility.
- New-password validation.
- Safe ringtone filename validation.
- Atomic JSON save/load behavior and corrupt-file backup recovery.
- Source syntax.

## Manual Windows test checklist

1. Run `python TimePulse.py` on Windows 10 or 11.
2. Create two alarms with different WAV files.
3. Restart the app and verify both ringtone selections persist.
4. Edit one alarm and change its ringtone.
5. Move quickly across ringtone entries and verify only the current preview plays.
6. Leave or close the dropdown and verify preview audio stops.
7. Trigger an alarm and verify the selected ringtone loops.
8. Snooze it and verify audio stops immediately and the time moves three minutes forward.
9. Dismiss an alarm and verify the workstation locks.
10. Leave an alarm untouched and verify the automatic lock attempt after 30 seconds.
11. Lock Windows while an alarm or preview is playing and verify audio stops.
12. Unlock Windows and verify stopped audio does not resume.
13. Rename the selected WAV and verify fallback to `Soft_Arrival.wav`.
14. Verify light and dark appearance modes.
15. Minimize to the tray, restore the window, and exit from the tray menu.
16. Confirm the Startup entry launches TimePulse at the next sign-in.
17. Build with `pyinstaller --clean --noconfirm TimePulse.spec`.
18. Copy `ringtones\` to `dist\TimePulse\ringtones\` (or use `BUILD_TIMEPULSE.bat`).
19. Run `dist\TimePulse\TimePulse.exe` and repeat the alarm and ringtone checks.
19. Exit and verify no TimePulse or orphan audio process remains.

The Linux-based preparation environment cannot truthfully validate Windows audio, locking, tray behavior, startup, or the final executable. Those checks must be completed on Windows.
