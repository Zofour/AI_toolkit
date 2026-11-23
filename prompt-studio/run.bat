@echo off
rem Prompt Studio launcher  (double-click to start)
cd /d "%~dp0"
set "PYW=C:\Users\yourname\AppData\Local\Programs\Python\Python313\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%~dp0app.py"
