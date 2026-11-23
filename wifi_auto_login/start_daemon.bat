@echo off
cd /d "%~dp0"
echo 正在启动 BUCT 校园网自动登录（后台守护，无窗口）...
wscript "%~dp0start_hidden.vbs"
ping -n 3 127.0.0.1 >nul
echo.
python "%~dp0srun_autologin.py" --status
echo.
echo 日志文件: %~dp0autologin.log
echo 关闭本窗口不影响后台守护。
ping -n 6 127.0.0.1 >nul
