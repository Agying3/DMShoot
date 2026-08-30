@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    set "PYTHONW=.venv\Scripts\pythonw.exe"
) else (
    echo [ERROR] No venv found. Run setup.bat first.
    pause
    exit /b 1
)

set "PYTHONPATH=%~dp0"
set "PYTHONUTF8=1"

node --version >nul 2>&1
if %errorlevel% neq 0 (
    for /d %%d in ("%USERPROFILE%\.workbuddy\binaries\node\versions\*") do (
        if exist "%%d\node.exe" set "PATH=%%d;%PATH%"
    )
)

if /I "%~1"=="--console" (
    "%PYTHON%" main.py
    exit /b %errorlevel%
)

start "" "%PYTHONW%" "%~dp0main.py"
exit /b 0
