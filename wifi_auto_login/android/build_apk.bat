@echo off
rem Rebuild the Android APK (uses the machine-wide toolchain wrapper).
rem Output: app\build\outputs\apk\debug\app-debug.apk
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File C:\chatbox_temp\ai_toolkit\apk_build.ps1 -Project "%~dp0." -Variant debug -NoDaemon
echo.
echo APK: %~dp0app\build\outputs\apk\debug\app-debug.apk
pause
