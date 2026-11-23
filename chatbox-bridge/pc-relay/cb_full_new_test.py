"""真链路测试：control.new（新建会话）→ control.send → 截图验证。"""
import json
import os
import sys
import time

import websocket

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cdp  # noqa: E402
from relay.config import load_config  # noqa: E402

TEXT = sys.argv[1] if len(sys.argv) > 1 else "手机新建会话测试"


def wait(ws, want, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            m = json.loads(ws.recv())
        except Exception:
            break
        if m.get("type") == want:
            return m
    return None


def main():
    cfg = load_config()
    ws = websocket.create_connection(f"ws://127.0.0.1:{cfg['port']}/ws?token={cfg['token']}",
                                     suppress_origin=True, timeout=15)
    try:
        ws.send(json.dumps({"type": "subscribe", "data": {}}))
        time.sleep(0.3)

        print("→ control.new")
        ws.send(json.dumps({"type": "control.new", "data": {"reqId": "n1"}}))
        r = wait(ws, "control.result")
        print("   ", r.get("data") if r else None)

        time.sleep(1.0)
        print("→ control.send:", TEXT)
        ws.send(json.dumps({"type": "control.send", "data": {"text": TEXT, "reqId": "s1"}}))
        r2 = wait(ws, "control.result")
        print("   ", r2.get("data") if r2 else None)
    finally:
        ws.close()

    time.sleep(3)
    c = cdp.CDP(9333)
    p = os.path.join(HERE, "_host_new.png")
    c.screenshot(p)
    c.close()
    print("[shot]", p)


if __name__ == "__main__":
    main()
