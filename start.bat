@echo off
REM Trip Share local starter (Windows).
REM Uses managed Python so no admin install needed.
REM Port: defaults to 8000; override with `set PORT=9000` before running.

setlocal
set PYTHON_EXE=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe
if not exist "%PYTHON_EXE%" (
  echo [error] Python not found at: %PYTHON_EXE%
  echo         Adjust start.bat to your Python path.
  pause
  exit /b 1
)

cd /d "%~dp0"

REM Install deps on first run
if not exist ".deps_installed" (
  echo [setup] Installing dependencies ...
  "%PYTHON_EXE%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  if errorlevel 1 goto :err
  type nul > .deps_installed
)

REM Port selection: avoid 8765 (Jojo's customer-mgmt workbench) and 8766/8767/8768/8769 (other instances)
if "%PORT%"=="" set PORT=8000

REM Check if port is free; if not, try the next 5 ports
set /a TRIED=0
:check_port
netstat -ano | findstr ":%PORT% " | findstr LISTENING >nul
if %ERRORLEVEL%==0 (
  echo [warn] Port %PORT% is busy, trying next ...
  set /a PORT=%PORT%+1
  set /a TRIED=%TRIED%+1
  if %TRIED% GTR 10 (
    echo [error] No free port in range. Try: set PORT=9500 ^& start.bat
    pause
    exit /b 1
  )
  goto :check_port
)

echo.
echo [start] Trip Share on http://localhost:%PORT%
echo         (DATABASE_URL must be set if you want to use Postgres)
echo.
"%PYTHON_EXE%" server.py
goto :eof

:err
echo.
echo [error] Failed to install dependencies. Check your Python / network.
pause
