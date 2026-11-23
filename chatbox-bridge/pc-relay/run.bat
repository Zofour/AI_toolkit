@echo off
chcp 65001 >nul
cd /d %~dp0
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title Chatbox Bridge Relay
echo === Starting Chatbox Bridge relay ===
python run.py %*
echo.
echo (relay exited, press any key to close)
pause >nul
