@echo off
rem Start ComfyUI headless (Comfy Desktop venv) on port 8000, detached.
set "PY=C:\Users\yourname\Documents\ComfyUI\.venv\Scripts\python.exe"
set "UD=C:\Users\yourname\Documents\ComfyUI"
set "YA=%APPDATA%\Comfy Desktop\instance-model-paths\inst-1788930888828.yaml"
set "LOGDIR=C:\chatbox_temp\comfyui_run"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
cd /d "D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI"
"%PY%" -s ComfyUI\main.py --port 8000 --enable-manager ^
  --base-directory "%UD%" --user-directory "%UD%\user" ^
  --extra-model-paths-config "%YA%" ^
  --input-directory "%UD%\input" --output-directory "%UD%\output" ^
  > "%LOGDIR%\comfy.out.log" 2>&1
