"""模拟手机：连中继 -> 发 control.send -> 打印返回；并给测试实例截图。"""
import json
import os
import sys
import time

import websocket

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from relay.config import load_config  # noqa: E402
import cdp  # noqa: E402

TEXT = sys.argv[1] if len(sys.argv) > 1 else "手机注入验证XYZ"
SID = sys.argv[2] if len(sys.argv) > 2 else None


def main():
    cfg = load_config()
    url = f"ws://127.0.0.1:{cfg['port']}/ws?token={cfg['token']}"
    ws = websocket.create_connection(url, suppress_origin=True, timeout=15)
    ws.send(json.dumps({"type": "subscribe", "data": {}}))
    time.sleep(0.3)
    print("[phone] send control.send:", TEXT)
    ws.send(json.dumps({"type": "control.send", "data": {"text": TEXT, "reqId": "t1", "sessionId": SID}}))
    end = time.time() + 15
    while time.time() < end:
        try:
            m = json.loads(ws.recv())
        except Exception:
            break
        print("  <-", m.get("type"), json.dumps(m.get("data"), ensure_ascii=False))
        if m.get("type") == "control.result" and m.get("data", {}).get("mode") == "inject":
            break
    time.sleep(2)
    # 给测试实例(Chatbox)截图
    out = os.path.join(HERE, "_cb_shot.png")
    try:
        c = cdp.CDP(9333)
        c.screenshot(out)
        c.close()
        print("[shot]", out)
    except Exception as e:
        print("[shot] failed:", e)


if __name__ == "__main__":
    main()
