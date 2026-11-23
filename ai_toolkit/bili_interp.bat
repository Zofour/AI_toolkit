@echo off
chcp 65001 >nul
setlocal
set "PYTHONIOENCODING=utf-8"
set "PATH=C:\ProgramData\chocolatey\bin;%LOCALAPPDATA%\Programs\Python\Python313;%PATH%"
title Bili Interp (RIFE + NVENC)
python "C:\chatbox_temp\ai_toolkit\bili_interp_fast.py" %*
echo.
pause
