@echo off
rem 鐩存帴璋?gradlew 鏋勫缓锛坅pk_build.ps1 鍦ㄢ€滆劚绂荤粓绔€濊繍琛屾椂浼氳鍒ゆ垚 Access is denied锛屽埆鐢級
chcp 65001 >nul
cd /d "%~dp0android"
set "JAVA_HOME=C:\chatbox_temp\chatbox-bridge\tools\jdk17"
set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"
set "ANDROID_SDK_ROOT=%LOCALAPPDATA%\Android\Sdk"
set "VARIANT=%~1"
if "%VARIANT%"=="" set "VARIANT=debug"

gradlew.bat assembleDebug --console=plain --no-daemon > "%~dp0build.log" 2>&1
echo EC=%errorlevel% >> "%~dp0build.log"

echo.
findstr /C:"BUILD SUCCESSFUL" /C:"BUILD FAILED" "%~dp0build.log"
echo 瀹屾暣鏃ュ織: %~dp0build.log
echo APK: %~dp0android\app\build\outputs\apk\debug\app-debug.apk
pause
