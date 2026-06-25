@echo off
title DMShoot Setup
cls
echo ============================================
echo   DMShoot Setup
echo ============================================
echo.
echo Press any key to begin...
pause >nul

cd /d "%~dp0"
if errorlevel 1 goto cd_fail
echo.

echo [1/6] Checking Python...
python --version
if errorlevel 1 goto no_python
echo [OK] Python ready
echo.

echo [2/6] Checking Node.js...
set "NODE_CMD=node"
set "NPM_CMD=npm"
node --version >nul 2>&1
if errorlevel 1 (
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
%NODE_CMD% --version
if errorlevel 1 goto no_node
echo [OK] Node.js ready
echo.

echo [3/6] Checking DouYin_Spider...
if not exist "external\DouYin_Spider\.git" (
    echo [*] Cloning...
    if not exist "external" mkdir external
    git clone --depth 1 https://github.com/Agying3/DouYin_Spider.git external\DouYin_Spider 2>nul
    if errorlevel 1 (
        echo [WARN] Clone failed, skipping
    )
)
if exist "external\DouYin_Spider\.git" (
    echo [OK] DouYin_Spider ready
) else (
    echo [WARN] DouYin_Spider not available - signing will not work
)
echo.

echo [4/6] Checking jsrsasign...
set "JSR_INSTALLED=0"
if exist "external\DouYin_Spider\node_modules\jsrsasign\package.json" set "JSR_INSTALLED=1"
if "%JSR_INSTALLED%"=="1" (
    echo [OK] jsrsasign already installed
)
if "%JSR_INSTALLED%"=="0" (
    if exist "external\DouYin_Spider\package.json" (
        echo [*] Installing jsrsasign (npmmirror)...
        pushd "%~dp0external\DouYin_Spider"
        call "%NPM_CMD%" install jsrsasign --registry=https://registry.npmmirror.com --ignore-scripts --no-optional
        popd
        if errorlevel 1 (
            echo [WARN] jsrsasign install failed, but may still work
        ) else (
            echo [OK] jsrsasign installed
        )
    )
)
echo.

echo [5/6] Checking venv...
if not exist ".venv" (
    echo [*] Creating venv...
    python -m venv .venv
    if errorlevel 1 goto no_venv
)
echo [OK] venv ready
echo.
set "PIP_ARG=-i https://mirrors.aliyun.com/pypi/simple/"
set "PW_HOST=https://npmmirror.com/mirrors/playwright/"

echo [6/6] Installing pip packages (Aliyun)...
call .venv\Scripts\activate.bat
pip install --upgrade pip %PIP_ARG% -q
pip install -r requirements.txt %PIP_ARG%
if errorlevel 1 goto pip_fail
echo [OK] Requirements installed

echo [*] Installing Playwright browser...
if defined PW_HOST set "PLAYWRIGHT_DOWNLOAD_HOST=%PW_HOST%"
playwright install chromium
echo [OK] Playwright installed

goto done

:cd_fail
echo [FATAL] Cannot access %~dp0
pause
exit /b 1

:no_python
echo [ERROR] Python not found in PATH
pause
exit /b 1

:no_node
echo [ERROR] Node.js not found
pause
exit /b 1

:no_venv
echo [ERROR] venv creation failed
pause
exit /b 1

:pip_fail
echo [ERROR] pip install failed
pause
exit /b 1

:done
echo.
echo ============================================
echo   Setup complete! Run run.bat to start.
echo ============================================
pause
