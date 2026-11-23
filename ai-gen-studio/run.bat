@echo off
cd /d %~dp0
title AI Gen Studio
echo ==================================================
echo   AI Gen Studio
echo   1) Make sure ComfyUI Desktop is running (port 8000)
echo   2) Make sure Ollama is running (port 11434)
echo   3) Browser will open  http://127.0.0.1:5000
echo ==================================================
start "" http://127.0.0.1:5000
python app.py
pause
