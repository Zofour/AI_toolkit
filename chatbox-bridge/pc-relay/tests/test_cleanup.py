"""清理与「会话 30 天过期」的测试。

运行： cd pc-relay && python tests/test_cleanup.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from relay.app import create_app  # noqa: E402
from relay.cleanup import expired_keys, run_cleanup, sweep_blobs, sweep_logs  # noqa: E402
from relay.config import DEFAULTS, Config  # noqa: E402

TOKEN = "cleanup-token"
ok = True


def check(cond, desc):
    global ok
    print(f"  {'PASS' if cond else 'FAIL'} - {desc}")
    ok = ok and bool(cond)


class FakeSession:
    def __init__(self, updated):
        self.updated = updated


def unit_tests():
    now = int(time.time() * 1000)
    day = 86400 * 1000
    sess = {
        "old": FakeSession(now - 40 * day),
        "edge": FakeSession(now - 31 * day),
        "new": FakeSession(now - 1 * day),
    }
    keys = expired_keys(sess, 30, now)
    check(set(keys) == {"old", "edge"}, f"30 天过期判定 (实={keys})")
    check(expired_keys(sess, 0, now) == [], "0 天 = 永不清理")

    d = tempfile.mkdtemp(prefix="blobs-")
    for name, age in (("a.png", 10), ("b.png", 8), ("c.png", 0)):
        p = os.path.join(d, name)
        open(p, "wb").write(b"x" * 1024)
        t = time.time() - age * 86400
        os.utime(p, (t, t))
    st = sweep_blobs(__import__("pathlib").Path(d), 800, 300, 7)
    check(st["removed_files"] == 2 and st["blob_files"] == 1, f"blob 按年龄清理 (实={st})")

    lg = tempfile.mkdtemp(prefix="logs-")
    p = os.path.join(lg, "old.log")
    open(p, "w").write("x")
    t = time.time() - 5 * 86400
    os.utime(p, (t, t))
    open(os.path.join(lg, "new.log"), "w").write("x")
    sl = sweep_logs(__import__("pathlib").Path(lg), 3, 10)
    check(sl["removed_files"] == 1 and os.path.exists(os.path.join(lg, "new.log")),
          f"日志按年龄清理 (实={sl})")


def integration_test():
    data = tempfile.mkdtemp(prefix="sess-")
    now = int(time.time() * 1000)
    old_ts = now - 40 * 86400 * 1000

    def write_session(key, ts, text):
        rec = {"v": 1, "type": "msg.user", "ts": ts, "sessionId": key,
               "messageId": None, "seq": 1, "data": {"role": "user", "text": text}}
        with open(os.path.join(data, key + ".jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    write_session("oldsess", old_ts, "40天前的会话")
    write_session("newsess", now - 3600 * 1000, "1小时前的会话")

    cfg = Config({**DEFAULTS, "data_dir": data, "token": TOKEN, "port": 8802,
                  "bind_host": "127.0.0.1", "session_max_age_days": 30}, None)
    app = create_app(cfg)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8802, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    end = time.time() + 15
    while time.time() < end:
        try:
            if httpx.get("http://127.0.0.1:8802/health", timeout=2).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.2)
    try:
        r = httpx.post(f"http://127.0.0.1:8802/cleanup", params={"token": TOKEN}, timeout=10)
        st = r.json()
        print("[cleanup]", st)
        check(not os.path.exists(os.path.join(data, "oldsess.jsonl")), "40 天前会话文件已删")
        check(os.path.exists(os.path.join(data, "newsess.jsonl")), "1 小时前会话保留")
        ss = httpx.get(f"http://127.0.0.1:8802/sessions", params={"token": TOKEN}, timeout=5).json()["sessions"]
        check(len(ss) == 1 and ss[0]["id"] == "newsess", f"会话列表只剩新的 (实={[s['id'] for s in ss]})")
        check(httpx.post("http://127.0.0.1:8802/cleanup", timeout=5).status_code == 401,
              "/cleanup 无 token 401")
    finally:
        server.should_exit = True


def main():
    print("[unit]")
    unit_tests()
    print("[integration]")
    integration_test()
    print("\n" + ("全部通过 ✅" if ok else "存在失败 ❌"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
