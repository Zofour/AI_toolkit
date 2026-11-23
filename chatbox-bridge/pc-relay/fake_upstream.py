"""完整工作流假上游（长文本版，SSE）：
- 第一条请求（没有 role=tool）：产出「思考 + 工具调用」
- 第二条请求（带 role=tool 结果）：产出「思考 + 最终正文」
监听 127.0.0.1:8791。
"""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REASON1 = [
    "用户想查看电脑和手机的连接状态。我需要先运行 tailscale status 命令，",
    "获取本机与对端设备的在线情况，再根据返回结果判断是否一切正常，",
    "最后给出一句清晰的中文结论。",
]
ARGS1 = '{"cmd": "tailscale status --json", "timeout": 15, "cwd": "C:/Users/yourname"}'
REASON2 = [
    "命令已经返回了结果：本机和手机都在线，属于同一个 tailnet。",
    "我确认一下 IP 与平台信息，然后总结成一句中文给用户。",
]
CONTENT2 = [
    "电脑端 **100.64.0.1** 在线，手机端也在线，二者处于同一 tailnet，连接正常。",
    "\n\n补充：这是经由 Tailscale 的 WireGuard 加密隧道建立的直连，",
    "出门在外（手机走 4G/5G）也能保持实时。\n\n",
    "```\n100.64.0.1   yourpc       windows\n100.64.0.1   aln-al00  android\n```",
]


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _sse(self, obj):
        self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))
        self.wfile.flush()

    def do_POST(self):
        n = int(self.headers.get("content-length", 0))
        body = self.rfile.read(n)
        try:
            req = json.loads(body)
        except Exception:
            req = {}
        has_tool = any(m.get("role") == "tool" for m in (req.get("messages") or []))
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()

        if not has_tool:
            for c in REASON1:
                self._sse({"choices": [{"delta": {"reasoning_content": c}}]})
                time.sleep(0.25)
            self._sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1",
                  "type": "function", "function": {"name": "run_command", "arguments": ARGS1}}]}}]})
            self._sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
        else:
            for c in REASON2:
                self._sse({"choices": [{"delta": {"reasoning_content": c}}]})
                time.sleep(0.25)
            for c in CONTENT2:
                self._sse({"choices": [{"delta": {"content": c}}]})
                time.sleep(0.2)
            self._sse({"choices": [{"delta": {}, "finish_reason": "stop"}]})

        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


if __name__ == "__main__":
    print("workflow fake upstream on 127.0.0.1:8791", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8791), H).serve_forever()
