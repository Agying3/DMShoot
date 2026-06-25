@echo off
cd /d "%~dp0" 2>nul
chcp 65001 >nul 2>&1
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

rem ---- Auto-detect Node.js ----
set "NODE_CMD=node"
set "NPM_CMD=npm"
node --version >nul 2>&1
if %errorlevel% neq 0 (
    for /d %%d in ("%USERPROFILE%\.workbuddy\binaries\node\versions\*") do (
        if exist "%%d\node.exe" (
            set "NODE_CMD=%%d\node.exe"
            set "NPM_CMD=%%d\npm.cmd"
        )
    )
)
if "%NODE_CMD%"=="node" (
    if exist "C:\Program Files\nodejs\node.exe" (
        set "NODE_CMD=C:\Program Files\nodejs\node.exe"
        set "NPM_CMD=C:\Program Files\nodejs\npm.cmd"
    )
)
%NODE_CMD% --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found - required for DouYin/XHS signing
    pause
    exit /b 1
)
echo [OK] Node.js ready

rem ---- DouYin_Spider SDK ----
if not exist "external\DouYin_Spider\.git" (
    echo [*] Cloning DouYin_Spider SDK...
    if not exist "external" mkdir external
    git clone --depth 1 https://github.com/Agying3/DouYin_Spider.git external\DouYin_Spider 2>&1
    if %errorlevel% neq 0 (
        echo [WARN] Clone failed, skipping
    )
)
echo [OK] DouYin_Spider ready

rem ---- jsrsasign ----
if exist "external\DouYin_Spider\node_modules\jsrsasign\package.json" (
    echo [OK] jsrsasign already installed, skipping
) else if exist "external\DouYin_Spider\package.json" (
    echo [*] Installing jsrsasign (npmmirror)...
    pushd "%~dp0external\DouYin_Spider"
    call "%NPM_CMD%" install jsrsasign --registry=https://registry.npmmirror.com
    popd
    if %errorlevel% neq 0 (
        echo [WARN] jsrsasign install failed
    ) else (
        echo [OK] jsrsasign installed
    )
)

rem ---- Python venv ----
if not exist ".venv" (
    echo [*] Creating venv...
    python -m venv .venv
)
echo [OK] venv ready

echo.
echo -------------------------------------------------
echo   Mirror Options:
echo   1. Tsinghua
echo   2. Aliyun
echo   Enter = default PyPI
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
if %errorlevel% neq 0 (
    echo [WARN] pip upgrade failed, continuing...
)

echo [*] Installing requirements...
pip install -r requirements.txt %PIP_ARG%
if %errorlevel% neq 0 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
)
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
