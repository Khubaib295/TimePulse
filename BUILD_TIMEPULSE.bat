@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Development environment not found. Run setup_development.bat or install Python.
        pause
        exit /b 1
    )
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" -m PyInstaller --clean --noconfirm TimePulse.spec
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
