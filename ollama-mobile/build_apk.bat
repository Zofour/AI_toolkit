@echo off
chcp 65001 >nul
setlocal
echo ==========================================
echo  Ollama 口袋 - 重新构建 APK
echo ==========================================
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\chatbox_temp\ai_toolkit\apk_build.ps1" -Project "C:\chatbox_temp\ollama-mobile\android" -NoDaemon
echo.
echo APK: C:\chatbox_temp\ollama-mobile\android\app\build\outputs\apk\debug\app-debug.apk
pause
