@echo off
cd /d "%~dp0" 2>nul
chcp 65001 >nul 2>&1
title DMShoot

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    echo [ERROR] No venv found. Run setup.bat first.
    pause
    exit /b 1
)

set "PYTHONPATH=%~dp0"
set "PYTHONUTF8=1"

rem ---- Auto-detect Node.js ----
node --version >nul 2>&1
if %errorlevel% neq 0 (
    for /d %%d in ("%USERPROFILE%\.workbuddy\binaries\node\versions\*") do (
        if exist "%%d\node.exe" set "PATH=%%d;%PATH%"
    )
)

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
if %errorlevel% neq 0 pause
