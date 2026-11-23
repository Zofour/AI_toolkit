@echo off
chcp 936 >nul
cd /d %~dp0
title AI Gen Studio 远程模式 (Tailscale)
cls
echo ============================================================
echo    AI Gen Studio  -  远程模式
echo    只绑定 Tailscale 地址，局域网其他设备访问不到
echo ============================================================
echo.

rem ---------- 防火墙：尝试放行 TCP 8848（无管理员权限会静默失败） ----------
netsh advfirewall firewall show rule name="AI Gen Studio 8848" >nul 2>&1
if errorlevel 1 (
    netsh advfirewall firewall add rule name="AI Gen Studio 8848" dir=in action=allow protocol=TCP localport=8848 profile=private >nul 2>&1
    if errorlevel 1 (
        echo [提示] 未能自动放行防火墙（需管理员权限）。
        echo        若手机连不上，请右键本文件 -^> 以管理员身份运行。
        echo.
    )
)

rem ---------- 启动 ----------
set "PY=C:\Users\yourname\AppData\Local\Programs\Python\Python313\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" app.py --remote

echo.
echo ============================================================
echo   服务已退出。若手机连不上，依次检查：
echo     1) 手机 Tailscale 是否在线
echo     2) 手机 App 里的地址是否与上面打印的一致
echo     3) 电脑防火墙是否放行了 TCP 8848
echo ============================================================
pause
