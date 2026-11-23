"""兜底通知：App 不在线时用 ntfy 推送“回复完成”。"""
from __future__ import annotations

import httpx


class Notifier:
    def __init__(self, url: str, topic: str):
        self.url = (url or "").rstrip("/")
        self.topic = topic or ""

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.topic)

    async def notify_done(self, title: str, text: str, session_id: str, message_id: str):
        if not self.enabled:
            return
        endpoint = f"{self.url}/{self.topic}"
        headers = {
            # 点击通知后由 App 深链接管；这里只带必要上下文
            "Title": _ascii(title or "Chatbox 回复完成"),
            "Tags": "speech_balloon",
            "X-Session": session_id,
            "X-Message": message_id,
        }
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                await c.post(endpoint, content=(text or "")[:300].encode("utf-8"), headers=headers)
        except Exception as e:
            print(f"[ntfy] 推送失败：{e}")


def _ascii(s: str) -> str:
    """ntfy 头只允许 latin-1，中文标题做一次安全降级。"""
    try:
        s.encode("latin-1")
        return s
    except UnicodeEncodeError:
        return "Chatbox reply ready"
