@echo off
chcp 936 >nul
title 诺蒂卡之奴隶们 - 汉化启动
setlocal
set "SVC=C:\chatbox_temp\game-localize"
set "GAME=C:\Users\yourname\Desktop\game！\ss\示例游戏"
set "URL=http://127.0.0.1:8791/health"

curl -s -m 2 %URL% | findstr /c:"ok" >nul
if not errorlevel 1 goto launch

echo [1/2] 启动本机离线翻译引擎（Qwen2.5-1.5B，纯本地，不联网）...
start "翻译服务 Qwen2.5-1.5B" /min cmd /c "cd /d %SVC% && python srv.py --port 8791"

set n=0
:wait
timeout /t 2 >nul
curl -s -m 2 %URL% | findstr /c:"ok" >nul
if not errorlevel 1 goto launch
set /a n+=1
if %n% lss 30 goto wait
echo    翻译引擎没起来，游戏仍会用已缓存的译文启动（首次出现的句子会是日文）。
echo.

:launch
echo [2/2] 启动游戏...
start "" /d "%GAME%\ReiPatcher" "%GAME%\ReiPatcher\ReiPatcher.exe" -c ExampleGame.ini
echo.
echo 游戏已启动。窗口内的快捷键：
echo     Alt+0  翻译控制面板     Alt+T  中/日原文切换     Alt+F  换字体
echo 关掉那个「翻译服务」窗口即可彻底退出翻译引擎。
timeout /t 6 >nul
