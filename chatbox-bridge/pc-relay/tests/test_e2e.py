"""端到端自测：假上游(SSE，含思考/工具调用) + 中继(uvicorn 线程) + 真 WebSocket 客户端。

运行： cd pc-relay && python tests/test_e2e.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from websockets.sync.client import connect  # noqa: E402

from relay.app import create_app  # noqa: E402
from relay.config import DEFAULTS, Config  # noqa: E402

TOKEN = "test-token-123"
REASON = ["先分析", "再作答"]
CHUNKS = ["你好", "，", "世界", "！"]
EXPECT = "".join(CHUNKS)
# 1x1 透明 PNG
PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
           "DwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class FakeUpstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def _sse(self, obj):
        self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def do_POST(self):
        n = int(self.headers.get("content-length", 0))
        self.rfile.read(n)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for c in REASON:
            self._sse({"choices": [{"delta": {"reasoning_content": c}}]})
            time.sleep(0.03)
        for c in CHUNKS:
            self._sse({"choices": [{"delta": {"content": c}}]})
            time.sleep(0.05)
        self._sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1",
              "type": "function", "function": {"name": "run_cmd", "arguments": "{\"cmd\":"}}]}}]})
        self._sse({"choices": [{"delta": {"tool_calls": [{"index": 0,
              "function": {"arguments": "\"ls\"}"}}]}}]})
        self._sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def do_GET(self):
        body = json.dumps({"data": [{"id": "fake-model"}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def wait_health(port, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def collect(ws, until="msg.done", timeout=15):
    types, deltas = [], []
    end = time.time() + timeout
    while time.time() < end:
        try:
            m = json.loads(ws.recv(timeout=5))
        except TimeoutError:
            break
        types.append(m["type"])
        if m["type"] == "msg.delta":
            deltas.append(m["data"]["text"])
        if m["type"] == until:
            break
    return types, deltas


def main():
    ok = True
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
    up_port = upstream.server_address[1]
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    print(f"[fake upstream] http://127.0.0.1:{up_port}")

    relay_port = 8799
    data = dict(DEFAULTS)
    data.update({
        "bind_host": "127.0.0.1", "port": relay_port, "token": TOKEN,
        "upstream_base": f"http://127.0.0.1:{up_port}/v1", "data_dir": tempfile.mkdtemp(prefix="cbrelay-"),
    })
    app = create_app(Config(data, None))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=relay_port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    assert wait_health(relay_port), "relay 未起来"
    print(f"[relay] http://127.0.0.1:{relay_port}")

    url = f"http://127.0.0.1:{relay_port}/v1/chat/completions"
    sys_msg = {"role": "system", "content": "你是助手"}
    user_msg = {"role": "user", "content": [
        {"type": "text", "text": "打个招呼"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + PNG_B64}},
    ]}
    req = {"model": "fake-model", "stream": True, "messages": [sys_msg, user_msg]}

    try:
        with connect(f"ws://127.0.0.1:{relay_port}/ws?token={TOKEN}") as ws:
            hello = json.loads(ws.recv(timeout=5))
            ok &= check(hello["type"] == "hello", "收到 hello")
            ws.send(json.dumps({"type": "subscribe", "data": {}}))

            holder = {}

            def do_post():
                with httpx.stream("POST", url, json=req, timeout=30) as r:
                    holder["status"] = r.status_code
                    holder["body"] = "".join(r.iter_text())

            th = threading.Thread(target=do_post)
            th.start()
            events, deltas = collect(ws)
            th.join(timeout=5)

            print("[events]", events)
            print("[deltas]", "".join(deltas))
            ok &= check(holder.get("status") == 200, f"代理返回 200 (实={holder.get('status')})")
            ok &= check("data:" in holder.get("body", ""), "透传给 Chatbox 的 SSE 完整")
            ok &= check("msg.user" in events, "推送了用户消息")
            ok &= check("msg.delta" in events, "推送了正文增量")
            ok &= check("msg.reason" in events, "推送了思考过程")
            ok &= check("msg.tool" in events, "推送了工具调用")
            ok &= check("".join(deltas) == EXPECT, f"增量拼接正确 == {EXPECT!r}")

            ws.send(json.dumps({"type": "control.stop", "data": {"reqId": "r1"}}))
            cr = json.loads(ws.recv(timeout=5))
            ok &= check(cr["type"] == "control.result" and cr["data"]["error"] == "not_implemented",
                        "回控返回 not_implemented（预留生效）")

        # REST
        r = httpx.get(f"http://127.0.0.1:{relay_port}/sessions", params={"token": TOKEN}, timeout=5)
        sess = r.json()["sessions"]
        ok &= check(r.status_code == 200 and len(sess) == 1, "REST 返回 1 个会话")
        sid = sess[0]["id"]

        ok &= check(httpx.get(f"http://127.0.0.1:{relay_port}/sessions", timeout=5).status_code == 401,
                    "无 token 401")

        # 图片：应推了 msg.image，且 blob 可通过 HTTP 取到（带 token）
        r2 = httpx.get(f"http://127.0.0.1:{relay_port}/sessions/{sid}/messages",
                       params={"token": TOKEN, "since": 0}, timeout=5)
        imgs = [e for e in r2.json()["events"] if e.get("type") == "msg.image"]
        ok &= check(len(imgs) >= 1, f"推送了图片事件 (实={len(imgs)})")
        if imgs:
            bid = imgs[0]["data"]["blobId"]
            rb = httpx.get(f"http://127.0.0.1:{relay_port}/blobs/{bid}",
                           params={"token": TOKEN}, timeout=5)
            ok &= check(rb.status_code == 200 and rb.content[:4] == b"\x89PNG", "blob 可取且是 PNG")
            ok &= check(httpx.get(f"http://127.0.0.1:{relay_port}/blobs/{bid}", timeout=5).status_code == 401,
                        "blob 无 token 401")

        # 工具结果：模拟 Chatbox 下一轮请求带 role=tool（应推送 msg.tool_result 且不重复 msg.user）
        req2 = {"model": "fake-model", "stream": True, "messages": [
            sys_msg, user_msg,
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "run_cmd", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "name": "run_cmd", "content": "file1\nfile2"},
        ]}
        with connect(f"ws://127.0.0.1:{relay_port}/ws?token={TOKEN}") as ws3:
            ws3.recv(timeout=5)
            ws3.send(json.dumps({"type": "subscribe",
                                 "data": {"sessionId": sid, "sinceSeq": 10 ** 9}}))
            time.sleep(0.3)

            def do_post2():
                with httpx.stream("POST", url, json=req2, timeout=30) as r:
                    for _ in r.iter_bytes():
                        pass

            th2 = threading.Thread(target=do_post2)
            th2.start()
            ev3, _ = collect(ws3)
            th2.join(timeout=5)
            print("[events2]", ev3)
            ok &= check("msg.tool_result" in ev3, "推送了工具结果(msg.tool_result)")
            ok &= check("msg.user" not in ev3, "工具轮次不重复推送用户消息")

        # 续传
        with connect(f"ws://127.0.0.1:{relay_port}/ws?token={TOKEN}") as ws2:
            ws2.recv(timeout=5)
            ws2.send(json.dumps({"type": "subscribe", "data": {"sessionId": sid, "sinceSeq": 0}}))
            n = 0
            end = time.time() + 6
            while time.time() < end:
                try:
                    m = json.loads(ws2.recv(timeout=3))
                except TimeoutError:
                    break
                if m["type"] == "subscribed":
                    break
                n += 1
            ok &= check(n >= 4, f"续传回放 >= 4 (实={n})")

        # 删除会话
        rd = httpx.delete(f"http://127.0.0.1:{relay_port}/sessions/{sid}",
                          params={"token": TOKEN}, timeout=5)
        ok &= check(rd.status_code == 200 and rd.json().get("ok"), "删除会话成功")
        r4 = httpx.get(f"http://127.0.0.1:{relay_port}/sessions", params={"token": TOKEN}, timeout=5)
        ok &= check(len(r4.json()["sessions"]) == 0, "删除后会话列表为空")

        try:
            bad = connect(f"ws://127.0.0.1:{relay_port}/ws?token=WRONG")
            bad.recv(timeout=3)
            ok &= check(False, "错误 token 应被拒")
        except Exception:
            ok &= check(True, "错误 token 被拒")

    finally:
        server.should_exit = True
        upstream.shutdown()

    print("\n" + ("全部通过 ✅" if ok else "存在失败 ❌"))
    sys.exit(0 if ok else 1)


def check(cond, desc):
    print(f"  {'PASS' if cond else 'FAIL'} - {desc}")
    return bool(cond)


if __name__ == "__main__":
    main()
