# -*- coding: utf-8 -*-
"""num_gpu=999 下继续上推上下文，找真实上限（含 nvidia 显存）。"""
import subprocess, time
import requests

MODEL = "qwen3.8-27b-rvn:q3km"
URL = "http://127.0.0.1:11434"


def gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.free",
                              "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=15).stdout.strip().splitlines()[0]
        return [int(x) for x in out.split(",")]
    except Exception:
        return [-1, -1]


def ps():
    try:
        d = requests.get(URL + "/api/ps", timeout=15).json()
        for m in d.get("models", []):
            if m.get("name", "").startswith(MODEL):
                return m.get("size"), m.get("size_vram")
    except Exception:
        pass
    return 0, 0


def unload():
    try:
        requests.post(URL + "/api/generate", json={"model": MODEL, "keep_alive": 0}, timeout=30)
    except Exception:
        pass
    time.sleep(3)


def gen(ctx, npred, prompt):
    return requests.post(URL + "/api/generate", json={
        "model": MODEL, "prompt": prompt, "stream": False, "think": False,
        "keep_alive": "5m",
        "options": {"num_ctx": ctx, "num_predict": npred, "temperature": 0.7, "num_gpu": 999}},
        timeout=900).json()


for ctx in [65536, 98304, 131072, 196608, 262144]:
    unload()
    d0 = gen(ctx, 1, "hi")
    err = d0.get("error")
    try:
        d = gen(ctx, 120, "写一段大约一百字的短文，主题是春天。")
        ec, ed = d.get("eval_count", 0), d.get("eval_duration", 1)
        tps = ec / (ed / 1e9)
    except Exception as e:
        tps = -1
        err = err or str(e)
    size, vram = ps()
    pct = round(100.0 * vram / size) if size else 0
    g = gpu()
    print("ctx=%7d  GPU=%3d%%  gen=%5.2f tok/s  vram_used=%5dMB  err=%s"
          % (ctx, pct, tps, g[0], err), flush=True)

unload()
print("DONE", flush=True)
