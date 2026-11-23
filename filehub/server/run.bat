@echo off
chcp 65001 >nul
cd /d "%~dp0"
title FileHub 只读媒体服务 (端口 8730)

rem 已在运行就不重复启动：开机自启 + 手动双击不会撞端口
netstat -ano | findstr /R /C:":8730 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [提示] FileHub 服务已经在运行中，无需重复启动。
    echo        手机端直接打开 App 即可。
    timeout /t 3 >nul
    exit /b 0
)

rem -u：日志不缓冲，窗口里能立刻看到地址和令牌
python -u "%~dp0filehub_server.py"
if errorlevel 1 (
    echo.
    echo [启动失败] 请检查 python 是否在 PATH 中，或查看上方报错。
    timeout /t 20 >nul
)
