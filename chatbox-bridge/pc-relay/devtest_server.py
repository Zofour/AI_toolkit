"""真机联调用：本地假上游(SSE) + 中继服务，常驻运行。

用法： python devtest_server.py
- 中继监听 config.json 里的 bind_host:port（默认 0.0.0.0:8787）
- 假上游在 127.0.0.1:8791；向中继 POST /v1/chat/completions 时带
  header: X-Upstream-Base: http://127.0.0.1:8791/v1  即可走它。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402
from relay.app import create_app  # noqa: E402
from relay.config import load_config  # noqa: E402

CHUNKS = [
    "你好", "，这是", "来自电脑的", "**实时回复**", "（真机联调）",
    "。\n\n```python\nprint('hello from pc')\n```\n\n",
    "结尾一句，用来验证逐字流式。",
]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _sse(self, obj):
        self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))
        self.wfile.flush()

    def do_POST(self):
        n = int(self.headers.get("content-length", 0))
        self.rfile.read(n)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for c in CHUNKS:
            self._sse({"choices": [{"delta": {"content": c}}]})
            time.sleep(0.12)
        self._sse({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def main():
    up = ThreadingHTTPServer(("127.0.0.1", 8791), Handler)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    print("[fake upstream] http://127.0.0.1:8791")

    cfg = load_config()
    app = create_app(cfg)
    print(f"[relay] http://{cfg['bind_host']}:{cfg['port']}  token={cfg['token']}")
    uvicorn.run(app, host=cfg["bind_host"], port=cfg["port"], log_level="info")


if __name__ == "__main__":
    main()
