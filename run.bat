@echo off
title DMShoot
echo ============================================
echo   DMShoot
echo ============================================
echo.
cd /d "%~dp0"
.venv\Scripts\python.exe main.py
echo.
echo Done. Press any key.
pause >nul
