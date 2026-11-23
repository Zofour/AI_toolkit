"""图片 blob 存储：落盘 + 按内容去重 + 简单 LRU 清理。"""
from __future__ import annotations

import hashlib
import pathlib

EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/bmp": "bmp",
}


def sniff_mime(data: bytes) -> str | None:
    """按魔数判断图片类型（比信扩展名可靠）。"""
    if len(data) < 12:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return None


class BlobStore:
    def __init__(self, root: str, max_files: int = 800):
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max = max_files

    def save(self, data: bytes, mime: str) -> str:
        ext = EXT.get(mime, "bin")
        name = hashlib.sha1(data).hexdigest()[:20] + "." + ext
        p = self.root / name
        if not p.exists():
            p.write_bytes(data)
            self._gc()
        return name

    def path(self, name: str) -> pathlib.Path:
        return self.root / name

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    def _gc(self):
        try:
            files = sorted(self.root.glob("*"), key=lambda f: f.stat().st_mtime)
            while len(files) > self.max:
                files.pop(0).unlink(missing_ok=True)
        except Exception:
            pass
