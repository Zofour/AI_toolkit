#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FileHub —— 电脑端“只读”媒体文件服务。

设计原则：
  * 只读。服务端没有任何写/删/改接口，只暴露 GET（+HEAD）。
  * 令牌鉴权。手机端所有请求都要带 t=<token>。
  * 支持 HTTP Range，视频可以随便拖进度条。
  * 缩略图：图片用 Pillow，视频用 ffmpeg 抽帧，结果落盘缓存。

端点：
  GET /api/ping                                健康检查
  GET /api/roots                               列出配置的根目录
  GET /api/list?path=<rel>[&all=1][&sort=name|date]   列目录
  GET /f?path=<rel>                            原文件（支持 Range）
  GET /t?path=<rel>&w=400                      缩略图 JPEG
"""
from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

BASE = Path(__file__).resolve().parent
CONFIG_PATH = BASE / "config.json"
CACHE_DIR = BASE / "cache"

IMAGE_EXT = {".jpg", ".jpeg", ".jfif", ".png", ".gif", ".webp", ".bmp",
             ".heic", ".heif", ".avif", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".mov", ".avi", ".webm", ".flv",
             ".wmv", ".3gp", ".ts", ".m2ts", ".mpg", ".mpeg", ".rmvb",
             ".flv"}   # flv：Media3 自带 FlvExtractor，H.264/AAC 的 FLV 可直接串流播

# 整盘共享时过滤掉这些系统目录
SKIP_NAMES = {"System Volume Information", "RECYCLER", "RECYCLED",
              "$RECYCLE.BIN", "config.msi", "pagefile.sys", "hiberfil.sys",
              "swapfile.sys", "DumpStack.log.tmp", "found.000", "$windows.~bt", "$windows.~ws"}
SKIP_NAMES_LC = {n.lower() for n in SKIP_NAMES}

CTYPE_OVERRIDE = {
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/mp4",
    ".mkv": "video/x-matroska", ".webm": "video/webm",
    ".flv": "video/x-flv",
    ".3gp": "video/3gpp", ".ts": "video/mp2t",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".jfif": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
    ".heic": "image/heic", ".heif": "image/heif",
}

FFMPEG = shutil.which("ffmpeg") or r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"
_lock_thumb = threading.BoundedSemaphore(4)


# ----------------------------------------------------------------------------
# 配置
# ----------------------------------------------------------------------------
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"找不到配置文件：{CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("port", 8730)
    cfg.setdefault("bind", "0.0.0.0")
    cfg.setdefault("token", "")
    cfg.setdefault("thumb_quality", 82)
    cfg["roots"] = {str(k): str(v) for k, v in (cfg.get("roots") or {}).items()}
    return cfg


CFG = load_config()
PORT = int(CFG["port"])
TOKEN = str(CFG["token"])
THUMB_Q = int(CFG.get("thumb_quality", 82))
AUTO_DRIVES = bool(CFG.get("auto_drives", True))
# 根名字里不能有斜杠，否则路径解析会乱
STATIC_ROOTS: dict[str, Path] = {}
for _name, _path in CFG["roots"].items():
    STATIC_ROOTS[_name.replace("/", "_").replace("\\", "_")] = Path(_path)


def _volume_label(root: str) -> str:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), buf, 261, None, None, None, fs, 261)
        return buf.value.strip() if ok else ""
    except Exception:
        return ""


def list_drives() -> list[tuple[str, str, str]]:
    """枚举当前可用的本地/可移动磁盘 -> [(盘符, 类型, 卷标)]。
    每次调用都实时枚举，所以中途插上的 U 盘无需重启服务。
    """
    import ctypes
    TYPES = {2: "removable", 3: "fixed", 6: "ram"}
    out = []
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except Exception:
        return out
    for i, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        if not (mask >> i) & 1:
            continue
        root = f"{letter}:\\"
        kind = TYPES.get(ctypes.windll.kernel32.GetDriveTypeW(root), "other")
        if kind not in ("fixed", "removable"):
            continue                      # 跳过光驱 / 网络盘 / 虚拟盘
        # 空读卡器：盘符在但读不了
        if not os.path.isdir(root):
            continue
        try:
            if ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    ctypes.c_wchar_p(root), None, None, None) == 0:
                continue
        except Exception:
            pass
        out.append((letter, kind, _volume_label(root)))
    return out


def current_roots() -> dict[str, Path]:
    """静态配置目录 + 全部磁盘（实时枚举）。"""
    roots = dict(STATIC_ROOTS)
    if not AUTO_DRIVES:
        return roots
    for letter, kind, label in list_drives():
        if kind == "removable":
            name = f"U盘 {letter}:" + (f" {label}" if label else "")
        else:
            name = f"{letter}盘" + (f" {label}" if label else "")
        roots.setdefault(name, Path(f"{letter}:\\"))
    return roots


def kind_of(path: str, is_dir: bool) -> str:
    if is_dir:
        return "dir"
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    return "file"


# ----------------------------------------------------------------------------
# Windows 快捷方式（.lnk）—— 桌面上指向图片/视频的快捷方式也要能在手机上看
# ----------------------------------------------------------------------------
_lnk_cache: dict[tuple[str, float], str | None] = {}
_lnk_lock = threading.Lock()
_tls = threading.local()


def _lnk_binary(path: str) -> str | None:
    """纯 Python 解析 .lnk（pywin32 不可用时的兜底）。"""
    def _ansiz(data, off):
        end = data.find(b"\x00", off)
        return data[off:end].decode("mbcs", "replace") if end > 0 else ""

    def _utf16z(data, off):
        buf = bytearray()
        i = off
        while i + 1 < len(data):
            ch = data[i:i + 2]
            if ch == b"\x00\x00":
                break
            buf += ch
            i += 2
        return bytes(buf).decode("utf-16-le", "replace")

    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if len(data) < 76 or data[:4] != b"\x4c\x00\x00\x00":
        return None
    import struct
    flags = struct.unpack_from("<I", data, 20)[0]
    off = 76
    if flags & 0x01:                     # HasLinkTargetIDList
        off += 2 + struct.unpack_from("<H", data, off)[0]
    target = None
    if flags & 0x02:                     # HasLinkInfo
        li = off
        try:
            li_size, li_hdr = struct.unpack_from("<II", data, li)
            lbl = struct.unpack_from("<I", data, li + 16)[0]
            sfx = struct.unpack_from("<I", data, li + 24)[0]
            lbl_u = sfx_u = 0
            if li_hdr >= 0x24:
                lbl_u = struct.unpack_from("<I", data, li + 28)[0]
                sfx_u = struct.unpack_from("<I", data, li + 32)[0]
            base = _utf16z(data, li + lbl_u) if lbl_u else (_ansiz(data, li + lbl) if lbl else "")
            tail = _utf16z(data, li + sfx_u) if sfx_u else (_ansiz(data, li + sfx) if sfx else "")
            if base:
                target = base + tail
        except Exception:
            pass
    if not target:                       # EnvironmentVariableDataBlock
        sig = data.find(b"\x01\x00\x00\xa0")
        if sig > 0:
            target = _utf16z(data, sig + 4 + 260) or None
    return os.path.expandvars(target) if target else None


def lnk_target(path: str) -> str | None:
    """取 .lnk 的目标路径。COM（最准）→ 二进制解析兜底；带缓存。"""
    try:
        key = (os.path.normcase(path), os.path.getmtime(path))
    except OSError:
        return None
    with _lnk_lock:
        if key in _lnk_cache:
            return _lnk_cache[key]

    target = None
    try:
        shell = getattr(_tls, "shell", None)
        if shell is None:
            import pythoncom
            from win32com.client import Dispatch
            pythoncom.CoInitialize()
            shell = Dispatch("WScript.Shell")
            _tls.shell = shell
        target = shell.CreateShortcut(path).TargetPath or None
    except Exception:
        target = None
    if not target:
        target = _lnk_binary(path)

    with _lnk_lock:
        if len(_lnk_cache) > 4096:
            _lnk_cache.clear()
        _lnk_cache[key] = target
    return target


def _norm(p: str) -> str:
    return os.path.normcase(os.path.realpath(p))


def _inside_roots(real_path: str) -> bool:
    """目标是否落在任一共享根之内（快捷方式可能指到另一个盘）。"""
    p = _norm(real_path)
    for rp in current_roots().values():
        rr = _norm(str(rp))
        if p == rr:
            return True
        prefix = rr if rr.endswith(os.sep) else rr + os.sep
        if p.startswith(prefix):
            return True
    return False


# ----------------------------------------------------------------------------
# 路径安全
# ----------------------------------------------------------------------------
def resolve(rel: str) -> tuple[str | None, str | None]:
    """把 '根名/子目录/文件.mp4' 解析成绝对路径；越界或非法一律抛异常。"""
    rel = (rel or "").replace("\\", "/").strip("/")
    if rel == "":
        return None, None
    parts = rel.split("/")
    for p in parts:
        if p in ("", ".", ".."):
            raise ValueError("非法路径")
    root_name = parts[0]
    all_roots = current_roots()
    if root_name not in all_roots:
        raise KeyError(root_name)
    root = all_roots[root_name]
    cand = os.path.join(str(root), *parts[1:])
    real_path = os.path.realpath(cand)

    # .lnk 快捷方式 -> 换成目标路径（手机端看到的是目标本身的内容）
    if real_path.lower().endswith(".lnk"):
        tgt = lnk_target(real_path)
        if not tgt:
            raise ValueError("快捷方式无法解析")
        if not os.path.exists(tgt):
            raise ValueError("快捷方式指向的目标不存在")
        real_path = os.path.realpath(tgt)

    # 越界检查：目标可能落在别的盘，所以按“是否在任一共享根内”判
    if not _inside_roots(real_path):
        raise ValueError("路径越界")
    return root_name, real_path


# ----------------------------------------------------------------------------
# 缩略图
# ----------------------------------------------------------------------------
def thumb_cache_path(fp: str, w: int) -> Path:
    try:
        mtime = int(os.path.getmtime(fp))
    except OSError:
        mtime = 0
    key = hashlib.sha1(f"{fp}|{mtime}|{w}".encode("utf-8", "surrogatepass")).hexdigest()
    return CACHE_DIR / f"{key}.jpg"


def make_image_thumb(fp: str, w: int) -> bytes:
    from PIL import Image, ImageOps
    im = Image.open(fp)
    try:
        im.draft("RGB", (w * 2, w * 2))          # JPEG 快速降采样，省内存
    except Exception:
        pass
    im = ImageOps.exif_transpose(im)
    im.thumbnail((w, w), Image.LANCZOS)
    if im.mode != "RGB":
        im = im.convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=THUMB_Q, optimize=True)
    return buf.getvalue()


def make_video_thumb(fp: str, w: int) -> bytes:
    if not FFMPEG or not os.path.exists(FFMPEG):
        raise RuntimeError("ffmpeg 不可用")
    for seek in ("1", "0"):
        cmd = [FFMPEG, "-v", "error", "-nostdin", "-ss", seek, "-i", fp,
               "-frames:v", "1", "-vf", f"scale={w}:-2:flags=fast_bilinear",
               "-q:v", "4", "-f", "mjpeg", "pipe:1"]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=25).stdout
        except Exception:
            out = b""
        if out and len(out) > 512:
            return out
    raise RuntimeError("抽帧失败")


def build_thumb(fp: str, w: int) -> tuple[bytes, bool]:
    """返回 (jpeg 字节, 是否来自缓存)"""
    w = max(48, min(int(w), 3000))
    cache = thumb_cache_path(fp, w)
    if cache.exists() and cache.stat().st_size > 512:
        return cache.read_bytes(), True
    k = kind_of(fp, False)
    if k == "image":
        data = make_image_thumb(fp, w)
    elif k == "video":
        with _lock_thumb:
            data = make_video_thumb(fp, w)
    else:
        raise RuntimeError("不支持的类型")
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(cache)
    except Exception:
        pass
    return data, False


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FileHub/1.0"
    disable_nagle_algorithm = True
    timeout = 120

    # ---------------- 基础输出 ----------------
    def _hdr(self, code: int, ctype: str, length: int, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def js(self, obj, code: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._hdr(code, "application/json; charset=utf-8", len(body),
                  {"Cache-Control": "no-store"})
        if self.command != "HEAD":
            self._safe_write(body)

    def err(self, msg: str, code: int = 400):
        self.js({"error": msg}, code)

    def _safe_write(self, data: bytes):
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    # ---------------- 路由 ----------------
    def do_GET(self):
        self.route()

    def do_HEAD(self):
        self.route()

    def log_message(self, fmt, *args):  # 精简日志
        sys.stdout.write("%s  %s\n" % (time.strftime("%H:%M:%S"), fmt % args))
        sys.stdout.flush()

    def route(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        path = unquote(u.path)

        if path == "/api/ping":
            return self.js({"ok": True, "app": "filehub", "version": 1,
                            "name": CFG.get("name", "FileHub"),
                            "roots": list(current_roots().keys())})

        # ---- 鉴权 ----
        tok = (qs.get("t", [""])[0] or self.headers.get("X-Token", "")
               or (self.headers.get("Authorization", "").replace("Bearer ", "")))
        if not TOKEN or tok != TOKEN:
            return self.err("unauthorized", 401)

        if path == "/api/roots":
            return self.api_roots()
        if path == "/api/list":
            return self.api_list(qs)
        if path == "/f":
            return self.serve_file(qs)
        if path == "/t":
            return self.serve_thumb(qs)
        return self.err("not found", 404)

    # ---------------- 接口 ----------------
    def api_roots(self):
        out = []
        for name, rp in current_roots().items():
            exists = rp.exists()
            out.append({
                "name": name, "path": name, "type": "dir", "size": 0,
                "mtime": int(rp.stat().st_mtime) if exists else 0,
                "exists": exists,
            })
        self.js({"ok": True, "entries": out})

    def api_list(self, qs):
        rel = qs.get("path", [""])[0]
        show_all = qs.get("all", ["0"])[0] in ("1", "true", "yes")
        sort = qs.get("sort", ["name"])[0]
        try:
            _, fp = resolve(rel)
        except KeyError:
            return self.err("未知根目录", 404)
        except ValueError as ex:
            return self.err(str(ex) or "非法路径", 400)

        if fp is None:                       # 根目录列表
            return self.api_roots()
        if not os.path.isdir(fp):
            return self.err("不是目录", 400)

        entries = []
        try:
            with os.scandir(fp) as it:
                for e in it:
                    try:
                        is_dir = e.is_dir()
                        name = e.name
                        if (name.startswith(".") or name.startswith("$")
                                or name.lower() in SKIP_NAMES_LC):
                            continue
                        # 跳过 junction / 符号链接：C:\ 下那些 “Documents and Settings”
                        # “Application Data” 会指回去，整盘共享时不排掉会翻出重复项甚至绕圈
                        if e.is_symlink() or (hasattr(e, "is_junction") and e.is_junction()):
                            continue

                        # .lnk 快捷方式：解析成目标，目标是真文件/目录才当它是一条媒体/目录
                        target = None
                        if not is_dir and name.lower().endswith(".lnk"):
                            target = lnk_target(e.path)
                            if not target or not os.path.exists(target):
                                continue
                            is_dir = os.path.isdir(target)
                            name = name[:-4]          # 去掉 .lnk 后缀显示

                        if is_dir:
                            k = "dir"
                            size = 0
                            mtime = int(os.path.getmtime(target)) if target else int(e.stat().st_mtime)
                        else:
                            src = target or e.path
                            k = kind_of(src, False)
                            if k == "file" and not show_all:
                                continue
                            st = os.stat(src)
                            size = st.st_size
                            mtime = int(st.st_mtime)
                    except OSError:
                        continue
                    entries.append({
                        "name": name,
                        "path": (rel.strip("/") + "/" + e.name) if rel else e.name,
                        "type": k, "size": size, "mtime": mtime,
                        "lnk": bool(target),
                    })
        except PermissionError:
            return self.err("没有权限读取该目录", 403)

        if sort == "date":
            entries.sort(key=lambda x: (x["type"] != "dir", -x["mtime"]))
        else:
            entries.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))

        parent = ""
        if rel.strip("/"):
            parts = rel.strip("/").split("/")
            parent = "/".join(parts[:-1])
        self.js({"ok": True, "path": rel.strip("/"), "parent": parent,
                 "entries": entries, "count": len(entries)})

    # ---------------- 文件 ----------------
    def serve_file(self, qs):
        rel = qs.get("path", [""])[0]
        try:
            _, fp = resolve(rel)
        except KeyError:
            return self.err("未知根目录", 404)
        except ValueError as ex:
            return self.err(str(ex) or "非法路径", 400)
        if fp is None or not os.path.isfile(fp):
            return self.err("文件不存在", 404)

        try:
            size = os.path.getsize(fp)
        except OSError:
            return self.err("读取失败", 500)
        ext = os.path.splitext(fp)[1].lower()
        ctype = CTYPE_OVERRIDE.get(ext) or (mimetypes.guess_type(fp)[0]
                                            or "application/octet-stream")

        start, end, partial = 0, size - 1, False
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
            if m:
                g1, g2 = m.group(1), m.group(2)
                if g1 == "" and g2 != "":
                    n = int(g2)
                    start = max(0, size - n)
                elif g1 != "":
                    start = int(g1)
                    if g2 != "":
                        end = min(int(g2), size - 1)
                if start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                partial = True

        length = max(0, end - start + 1)
        extra = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=300"}
        if partial:
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        self._hdr(206 if partial else 200, ctype, length, extra)
        if self.command == "HEAD":
            return

        try:
            with open(fp, "rb") as f:
                f.seek(start)
                remain = length
                while remain > 0:
                    chunk = f.read(min(262144, remain))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remain -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True
        except OSError:
            self.close_connection = True

    def serve_thumb(self, qs):
        rel = qs.get("path", [""])[0]
        try:
            w = int(qs.get("w", ["400"])[0])
        except ValueError:
            w = 400
        try:
            _, fp = resolve(rel)
        except KeyError:
            return self.err("未知根目录", 404)
        except ValueError as ex:
            return self.err(str(ex) or "非法路径", 400)
        if fp is None or not os.path.isfile(fp):
            return self.err("文件不存在", 404)
        try:
            data, hit = build_thumb(fp, w)
        except Exception as ex:
            return self.err(f"缩略图生成失败: {ex}", 500)
        self._hdr(200, "image/jpeg", len(data),
                  {"Cache-Control": "public, max-age=86400",
                   "X-Thumb-Cache": "hit" if hit else "miss"})
        if self.command != "HEAD":
            self._safe_write(data)


# ----------------------------------------------------------------------------
def local_ips() -> list[str]:
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips


def move_console_to_desktop(index) -> None:
    """
    把本服务的控制台窗口挪到指定虚拟桌面（0 起）。
    窗口刚创建时句柄可能还不可用，所以放后台线程里轮询重试；失败只提示，不影响服务。
    """
    if not isinstance(index, int) or index <= 0:
        return
    prefix = CFG.get("window_title", "FileHub")
    threading.Thread(target=_move_loop, args=(index, prefix), daemon=True).start()


def _find_window_by_title(prefix: str) -> int:
    """EnumWindows 按标题前缀找顶层窗口。
    必要性：控制台被 Windows Terminal 托管时，GetConsoleWindow() 给的句柄 vd 根本不认。
    """
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    hits = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if buf.value.startswith(prefix):
                hits.append(int(hwnd))
                return False
        return True

    user32.EnumWindows(_cb, 0)
    return hits[0] if hits else 0


def _move_loop(index: int, title_prefix: str = "FileHub", attempts: int = 14) -> None:
    import ctypes
    vd = r"C:\Users\yourname\Tools\VirtualDesktop\vd.exe"
    if not os.path.exists(vd):
        vd = shutil.which("vd") or ""
    if not vd:
        print("  [提示] 找不到 vd.exe，跳过窗口迁移")
        return
    moved = False
    for _ in range(attempts):
        time.sleep(0.7)
        try:
            hwnd = _find_window_by_title(title_prefix) or ctypes.windll.kernel32.GetConsoleWindow()
            if not hwnd:
                continue
            cur = subprocess.run([vd, f"/GetDesktopFromWindowHandle:{hwnd}"],
                                 capture_output=True, timeout=8, text=True).stdout or ""
            if f"desktop number {index} " in cur:
                moved = True
                break
            subprocess.run([vd, f"/GetDesktop:{index}", f"/MoveWindowHandle:{hwnd}"],
                           capture_output=True, timeout=8, text=True)
        except Exception:
            continue
    if moved:
        print(f"  窗口已在桌面 {index + 1}（不占当前桌面）")
    else:
        print(f"  [提示] 窗口迁移未确认，可在桌面 {index + 1} 找一下")


def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Windows: 让 Ctrl+C 更干脆
    try:
        ThreadingHTTPServer.allow_reuse_address = True
    except Exception:
        pass
    srv = None
    try:
        srv = ThreadingHTTPServer((CFG.get("bind", "0.0.0.0"), PORT), Handler)
    except OSError as ex:
        if getattr(ex, "errno", None) in (48, 98, 10048) or "in use" in str(ex).lower() \
                or "只允许使用每个套接字地址" in str(ex):
            print(f"\n[提示] 端口 {PORT} 已被占用：FileHub 应该已经在跑了，无需重复启动。")
            print("       手机端直接打开 App 即可。")
            return
        raise
    srv.daemon_threads = True

    print("=" * 62)
    print(f" FileHub 只读媒体服务  |  端口 {PORT}  |  令牌 {TOKEN}")
    print("=" * 62)
    for name, rp in STATIC_ROOTS.items():
        flag = "OK " if rp.exists() else "缺失"
        print(f"  [{flag}] {name:<8} -> {rp}")
    if AUTO_DRIVES:
        print("- " * 31)
        for letter, kind, label in list_drives():
            tag = "可移动" if kind == "removable" else "本地盘"
            print(f"  [OK ] {letter}:\\      {tag}  {label}")
        print("  （磁盘实时枚举：中途插 U 盘不用重启，App 里点刷新即可）")
    print("-" * 62)
    print(" 手机端可填写的地址：")
    print(f"   Tailscale : http://100.64.0.1:{PORT}")
    for ip in local_ips():
        print(f"   局域网     : http://{ip}:{PORT}")
    print(f"   本机       : http://127.0.0.1:{PORT}")
    print("-" * 62)
    print(" 只读服务，无任何写/删接口。Ctrl+C 停止。")
    print("=" * 62)
    move_console_to_desktop(CFG.get("move_to_desktop"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
