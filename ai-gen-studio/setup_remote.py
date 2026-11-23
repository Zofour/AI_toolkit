# -*- coding: utf-8 -*-
"""生成远程启动脚本 + 防火墙放行脚本 + 桌面快捷方式。bat 一律 GBK + CRLF。"""
import os
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
GBK = 'gbk'
PY = r'C:\Users\yourname\AppData\Local\Programs\Python\Python313\python.exe'
DESKTOP = os.path.join(os.environ['USERPROFILE'], 'Desktop')

BAT_HELPER = '''@echo off
rem 由「AI Gen Studio 远程.bat」以管理员身份调起：只是放行 TCP 8848（仅 Private 配置）
netsh advfirewall firewall delete rule name="AI Gen Studio 8848" >nul 2>&1
netsh advfirewall firewall add rule name="AI Gen Studio 8848" dir=in action=allow protocol=TCP localport=8848 profile=private
exit /b 0
'''

BAT_MAIN = '''@echo off
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
set "PY={PY}"
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
'''.replace('{PY}', PY)


def w(path, text, enc=GBK):
    with open(path, 'wb') as f:
        f.write(text.replace('\r\n', '\n').replace('\n', '\r\n').encode(enc, 'ignore'))
    print('写入:', path)


def main():
    main_bat = os.path.join(BASE, 'AI Gen Studio 远程.bat')
    w(main_bat, BAT_MAIN)

    # 桌面快捷方式（显示名就叫 AI Gen Studio 远程.bat）
    lnk = os.path.join(DESKTOP, 'AI Gen Studio 远程.bat.lnk')
    ico = os.path.join(BASE, 'icon.ico')
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{lnk}'); "
        f"$s.TargetPath = '{main_bat}'; "
        f"$s.WorkingDirectory = '{BASE}'; "
        f"$s.IconLocation = '{ico}'; "
        "$s.Description = 'AI Gen Studio 远程模式 (Tailscale)'; "
        "$s.Save(); Write-Output 'shortcut ok'"
    )
    r = subprocess.run(['powershell', '-NoProfile', '-Command', ps],
                       capture_output=True, text=True)
    print(r.stdout.strip(), r.stderr.strip())
    print('快捷方式存在:', os.path.isfile(lnk))
    print('bat 存在:', os.path.isfile(main_bat))


if __name__ == '__main__':
    main()
