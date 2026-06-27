@echo off
chcp 65001 >nul
title 小红书带货系统监控台

echo ============================================
echo   小红书带货系统监控台
echo ============================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)
echo [OK] Python 已就绪

where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Node.js，请先安装 Node.js
    pause
    exit /b 1
)
echo [OK] Node.js 已就绪
echo.

echo [1/2] 启动 Web API 服务 (端口 8000)...
start "小红书 WebAPI" cmd /c "cd /d E:\titkok\web-api && python main.py"

echo [2/2] 启动 Web UI 服务 (端口 3000)...
start "小红书 WebUI" cmd /c "cd /d E:\titkok\web-ui && npm start"

echo.
echo ============================================
echo   所有服务已启动！
echo   - Web API: http://localhost:8000
echo   - Web UI:  http://localhost:3000
echo ============================================
echo.
echo 关闭此窗口不会影响已启动的服务。
echo.

pause