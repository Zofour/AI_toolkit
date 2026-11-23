"""Chatbox Bridge - PC relay service.

把 Chatbox 桌面版的模型输出（OpenAI 兼容反向代理捕获）实时通过 WebSocket
推送给安卓 App。方案 A：Chatbox 的 API Host 指向本服务，本服务转发真上游并顺路抓取。
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
PROTOCOL_VERSION = 1
