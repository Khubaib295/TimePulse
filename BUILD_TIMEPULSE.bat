@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Development environment not found. Run setup_development.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm TimePulse.spec
if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

xcopy /E /I /Y "ringtones" "dist\TimePulse\ringtones" >nul
if errorlevel 1 (
    echo.
    echo Failed to copy external ringtone resources.
    pause
    exit /b 1
)

echo.
echo Build completed: dist\TimePulse\TimePulse.exe
echo Package the complete dist\TimePulse folder in an installer; do not use onefile.
pause
