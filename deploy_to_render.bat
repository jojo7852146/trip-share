@echo off
REM 一键推送到 GitHub（推到你自己仓库后 Render 自动部署）。
REM 第一次用：要先去 GitHub 网页建一个空仓库（步骤见 DEPLOY.md）。
REM
REM 用法：
REM   deploy_to_render.bat
REM 默认会推送到 origin/main。如果你仓库叫别的名字，传仓库 URL：
REM   deploy_to_render.bat https://github.com/USERNAME/trip-share.git

setlocal
cd /d "%~dp0"

REM 检查 git
where git >nul 2>nul
if errorlevel 1 (
  echo [error] git 没装。先去 https://git-scm.com/download/win 装一下。
  pause
  exit /b 1
)

REM 检查是否已配置 remote
git remote get-url origin >nul 2>nul
if errorlevel 1 (
  REM 没配置：使用第一个参数或者默认占位
  if "%~1"=="" (
    echo.
    echo [warn] 还没配置 GitHub 仓库。
    echo        1. 去 https://github.com/new 创建一个新仓库（公开私有都行，名字比如 trip-share）
    echo        2. 在下面输入仓库 URL：
    echo.
    set /p REPO_URL= 仓库 URL (例如 https://github.com/你的用户名/trip-share.git):
  ) else (
    set REPO_URL=%~1
  )
  git remote add origin %REPO_URL%
)

echo.
echo [1/4] 检查文件改动 ...
git status --short
echo.

REM 默认不提交 .venv、__pycache__、data/.db 这些大文件
if not exist ".gitignore" (
  echo [info] 写一个 .gitignore ^(排除 .venv 和 data/*.db^)
  (
    echo .venv/
    echo __pycache__/
    echo *.pyc
    echo .deps_installed
    echo data/*.db
    echo data/*.sqlite
    echo .env
  ) > .gitignore
  git add .gitignore
)

REM 询问提交信息
set /p MSG=本次提交信息 ^(回车默认 "update"^):
if "%MSG%"=="" set MSG=update

echo.
echo [2/4] add + commit ...
git add .
git commit -m "%MSG%" --allow-empty
echo.

REM 第一次可能要 push -u
git rev-parse --abbrev-ref HEAD >nul 2>nul
if errorlevel 1 (
  echo [error] 不在 git 分支上。检查：git status
  pause
  exit /b 1
)

echo [3/4] push 到 GitHub ...
git push -u origin main
if errorlevel 1 (
  echo.
  echo [error] push 失败。常见原因：
  echo   - 没登录 GitHub：第一次推送会弹窗口问账号密码（或 token）
  echo   - 远程仓库还没建：去 https://github.com/new 建一个空仓库
  echo   - 网络问题：换个时间或挂代理
  pause
  exit /b 1
)

echo.
echo [4/4] 完成！
echo.
echo ===========================================
echo  下一步：
echo  1. 打开 https://dashboard.render.com
echo  2. New + -^> Blueprint -^> 选你的仓库
echo  3. Render 会自动读 render.yaml，点 Apply
echo  4. 等 3-5 分钟，Dashboard 上会显示你的 URL
echo ===========================================
echo.
pause
