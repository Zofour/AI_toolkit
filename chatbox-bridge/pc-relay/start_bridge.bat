@echo off
chcp 65001 >nul
cd /d %~dp0
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title Chatbox Bridge 启动器
echo [1/4] 检查 Chatbox 调试端口(9333)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_bridge_pre.ps1"
echo [2/4] 启动中继...
start "Chatbox Bridge Relay" cmd /k "python run.py"
timeout /t 4 >nul
echo [3/4] 启动注入器...
start "Chatbox Bridge Injector" cmd /k "python chatbox_inject.py --cdp 9333"
echo.
echo [4/4] Moving bridge windows to desktop 2...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_bridge_post.ps1"
echo.
echo 完成：保持弹出的两个窗口开着，手机端即可回控。
pause