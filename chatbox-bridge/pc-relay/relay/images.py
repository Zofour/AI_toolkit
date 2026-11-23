"""从消息内容里抽取图片：data URL / 本地文件 / http / Markdown 图片语法。"""
from __future__ import annotations

import base64
import io
import json
import re
import urllib.parse
import urllib.request

from .blobs import sniff_mime

MD_IMG = re.compile(r"!\[[^\]]*\]\(\s*([^)\s]+)\s*\)")
MAX_FETCH = 12 * 1024 * 1024      # 单图最大 12MB
SHRINK_BYTES = 2_500_000          # 超过 2.5MB 就压缩
SHRINK_SIDE = 2000                # 长边压到 2000px


def _from_data_url(url: str) -> tuple[bytes, str] | None:
    try:
        head, b64 = url.split(",", 1)
        mime = head[5:].split(";")[0] or "image/png"
        data = base64.b64decode(b64, validate=False)
        if len(data) > MAX_FETCH:
            return None
        return data, mime
    except Exception:
        return None


def _from_local_path(url: str) -> tuple[bytes, str] | None:
    try:
        if url.startswith("file://"):
            p = urllib.parse.unquote(url[7:])
            if re.match(r"^/[A-Za-z]:", p):   # file:///C:/x  -> C:/x
                p = p[1:]
        else:
            p = url
        if not re.match(r"^[A-Za-z]:[\\/]", p) and not p.startswith("\\\\"):
            return None
        data = open(p, "rb").read(MAX_FETCH + 1)
        if len(data) > MAX_FETCH:
            return None
        return data, None
    except Exception:
        return None


def _from_http(url: str) -> tuple[bytes, str] | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "chatbox-bridge"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = r.read(MAX_FETCH + 1)
        if len(data) > MAX_FETCH:
            return None
        return data, (r.headers.get("content-type") or "").split(";")[0] or None
    except Exception:
        return None


def _resolve(url: str) -> tuple[bytes, str] | None:
    url = url.strip().strip("<>\"'")
    if not url:
        return None
    if url.startswith("data:"):
        got = _from_data_url(url)
    elif url.startswith("http://") or url.startswith("https://"):
        got = _from_http(url)
    else:
        got = _from_local_path(url)
    if not got:
        return None
    data, mime = got
    real = sniff_mime(data)
    if not real:                      # 不是图片就丢弃
        return None
    return data, real


def _shrink(data: bytes, mime: str) -> tuple[bytes, str]:
    if len(data) <= SHRINK_BYTES:
        return data, mime
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.load()
        if max(im.size) > SHRINK_SIDE:
            im.thumbnail((SHRINK_SIDE, SHRINK_SIDE))
        buf = io.BytesIO()
        if im.mode in ("RGBA", "LA", "P") and mime in ("image/png", "image/webp"):
            im.save(buf, "PNG", optimize=True)
            return buf.getvalue(), "image/png"
        im.convert("RGB").save(buf, "JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return data, mime


def _size_of(data: bytes) -> tuple[int, int] | None:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return None


def collect(content) -> list[tuple[bytes, str]]:
    """从一段 message content 里收集图片（data URL / 本地文件 / http / Markdown）。"""
    urls: list[str] = []
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") in ("image_url", "input_image", "image"):
                iu = part.get("image_url") or part.get("url")
                if isinstance(iu, dict):
                    iu = iu.get("url")
                if isinstance(iu, str):
                    urls.append(iu)
            elif isinstance(part.get("text"), str):
                urls.extend(MD_IMG.findall(part["text"]))
    elif isinstance(content, str):
        urls.extend(MD_IMG.findall(content))

    out: list[tuple[bytes, str]] = []
    for u in urls:
        got = _resolve(u)
        if got:
            out.append(_shrink(*got))
    return out


def describe(data: bytes) -> dict:
    size = _size_of(data)
    return {"w": size[0], "h": size[1]} if size else {}
