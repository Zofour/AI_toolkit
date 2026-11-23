# -*- coding: utf-8 -*-
"""测试强制 num_gpu=999（全层上 GPU）能否把上下文推更高。"""
import time
import requests

MODEL = "qwen3.8-27b-rvn:q3km"
URL = "http://127.0.0.1:11434"


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


def gen(ctx, npred, prompt, num_gpu):
    opt = {"num_ctx": ctx, "num_predict": npred, "temperature": 0.7}
    if num_gpu:
        opt["num_gpu"] = num_gpu
    return requests.post(URL + "/api/generate", json={
        "model": MODEL, "prompt": prompt, "stream": False, "think": False,
        "keep_alive": "5m", "options": opt}, timeout=900).json()


for num_gpu in [999, 999, 999]:
    for ctx in [16384, 32768, 49152]:
        unload()
        d0 = gen(ctx, 1, "hi", num_gpu)
        err = d0.get("error")
        d = gen(ctx, 120, "写一段大约一百字的短文，主题是春天。", num_gpu)
        ec, ed = d.get("eval_count", 0), d.get("eval_duration", 1)
        tps = ec / (ed / 1e9)
        size, vram = ps()
        pct = round(100.0 * vram / size) if size else 0
        print("num_gpu=%d ctx=%6d  GPU=%3d%%  gen=%5.2f tok/s  err=%s"
              % (num_gpu, ctx, pct, tps, err), flush=True)
    break

unload()
print("DONE", flush=True)
