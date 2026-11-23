"""会话与事件存储：会话归并、seq 分配、内存环形缓冲 + JSONL 持久化。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import time
from collections import deque


def session_key(model: str, system_prompt: str, first_user: str) -> str:
    """稳定会话指纹：同一会话的多轮请求 → 同一 key（取 system + 首条用户 + 模型）。"""
    raw = f"{model}\x00{system_prompt[:4000]}\x00{first_user[:4000]}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def now_ms() -> int:
    return int(time.time() * 1000)


class Session:
    __slots__ = ("key", "title", "created", "updated", "seq", "events", "_fh", "_path", "chatbox_id")

    def __init__(self, key: str, title: str, path: pathlib.Path):
        self.key = key
        self.title = title
        self.created = now_ms()
        self.updated = self.created
        self.seq = 0
        self.events: deque = deque()
        self._fh = None
        self._path = path
        self.chatbox_id = ""

    def append(self, ev: dict, limit: int):
        self.seq = ev["seq"]
        self.updated = ev["ts"]
        self.events.append(ev)
        while len(self.events) > limit:
            self.events.popleft()
        # 持久化（追加一行 JSON）
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def load(self, limit: int):
        self.events = deque(maxlen=limit)
        if not self._path.exists():
            return
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                self.events.append(ev)
                self.seq = max(self.seq, int(ev.get("seq", 0)))
                self.title = self.title or ev.get("data", {}).get("title") or self.title
                self.updated = ev.get("ts", self.updated)
        except Exception:
            pass

    def to_meta(self) -> dict:
        last = ""
        for ev in reversed(self.events):
            d = ev.get("data", {})
            if ev.get("type") in ("msg.done", "msg.delta", "msg.user"):
                last = (d.get("text") or last)[:120]
                if last:
                    break
        return {
            "id": self.key,
            "title": self.title or "(无标题)",
            "created": self.created,
            "updated": self.updated,
            "seq": self.seq,
            "last": last,
            "chatboxId": self.chatbox_id or None,
        }


class Store:
    def __init__(self, data_dir: str, buffer_limit: int = 3000):
        self.dir = pathlib.Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.limit = buffer_limit
        self.lock = asyncio.Lock()
        self.sessions: dict[str, Session] = {}
        self._load_index()

    def _path_for(self, key: str) -> pathlib.Path:
        return self.dir / f"{key}.jsonl"

    def _load_index(self):
        for p in self.dir.glob("*.jsonl"):
            key = p.stem
            s = Session(key, "", p)
            s.load(self.limit)
            if not s.created:
                continue
            self.sessions[key] = s

    def get_or_create(self, key: str, title: str) -> Session:
        s = self.sessions.get(key)
        if s is None:
            s = Session(key, title, self._path_for(key))
            self.sessions[key] = s
        elif title and not s.title:
            s.title = title
        return s

    def list_meta(self) -> list[dict]:
        metas = [s.to_meta() for s in self.sessions.values()]
        metas.sort(key=lambda m: m["updated"], reverse=True)
        return metas

    def get(self, key: str) -> Session | None:
        return self.sessions.get(key)

    def delete(self, key: str) -> bool:
        """删除某会话（内存 + 文件）。"""
        s = self.sessions.pop(key, None)
        if s is None:
            return False
        try:
            s._path.unlink(missing_ok=True)
        except Exception:
            pass
        return True

    def reset(self):
        """清空所有会话（内存 + 文件）。"""
        for s in self.sessions.values():
            try:
                s._path.unlink(missing_ok=True)
            except Exception:
                pass
        self.sessions.clear()
