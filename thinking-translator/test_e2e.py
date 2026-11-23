# -*- coding: utf-8 -*-
"""端到端测试：启动 假上游 + 代理，验证 reasoning_content 被替换成中文。
  python test_e2e.py            # 用真实本地模型（较慢，需已下载模型）
  python test_e2e.py --fake     # 用假翻译器（秒级，只验证管路）
"""
import os, sys, json, time, threading, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("UPSTREAM_BASE", "http://127.0.0.1:9911")
os.environ.setdefault("PORT", "8788")
os.environ.setdefault("DEBUG", "1")

import uvicorn, requests


def serve(app, port):
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    return srv, t


class FakeTranslator:
    def translate(self, t):
        return "【译】" + t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true")
    args = ap.parse_args()

    import mock_upstream
    serve(mock_upstream.app, 9911)
    time.sleep(1)

    import proxy
    if args.fake:
        proxy._tr = FakeTranslator()
    serve(proxy.app, 8788)
    time.sleep(1)
    if not args.fake:
        print("[test] warming translator (loading model)...", flush=True)
        proxy.get_translator()

    payload = {"model": "mock", "stream": True,
               "messages": [{"role": "user", "content": "how to reverse a linked list"}]}
    print("[test] POST http://127.0.0.1:8788/v1/chat/completions (stream)", flush=True)
    r = requests.post("http://127.0.0.1:8788/v1/chat/completions", json=payload,
                      stream=True, timeout=300)
    print("[test] status", r.status_code, flush=True)
    reason, content, nchunks = [], [], 0
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        p = line[5:].strip()
        if p == "[DONE]":
            break
        try:
            o = json.loads(p)
        except Exception:
            continue
        d = (o.get("choices") or [{}])[0].get("delta") or {}
        if d.get("reasoning_content"):
            reason.append(d["reasoning_content"]); nchunks += 1
        if d.get("content"):
            content.append(d["content"])
    R = "".join(reason); C = "".join(content)
    print("\n=== 收到的 reasoning（前 400 字）===\n", R[:400], flush=True)
    print("\n=== 收到的 content ===\n", C[:200], flush=True)
    print(f"\n[test] reasoning 分片={nchunks} 总长={len(R)}", flush=True)
    ok = len(R) > 0 and ("译" in R or any('\u4e00' <= ch <= '\u9fff' for ch in R))
    print("[test] RESULT:", "PASS - 思考过程已变中文" if ok else "FAIL", flush=True)


if __name__ == "__main__":
    main()
