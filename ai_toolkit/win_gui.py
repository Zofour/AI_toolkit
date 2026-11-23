#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
win_gui.py —— Windows 桌面「看屏 + 点击」小工具（无第三方 GUI 依赖，只用 PIL + ctypes）

用法:
  python win_gui.py list                          列出所有可见顶层窗口(标题/类名/句柄/屏幕矩形/客户区)
  python win_gui.py shot [-o out.png]             截全屏 -> PNG，并打印 JSON(屏幕物理分辨率)
  python win_gui.py shot --title 微信 [-o w.png]  只截标题含「微信」的窗口(含窗口矩形 JSON)
  python win_gui.py shot --hwnd 394684 -o w.png   只截指定句柄窗口
  python win_gui.py click X Y [--double] [--button left|right] [--restore] [--settle 0.35]
  python win_gui.py move  X Y
  python win_gui.py drag  X1 Y1 X2 Y2 [--dur 0.6]
  python win_gui.py key   "ctrl+v" | "enter" | "hello" [--settle 0.2]

约定: 所有坐标都是**屏幕物理像素**(DPI 感知后)，与 shot 图内像素一一对应(全屏截图)。
窗口截图的坐标换算: 屏幕坐标 = 窗口图内坐标 + 该窗口 rect 的 left/top。
"""
import argparse, ctypes, ctypes.wintypes as wt, json, sys, time, os

user32 = ctypes.windll.user32
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        user32.SetProcessDPIAware()

SW_RESTORE, SW_SHOW = 9, 5
INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE = 0x0001, 0x8000
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004

DWORD = wt.DWORD
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", DWORD),
                ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", DWORD),
                ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", ctypes.c_ushort), ("wParamH", ctypes.c_ushort)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", DWORD), ("u", _U)]


def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _mouse(flags, dx=0, dy=0, data=0):
    return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(dx, dy, data, flags, 0, 0))


def _key(vk=0, scan=0, flags=0):
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, scan, flags, 0, 0))


# ---------------- 枚举窗口 ----------------
def enum_windows():
    out = []
    EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 2)
        user32.GetWindowTextW(hwnd, buf, n + 2)
        title = buf.value
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        r = RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
        cr = RECT(); user32.GetClientRect(hwnd, ctypes.byref(cr))
        tl = POINT(cr.left, cr.top); user32.ClientToScreen(hwnd, ctypes.byref(tl))
        pid = DWORD(); user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if n > 0 or (r.right - r.left) > 200:
            out.append({
                "hwnd": int(hwnd), "title": title, "class": cls.value,
                "pid": pid.value,
                "rect": [r.left, r.top, r.right, r.bottom],
                "w": r.right - r.left, "h": r.bottom - r.top,
                "client_screen_xy": [tl.x, tl.y],
                "client_wh": [cr.right - cr.left, cr.bottom - cr.top],
            })
        return True

    user32.EnumWindows(EnumProc(cb), 0)
    return out


def find_window(title=None, hwnd=None):
    if hwnd:
        r = RECT(); user32.GetWindowRect(hwnd, ctypes.byref(r))
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 2); user32.GetWindowTextW(hwnd, buf, n + 2)
        return {"hwnd": hwnd, "title": buf.value,
                "rect": [r.left, r.top, r.right, r.bottom],
                "w": r.right - r.left, "h": r.bottom - r.top}
    wins = [w for w in enum_windows() if title and title.lower() in (w["title"] or "").lower()]
    if not wins:
        return None
    wins.sort(key=lambda w: w["w"] * w["h"], reverse=True)
    return wins[0]


# ---------------- 截图 ----------------
def _draw_marks(img, origin, marks, color=(255, 0, 0)):
    """在图上画红十字符号，用于校准「我要点的屏幕坐标 = 图上什么位置」"""
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    for (mx, my) in marks:
        x, y = mx - origin[0], my - origin[1]
        d.line([(x - 26, y), (x + 26, y)], fill=color, width=3)
        d.line([(x, y - 26), (x, y + 26)], fill=color, width=3)
        d.ellipse([x - 4, y - 4, x + 4, y + 4], outline=color, width=3)
    return img


def shot(out, title=None, hwnd=None, full=False, restore=False, settle=0.3, marks=None):
    from PIL import ImageGrab
    info = {}
    marks = marks or []
    if title or hwnd:
        w = find_window(title, hwnd)
        if not w:
            print(json.dumps({"error": "window not found", "title": title, "hwnd": hwnd}, ensure_ascii=False))
            return 2
        if restore:
            user32.ShowWindow(w["hwnd"], SW_RESTORE)
            user32.SetForegroundWindow(w["hwnd"])
            time.sleep(settle)
            w = find_window(title, w["hwnd"])
        l, t, r, b = w["rect"]
        img = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)
        if marks:
            _draw_marks(img, (l, t), marks)
        info = {"mode": "window", **w}
        info["marks_screen"] = [[int(a), int(b)] for a, b in marks]
        info["marks_in_png"] = [[int(a - l), int(b - t)] for a, b in marks]
    else:
        img = ImageGrab.grab(all_screens=True)
        if marks:
            _draw_marks(img, (0, 0), marks)
        info = {"mode": "fullscreen", "size": list(img.size),
                "marks_screen": [[int(a), int(b)] for a, b in marks],
                "virtual_screen": [user32.GetSystemMetrics(76), user32.GetSystemMetrics(77),
                                   user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)]}
    img.save(out)
    info["png"] = os.path.abspath(out)
    info["png_size"] = list(img.size)
    info["cursor"] = [p.x for p in [POINT()]] and None or None
    p = POINT(); user32.GetCursorPos(ctypes.byref(p))
    info["cursor"] = [p.x, p.y]
    print(json.dumps(info, ensure_ascii=False))
    return 0


# ---------------- 点击 / 移动 ----------------
def move(x, y):
    user32.SetCursorPos(int(x), int(y))


def click(x, y, double=False, button="left", settle=0.35, restore=None):
    if restore:
        user32.ShowWindow(restore, SW_RESTORE)
        user32.SetForegroundWindow(restore)
        time.sleep(settle)
    move(x, y)
    time.sleep(0.05)
    dn, up = ((MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP) if button == "left"
              else (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP))
    _send(_mouse(dn)); time.sleep(0.04); _send(_mouse(up))
    if double:
        time.sleep(0.06); _send(_mouse(dn)); time.sleep(0.04); _send(_mouse(up))
    print(json.dumps({"clicked": [int(x), int(y)], "button": button, "double": double}, ensure_ascii=False))


def drag(x1, y1, x2, y2, dur=0.6, steps=24):
    move(x1, y1); time.sleep(0.12)
    _send(_mouse(MOUSEEVENTF_LEFTDOWN)); time.sleep(0.08)
    for i in range(1, steps + 1):
        move(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
        time.sleep(dur / steps)
    _send(_mouse(MOUSEEVENTF_LEFTUP))
    print(json.dumps({"dragged": [[int(x1), int(y1)], [int(x2), int(y2)]]}, ensure_ascii=False))


def focus(title=None, hwnd=None, settle=0.6):
    """把窗口恢复并抢到前台。Windows 有前台锁，直接 SetForegroundWindow 常失败，
    这里用经典的『先注入一次 ALT 键 → 再 SetForegroundWindow』绕过。"""
    w = find_window(title, hwnd)
    if not w:
        print(json.dumps({"error": "window not found", "title": title, "hwnd": hwnd}, ensure_ascii=False))
        return 2
    h = w["hwnd"]
    user32.ShowWindow(h, SW_RESTORE)
    time.sleep(0.1)
    # ALT 空按一下，向系统声明“本线程正在响应输入”，从而允许抢前台
    _send(_key(0x12), _key(0x12, flags=KEYEVENTF_KEYUP))
    time.sleep(0.05)
    ok = user32.SetForegroundWindow(h)
    if not ok:
        # 退而求其次：临时置顶一下再取消
        HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
        SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040
        user32.SetWindowPos(h, ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        time.sleep(0.25)
        user32.SetWindowPos(h, ctypes.c_void_p(HWND_NOTOPMOST), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.SetForegroundWindow(h)
    time.sleep(settle)
    fg = user32.GetForegroundWindow()
    print(json.dumps({"focused": h, "setForeground_ok": bool(ok), "is_foreground": fg == h,
                      "fg_hwnd": int(fg), **find_window(title, h)}, ensure_ascii=False))
    return 0


VK = {"enter": 0x0D, "esc": 0x1B, "tab": 0x09, "space": 0x20, "backspace": 0x08,
      "del": 0x2E, "delete": 0x2E, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
      "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
      "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
      "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
      "a": 0x41, "c": 0x43, "v": 0x56, "x": 0x58, "z": 0x5A, "s": 0x53}


def type_text(s, settle=0.2):
    for ch in s:
        if ch == "\n":
            _send(_key(VK["enter"]), _key(VK["enter"], flags=KEYEVENTF_KEYUP))
        else:
            _send(_key(scan=ord(ch), flags=KEYEVENTF_UNICODE),
                  _key(scan=ord(ch), flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        time.sleep(0.012)
    time.sleep(settle)


def key(spec, settle=0.25):
    parts = [p.strip().lower() for p in spec.split("+")]
    mods, last = parts[:-1], parts[-1]
    if last in VK:
        seq = [_key(VK[m]) for m in mods] + [_key(VK[last]), _key(VK[last], flags=KEYEVENTF_KEYUP)] \
              + [_key(VK[m], flags=KEYEVENTF_KEYUP) for m in reversed(mods)]
        _send(*seq)
    else:
        type_text(spec)
    time.sleep(settle)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "shot", "click", "move", "drag", "key", "focus"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("-o", "--out", default="shot.png")
    ap.add_argument("--title")
    ap.add_argument("--hwnd", type=int)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--double", action="store_true")
    ap.add_argument("--button", default="left")
    ap.add_argument("--settle", type=float, default=0.35)
    ap.add_argument("--dur", type=float, default=0.6)
    ap.add_argument("--mark", action="append", default=[],
                    help="截图前在指定屏幕坐标画红十字(校准用)，可多次: --mark 1075,355")
    a = ap.parse_args()

    if a.cmd == "list":
        for w in sorted(enum_windows(), key=lambda w: -w["w"] * w["h"]):
            print(f'hwnd={w["hwnd"]:>8} pid={w["pid"]:>6} {w["w"]:>5}x{w["h"]:<5} @({w["rect"][0]},{w["rect"][1]}) '
                  f'class={w["class"]:<28} title={w["title"]!r}')
        return 0
    if a.cmd == "shot":
        marks = [tuple(int(v) for v in m.split(",")) for m in a.mark]
        return shot(a.out, a.title, a.hwnd, a.full, marks=marks)
    if a.cmd == "focus":
        return focus(a.title, a.hwnd, a.settle)
    if a.cmd == "click":
        x, y = float(a.args[0]), float(a.args[1])
        click(x, y, a.double, a.button, a.settle, restore=(find_window(a.title, a.hwnd) or {}).get("hwnd") if a.restore else None)
        return 0
    if a.cmd == "move":
        move(float(a.args[0]), float(a.args[1])); return 0
    if a.cmd == "drag":
        drag(*(float(v) for v in a.args[:4]), dur=a.dur); return 0
    if a.cmd == "key":
        key(a.args[0], a.settle); return 0


if __name__ == "__main__":
    sys.exit(main())
