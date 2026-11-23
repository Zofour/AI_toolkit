@echo off
chcp 65001 >nul
setlocal
REM ===================== EDIT THESE =====================
REM  1) UPSTREAM_BASE : your REAL model provider base URL (keep the /v1)
set "UPSTREAM_BASE=https://api.deepseek.com/v1"
REM  2) translation engine:  local = bundled Qwen2.5-1.5B | openai = local Ollama/LM Studio
set "TRANSLATOR_BACKEND=openai"
set "TRANSLATOR_API_BASE=http://127.0.0.1:11434/v1"
set "TRANSLATOR_API_MODEL=gemma3:12b"
REM  3) MODEL_DIR : used only when TRANSLATOR_BACKEND=local
set "MODEL_DIR=%~dp0models\Qwen2.5-1.5B-Instruct"
REM  4) PORT : local listen port
set "PORT=8788"
REM ======================================================
REM  TRANSLATE_CONTENT=1 also translates the final answer (default 0 = only thinking)
set "TRANSLATE_CONTENT=0"
set "PYTHONIOENCODING=utf-8"

echo Starting thinking-translator proxy on http://127.0.0.1:%PORT%
echo   upstream  = %UPSTREAM_BASE%
echo   engine    = %TRANSLATOR_BACKEND%  %TRANSLATOR_API_MODEL%
echo.
python "%~dp0proxy.py"
pause
