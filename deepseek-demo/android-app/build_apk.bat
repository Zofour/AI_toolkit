@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0sync_web.ps1" || exit /b 1
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\chatbox_temp\ai_toolkit\apk_build.ps1" -Project "%~dp0." -Variant debug -NoDaemon %*
