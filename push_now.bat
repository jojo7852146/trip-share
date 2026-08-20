@echo off
REM Push trip-share to GitHub. All-ASCII echo to avoid GBK garbled output in CMD.

setlocal
set PATH=C:\Users\Administrator\.workbuddy-ai\vendor\PortableGit\mingw64\bin;%PATH%

cd /d "C:\Users\Administrator\WorkBuddy AI\2026-08-19-13-48-28\trip-share"

echo.
echo ============================================================
echo  STEP 1/3 - check git works
echo ============================================================
git --version
if errorlevel 1 goto :no_git

echo.
echo ============================================================
echo  STEP 2/3 - check status
echo ============================================================
git status --short
echo ----------------------------------------
echo   (M  = modified, A  = added, ?? = untracked)
echo.

echo ============================================================
echo  STEP 3/3 - push to GitHub
echo ============================================================
echo.
echo   You will be asked:
echo     Username: jojo7852146
echo     Password: paste your PAT (NOT your GitHub password!)
echo.
echo   >>> Press Enter to start pushing.
echo.
pause

git push -u origin main
set RC=%errorlevel%

echo.
echo ============================================================
if %RC% NEQ 0 (
    echo  PUSH FAILED. errorlevel=%RC%. See messages above.
    echo  Common fixes:
    echo    - Wrong PAT: re-generate at https://github.com/settings/tokens
    echo    - Repo doesn't exist: create it at https://github.com/new
    echo    - Network: try again later
) else (
    echo  PUSH SUCCEEDED!
    echo.
    echo  Next: open https://dashboard.render.com
    echo         New +  -^>  Blueprint  -^>  jojo7852146/trip-share  -^>  Apply
)
echo ============================================================
pause
exit /b %RC%

:no_git
echo [error] git not found even after PATH fix. Check WorkBuddy installation.
pause
exit /b 1