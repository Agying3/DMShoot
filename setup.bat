<<<<<<< HEAD
@echo off
chcp 65001 >nul
echo ============================================
echo   DMShoot - 多平台私信聚合工具 环境配置
echo ============================================
echo.

REM 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)
echo [✓] Python 已就绪

REM 检查 Node.js (小红书签名需要)
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 未找到 Node.js（小红书签名可选依赖，不影响抖音/B站使用）
)

REM 创建虚拟环境
if not exist ".venv" (
    echo [*] 创建虚拟环境...
    python -m venv .venv
)
echo [✓] 虚拟环境已就绪

REM 安装依赖
echo [*] 安装 Python 依赖...
call .venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install -r requirements.txt
echo [✓] Python 依赖安装完成

REM 安装 Playwright 浏览器（必须，用于扫码登录）
echo [*] 安装 Playwright 浏览器（可能需要几分钟）...
playwright install chromium
echo [✓] Playwright 浏览器安装完成

REM 检查 DouYin_Spider
if not exist "external\DouYin_Spider\setup.py" (
    echo [!] 未找到 DouYin_Spider，请从以下地址 clone:
    echo     git clone https://github.com/xxx/DouYin_Spider external/DouYin_Spider
    echo    （或手动放入 external/DouYin_Spider/ 目录）
) else (
    echo [✓] DouYin_Spider 已就绪
)

REM 检查 Go 消息服务
if exist "dmshoot-go\msg-service.exe" (
    echo [✓] msg-service.exe 已就绪
) else (
    echo [!] msg-service.exe 不存在（可选：Go 消息服务，用于 IM 协议通信）
)

echo.
echo ============================================
echo   配置完成！运行 run.bat 启动 DMShoot
echo ============================================
pause
=======
@echo off
chcp 65001 >nul
echo ============================================
echo   DMShoot - 多平台私信聚合工具 环境配置
echo ============================================
echo.

REM 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)
echo [✓] Python 已就绪

REM 检查 Node.js (小红书签名需要)
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 未找到 Node.js（小红书签名可选依赖，不影响抖音/B站使用）
)

REM 创建虚拟环境
if not exist ".venv" (
    echo [*] 创建虚拟环境...
    python -m venv .venv
)
echo [✓] 虚拟环境已就绪

REM 安装依赖
echo [*] 安装 Python 依赖...
call .venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install -r requirements.txt
echo [✓] Python 依赖安装完成

REM 安装 Playwright 浏览器（必须，用于扫码登录）
echo [*] 安装 Playwright 浏览器（可能需要几分钟）...
playwright install chromium
echo [✓] Playwright 浏览器安装完成

REM 检查 DouYin_Spider
if not exist "external\DouYin_Spider\setup.py" (
    echo [!] 未找到 DouYin_Spider，请从以下地址 clone:
    echo     git clone https://github.com/xxx/DouYin_Spider external/DouYin_Spider
    echo    （或手动放入 external/DouYin_Spider/ 目录）
) else (
    echo [✓] DouYin_Spider 已就绪
)

REM 检查 Go 消息服务
if exist "dmshoot-go\msg-service.exe" (
    echo [✓] msg-service.exe 已就绪
) else (
    echo [!] msg-service.exe 不存在（可选：Go 消息服务，用于 IM 协议通信）
)

echo.
echo ============================================
echo   配置完成！运行 run.bat 启动 DMShoot
echo ============================================
pause
>>>>>>> e4d005e5b68e4e0bc847197e9fd032c4f15bedeb
