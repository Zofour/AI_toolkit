"""极简 CDP 客户端：连到 Chatbox 的调试端口，执行 JS 表达式。
用法: python cdp.py "<js expression>" [port]
"""
import json
import sys
import urllib.request

import websocket  # websocket-client


def page_ws(port=9333):
    data = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5))
    pages = [x for x in data if x.get("type") == "page"]
    if not pages:
        raise RuntimeError("no page target")
    return pages[0]["webSocketDebuggerUrl"]


class CDP:
    def __init__(self, port=9333, timeout=20):
        self.ws = websocket.create_connection(page_ws(port), timeout=timeout, suppress_origin=True)
        self.i = 0

    def ev(self, expr, await_promise=False, timeout=20):
        self.i += 1
        self.ws.settimeout(timeout)
        self.ws.send(json.dumps({
            "id": self.i, "method": "Runtime.evaluate",
            "params": {"expression": expr, "returnByValue": True,
                       "awaitPromise": await_promise, "userGesture": True},
        }))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.i:
                return msg

    def insert_text(self, text, timeout=20):
        """像真人打字一样插入文本（React 能感知）。"""
        self.i += 1
        self.ws.settimeout(timeout)
        self.ws.send(json.dumps({"id": self.i, "method": "Input.insertText",
                                 "params": {"text": text}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.i:
                return m

    def screenshot(self, path, timeout=20):
        import base64
        self.i += 1
        self.ws.settimeout(timeout)
        self.ws.send(json.dumps({"id": self.i, "method": "Page.captureScreenshot",
                                 "params": {"format": "png"}}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.i:
                with open(path, "wb") as f:
                    f.write(base64.b64decode(m["result"]["data"]))
                return path

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    expr = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9333
    c = CDP(port)
    try:
        r = c.ev(expr)
        res = r.get("result", {}).get("result", {})
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if r.get("result", {}).get("exceptionDetails"):
            print("EXC:", json.dumps(r["result"]["exceptionDetails"], ensure_ascii=False)[:500])
    finally:
        c.close()
