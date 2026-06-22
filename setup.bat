@echo off
chcp 65001 >nul
title DMShoot Setup

echo ============================================
echo   DMShoot Setup
echo ============================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.10+ not found
    pause
    exit /b 1
)
echo [OK] Python ready

node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found - required for DouYin/XHS signing
    pause
    exit /b 1
)
echo [OK] Node.js ready

echo [*] Checking DouYin_Spider...
if not exist "external\DouYin_Spider\.git" (
    echo [*] Cloning DouYin_Spider SDK...
    if not exist "external" mkdir external
    git clone --depth 1 https://github.com/Agying3/DouYin_Spider.git external\DouYin_Spider
    if %errorlevel% neq 0 (
        echo [WARN] Clone failed. Manually clone to external/DouYin_Spider
    )
)
echo [OK] DouYin_Spider ready

echo [*] Installing Node.js dependencies (jsrsasign)...
cd /d external\DouYin_Spider
call npm install jsrsasign
cd /d %~dp0
echo [OK] jsrsasign installed

if not exist ".venv" (
    echo [*] Creating venv...
    python -m venv .venv
)
echo [OK] venv ready

echo.
echo -------------------------------------------------
echo   Mirror Options:
echo   1. Tsinghua (fast, but some large packages may be missing)
echo   2. Aliyun   (fast, has PySide6)
echo   Enter = default PyPI (slow outside China)
echo -------------------------------------------------
set /p CHOICE="Select [1/2/Enter]: "

if "%CHOICE%"=="1" goto :tsinghua
if "%CHOICE%"=="2" goto :aliyun
goto :no_mirror

:tsinghua
set "PIP_ARG=-i https://pypi.tuna.tsinghua.edu.cn/simple --extra-index-url https://pypi.org/simple"
set "PW_HOST=https://npmmirror.com/mirrors/playwright/"
echo [*] Tsinghua + PyPI fallback
goto :install

:aliyun
set "PIP_ARG=-i https://mirrors.aliyun.com/pypi/simple/"
set "PW_HOST=https://npmmirror.com/mirrors/playwright/"
echo [*] Aliyun mirror
goto :install

:no_mirror
set PIP_ARG=
set PW_HOST=
echo [*] Default PyPI

:install
call .venv\Scripts\activate.bat
pip install --upgrade pip %PIP_ARG% -q

echo [*] Installing requirements...
pip install -r requirements.txt %PIP_ARG%
echo [OK] Requirements installed

echo [*] Installing Playwright browser (~300MB)...
if defined PW_HOST set "PLAYWRIGHT_DOWNLOAD_HOST=%PW_HOST%"
playwright install chromium
echo [OK] Playwright installed

echo.
echo ============================================
echo   Setup complete! Run run.bat to start.
echo ============================================
pause
