@echo off
title DMShoot
cls
echo ============================================
echo   DMShoot
echo ============================================
echo.
echo Press any key to start...
pause >nul

cd /d "%~dp0"
if errorlevel 1 goto cd_fail

if exist ".venv\Scripts\python.exe" goto has_venv
echo [ERROR] No venv found. Run setup.bat first.
pause
exit /b 1

:has_venv
set "PYTHON=.venv\Scripts\python.exe"
set "PYTHONPATH=%~dp0"
set "PYTHONUTF8=1"

rem ---- Auto-detect Node.js ----
node --version >nul 2>&1
if errorlevel 1 (
    for /d %%d in ("%USERPROFILE%\.workbuddy\binaries\node\versions\*") do (
        if exist "%%d\node.exe" set "PATH=%%d;%PATH%"
    )
)

if exist "dmshoot-go\msg-service.exe" (
    echo Starting Go msg-service...
    start "" /B "dmshoot-go\msg-service.exe"
    timeout /t 2 >nul
)

echo Starting GUI...
"%PYTHON%" main.py

echo.
echo Done.
pause
goto :eof

:cd_fail
echo [FATAL] Cannot access %~dp0
pause
exit /b 1
