@echo off
chcp 65001 >nul
cd /d %~dp0
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
title Chatbox Bridge 临时文件清理
python cleanup.py
echo.
pause