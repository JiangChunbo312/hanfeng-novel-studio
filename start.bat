@echo off
chcp 65001 >nul
cd /d %~dp0
title Hanfeng Novel Studio

REM ---------- 找 Python ----------
set "PY=C:\Users\Administrator\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if exist "%PY%" goto probe
set "PY=python"
where python >nul 2>&1
if "%errorlevel%"=="0" goto probe

echo.
echo  [错误] 找不到 Python，无法启动工作台。
echo  已尝试: WorkBuddy 自带 Python、以及 PATH 中的 python
echo.
pause
exit /b 1

REM ---------- 探活 ----------
:probe
"%PY%" -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8787/api/health',timeout=2)" >nul 2>&1
if "%errorlevel%"=="0" goto up

echo.
echo   寒峰小说工作台    http://127.0.0.1:8787
echo.
echo  [未运行] 正在启动服务，页面会自动弹出...
echo  这个窗口要留着，关掉它服务就停了。
echo.
"%PY%" server.py
pause
exit /b 0

REM ---------- 已在运行 ----------
:up
echo.
echo   寒峰小说工作台    http://127.0.0.1:8787
echo.
echo  [已在运行] 直接打开页面...
start "" "http://127.0.0.1:8787/"
pause
exit /b 0
