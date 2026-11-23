@echo off
rem Debug launcher with console: shows full traceback
cd /d "%~dp0"
set "PY=C:\Users\yourname\AppData\Local\Programs\Python\Python313\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" app.py
echo.
echo Exited. Press any key to close this window.
pause >nul
