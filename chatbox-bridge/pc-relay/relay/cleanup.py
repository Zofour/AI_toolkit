"""临时文件清理：图片 blob 缓存 + 日志文件（**不删**用户会话历史，只统计）。

策略：
- blob：超年龄（默认 7 天）→ 删；再超数量（800）→ 删最旧；再超总大小（300MB）→ 删最旧。
- 日志：`*.log` / `*.err` 超年龄（3 天）或超大（10MB）→ 删。
- 会话 JSONL：只统计不删。
"""
from __future__ import annotations

import pathlib
import time


def _size(p: pathlib.Path) -> int:
    try:
        return p.stat().st_size
    except Exception:
        return 0


def sweep_blobs(root: pathlib.Path, max_files: int, max_mb: float, max_age_days: float) -> dict:
    removed = 0
    freed = 0
    if not root.exists():
        return {"blob_files": 0, "blob_mb": 0.0, "removed_files": 0, "freed_bytes": 0}
    now = time.time()
    files: list[tuple[float, int, pathlib.Path]] = []
    for p in root.glob("*"):
        if not p.is_file():
            continue
        try:
            st = p.stat()
        except Exception:
            continue
        if max_age_days > 0 and (now - st.st_mtime) > max_age_days * 86400:
            try:
                p.unlink()
                removed += 1
                freed += st.st_size
                continue
            except Exception:
                pass
        files.append((st.st_mtime, st.st_size, p))

    files.sort(key=lambda x: x[0])
    while len(files) > max_files:
        _, sz, p = files.pop(0)
        try:
            p.unlink()
            removed += 1
            freed += sz
        except Exception:
            pass

    total = sum(sz for _, sz, _ in files)
    limit = int(max_mb * 1024 * 1024)
    while files and total > limit:
        _, sz, p = files.pop(0)
        try:
            p.unlink()
            removed += 1
            freed += sz
            total -= sz
        except Exception:
            break

    return {"blob_files": len(files), "blob_mb": round(total / 1048576, 2),
            "removed_files": removed, "freed_bytes": freed}


def sweep_logs(root: pathlib.Path, max_age_days: float, max_mb: float) -> dict:
    removed = 0
    freed = 0
    now = time.time()
    if not root.exists():
        return {"removed_files": 0, "freed_bytes": 0}
    for pat in ("*.log", "*.err"):
        for p in root.glob(pat):
            try:
                st = p.stat()
            except Exception:
                continue
            old = max_age_days > 0 and (now - st.st_mtime) > max_age_days * 86400
            big = st.st_size > max_mb * 1024 * 1024
            if old or big:
                try:
                    p.unlink()
                    removed += 1
                    freed += st.st_size
                except Exception:
                    pass
    return {"removed_files": removed, "freed_bytes": freed}


def stat_sessions(session_dir: pathlib.Path) -> dict:
    total = 0
    n = 0
    if session_dir.exists():
        for p in session_dir.glob("*.jsonl"):
            total += _size(p)
            n += 1
    return {"session_files": n, "session_mb": round(total / 1048576, 2)}


def expired_keys(sessions: dict, max_age_days: float, now_ms: int) -> list[str]:
    """返回最后更新时间早于 max_age_days 的会话 key（0/负数 = 不清理）。"""
    if not max_age_days or max_age_days <= 0:
        return []
    cutoff = now_ms - int(max_age_days * 86400 * 1000)
    out = []
    for k, s in list(sessions.items()):
        upd = getattr(s, "updated", 0) or 0
        if upd and upd < cutoff:
            out.append(k)
    return out


def run_cleanup(data_dir: pathlib.Path, blob_dir: pathlib.Path, log_dir: pathlib.Path, cfg) -> dict:
    b = sweep_blobs(
        blob_dir,
        int(cfg.get("blob_max_files", 800)),
        float(cfg.get("blob_max_mb", 300)),
        float(cfg.get("blob_max_age_days", 7)),
    )
    lg = sweep_logs(log_dir, float(cfg.get("log_max_age_days", 3)), float(cfg.get("log_max_mb", 10)))
    s = stat_sessions(data_dir)
    removed = b["removed_files"] + lg["removed_files"]
    freed = b["freed_bytes"] + lg["freed_bytes"]
    return {**b, **lg, **s,
            "removed_files": removed,
            "freed_mb": round(freed / 1048576, 2)}
