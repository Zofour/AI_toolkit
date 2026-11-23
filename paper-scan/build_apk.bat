@echo off
chcp 65001 >nul
rem 重新构建「文档扫描」APK（统一走本机 apk_build.ps1，勿手写 JAVA_HOME）
set PROJ=%~dp0android
powershell -File C:\chatbox_temp\ai_toolkit\apk_build.ps1 -Project "%PROJ%" -Variant debug -NoDaemon
if errorlevel 1 goto fail
copy /y "%PROJ%\app\build\outputs\apk\debug\app-debug.apk" "%~dp0文档扫描.apk" >nul
echo.
echo 构建完成: %~dp0文档扫描.apk
echo 安装到手机: adb install -r "%~dp0文档扫描.apk"
pause
exit /b 0
:fail
echo 构建失败，看上面的日志
pause
exit /b 1
