@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else if exist "H:\DMShoot\.venv\Scripts\python.exe" (
    set "PYTHON=H:\DMShoot\.venv\Scripts\python.exe"
) else (
    echo [ERROR] No venv found. Run setup.bat first.
    pause
    exit /b 1
)

set "PYTHONPATH=%~dp0"

echo ============================================
echo   DMShoot
echo ============================================

if exist "dmshoot-go\msg-service.exe" (
    echo Starting Go msg-service...
    start "" /B "dmshoot-go\msg-service.exe"
    timeout /t 2 >nul
)

echo Starting GUI...
"%PYTHON%" main.py

echo Done.
pause
