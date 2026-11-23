"""WebSocket 连接中心：管理连接、订阅、广播（含回控预留接口）。"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.websockets import WebSocket

from . import PROTOCOL_VERSION

# 服务端能力声明（客户端据此开关 UI；加新功能只增条目）
FEATURES = [
    "sessions",          # 会话列表 / 历史
    "resume",            # 断线按 seq 续传
    "markdown",          # 正文为 Markdown
    "notify",            # 支持 ntfy 兜底
    # 回控（预留，尚未实现；客户端可据此隐藏/置灰控件）
    "control.reserved",  # 控制命名空间已定义，服务端返回 not_implemented
]

# 预留的控制类型（现在只登记，不实现）
CONTROL_TYPES = [
    "control.stop",           # 停止当前生成
    "control.send",           # 从手机发消息
    "control.session.switch", # 切换当前会话
    "control.model.switch",   # 切换模型
]


class Client:
    __slots__ = ("ws", "subs", "all", "id")

    def __init__(self, ws: WebSocket, cid: str):
        self.ws = ws
        self.id = cid
        self.subs: set[str] = set()  # 定向订阅的 sessionId 集合
        self.all = False             # 是否订阅“全部会话（含未来的）”

    def wants(self, session_id: str) -> bool:
        return self.all or (session_id in self.subs)


class Hub:
    def __init__(self):
        self.clients: set[Client] = set()
        self.injectors: set[Client] = set()
        self._lock = asyncio.Lock()
        self._cid = 0

    async def register(self, ws: WebSocket) -> Client:
        async with self._lock:
            self._cid += 1
            c = Client(ws, f"c{self._cid}")
            self.clients.add(c)
            return c

    async def unregister(self, c: Client):
        async with self._lock:
            self.clients.discard(c)
            self.injectors.discard(c)

    @property
    def online_count(self) -> int:
        return len(self.clients)

    @property
    def injector_count(self) -> int:
        return len(self.injectors)

    async def broadcast(self, ev: dict):
        """推给所有客户端（不按会话过滤）。"""
        text = json.dumps(ev, ensure_ascii=False)
        dead = []
        for c in list(self.clients):
            try:
                await c.ws.send_text(text)
            except Exception:
                dead.append(c)
        for c in dead:
            await self.unregister(c)

    async def dispatch(self, ev: dict) -> int:
        """把注入指令发给所有注入器，返回送达数量。"""
        text = json.dumps(ev, ensure_ascii=False)
        dead = []
        n = 0
        for c in list(self.injectors):
            try:
                await c.ws.send_text(text)
                n += 1
            except Exception:
                dead.append(c)
        for c in dead:
            self.injectors.discard(c)
        return n

    async def publish(self, ev: dict):
        """把事件推给所有订阅了该会话的客户端（回控事件也走这里）。"""
        session_id = ev.get("sessionId", "")
        text = json.dumps(ev, ensure_ascii=False)
        dead = []
        for c in list(self.clients):
            if not c.wants(session_id):
                continue
            try:
                await c.ws.send_text(text)
            except Exception:
                dead.append(c)
        for c in dead:
            await self.unregister(c)

    async def send(self, c: Client, ev: dict):
        try:
            await c.ws.send_text(json.dumps(ev, ensure_ascii=False))
        except Exception:
            await self.unregister(c)

    def hello(self, server_id: str, store_meta: list[dict], injectors: int = 0) -> dict:
        return {
            "v": PROTOCOL_VERSION,
            "type": "hello",
            "ts": 0,
            "data": {
                "serverId": server_id,
                "protocolVersion": PROTOCOL_VERSION,
                "features": FEATURES,
                "controlTypes": CONTROL_TYPES,
                "canControl": injectors > 0,
                "sessions": store_meta,
            },
        }
