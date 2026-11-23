@echo off
chcp 65001 >nul
cd /d %~dp0
set "JAVA_HOME=C:\chatbox_temp\chatbox-bridge\tools\jdk17"
set "ANDROID_HOME=C:\Users\yourname\AppData\Local\Android\Sdk"
set "ANDROID_SDK_ROOT=%ANDROID_HOME%"
echo Building APK (first run ~2 min)...
call gradlew.bat assembleDebug --console=plain
echo.
echo APK: app\build\outputs\apk\debug\app-debug.apk
pause
