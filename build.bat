@echo off
title DMShoot Build
cd /d "%~dp0"

echo ============================================
echo   DMShoot - PyInstaller Build
echo ============================================
echo.

rem Check PyInstaller
.venv\Scripts\pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Installing PyInstaller...
    .venv\Scripts\pip install pyinstaller
)
echo [OK] PyInstaller ready
echo.

echo [*] Building DMShoot.exe...
.venv\Scripts\pyinstaller DMShoot.spec --clean --noconfirm
if %errorlevel% neq 0 (
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Build complete!
echo   dist\DMShoot.exe
echo ============================================
pause
