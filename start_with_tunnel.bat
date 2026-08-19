@echo off
REM Trip Share 一键启动（本地 + Cloudflare Tunnel 公网暴露）
REM 注意：8765 已被客户管理工作台占着，所以默认用 8000。
REM
REM 流程：1) 启动 Flask  2) 等 3 秒  3) 开 Cloudflare Tunnel
REM 朋友通过临时 https://xxx.trycloudflare.com 访问

setlocal enabledelayedexpansion
cd /d "%~dp0"

REM 检查 cloudflared 是否存在
set CLOUDFLARED=
where cloudflared >nul 2>nul
if %ERRORLEVEL% == 0 (
  set CLOUDFLARED=cloudflared
) else if exist "C:\Windows\cloudflared.exe" (
  set CLOUDFLARED=C:\Windows\cloudflared.exe
) else if exist "%ProgramFiles%\cloudflared\cloudflared.exe" (
  set CLOUDFLARED=%ProgramFiles%\cloudflared\cloudflared.exe
) else (
  echo.
  echo [提示] 未检测到 cloudflared。要把链接暴露到公网，需手动安装：
  echo        1. 下载 https://github.com/cloudflare/cloudflared/releases（选 cloudflared-windows-amd64.exe）
  echo        2. 改名为 cloudflared.exe，放到 C:\Windows\ 或当前目录
  echo        3. 重启这个脚本
  echo.
  echo        注意：用 Cloudflare Tunnel 模式的话，你电脑不能关，关了朋友访问不了。
  echo        想要 7x24 永不关？用 deploy_to_render.bat 一键推 GitHub + Render。
  echo.
  set CLOUDFLARED=
)

REM Python
set PYTHON_EXE=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe
if not exist "%PYTHON_EXE%" (
  set PYTHON_EXE=python
)

REM 装依赖
if not exist ".deps_installed" (
  echo [setup] 第一次运行，安装依赖 ...
  "%PYTHON_EXE%" -m pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  if errorlevel 1 goto :err
  type nul > .deps_installed
)

REM 端口（默认 8000，避开 8765；PORT 优先）
if "%PORT%"=="" set PORT=8000
set /a TRIED=0
:check_port
netstat -ano | findstr ":%PORT% " | findstr LISTENING >nul
if %ERRORLEVEL%==0 (
  set /a PORT=%PORT%+1
  set /a TRIED=%TRIED%+1
  if %TRIED% GTR 10 (
    echo [error] No free port in range. Try: set PORT=9500 ^& start_with_tunnel.bat
    pause
    exit /b 1
  )
  goto :check_port
)

REM 关闭旧实例（如果有）
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :%PORT% ^| findstr LISTENING') do (
  taskkill /F /PID %%a >nul 2>nul
)

echo.
echo [start] 启动 Flask 服务 (端口 %PORT%) ...
start "Trip-Share-Flask" /min cmd /c "%PYTHON_EXE% server.py"
timeout /t 2 /nobreak >nul

REM 检查服务起来了
curl -s -o nul -w "  本地地址: http://localhost:%PORT%/  (HTTP %%{http_code})" http://localhost:%PORT%/health
echo.
echo.

if defined CLOUDFLARED (
  echo [tunnel] 启动 Cloudflare Tunnel，链接马上会显示在下面：
  echo          (Ctrl+C 关闭)
  echo.
  "%CLOUDFLARED%" tunnel --url http://localhost:%PORT%
) else (
  echo [info] 本地地址: http://localhost:%PORT%/
  echo        朋友只能在你这台电脑或同网络访问。
  echo        关闭此窗口即停止服务。
  echo        想要 7x24 可访问？去运行 deploy_to_render.bat
  pause
)

goto :eof

:err
echo.
echo [error] 依赖安装失败。检查 Python / 网络。
pause
