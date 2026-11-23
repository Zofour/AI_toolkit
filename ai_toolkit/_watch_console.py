# -*- coding: utf-8 -*-
"""监视 N 秒内所有 class=ConsoleWindowClass 的顶层窗口（用来抓 ffmpeg 弹出的黑框）"""
import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

seen = {}


def scan():
    found = []

    def cb(hwnd, lparam):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS",
                         "PseudoConsoleWindow"):
            t = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, t, 512)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            vis = bool(user32.IsWindowVisible(hwnd))
            found.append((int(pid.value), vis, cls.value[:10] + " | " + t.value))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


dur = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
t0 = time.time()
while time.time() - t0 < dur:
    for item in scan():
        seen[item] = seen.get(item, 0) + 1
    time.sleep(0.05)

print("窗口 (pid | 可见 | 标题) —— 采样次数:")
for k, v in seen.items():
    print(f"  {k[0]:>6} | {'vis' if k[1] else 'hid'} | {k[2]!r}   x{v}")
