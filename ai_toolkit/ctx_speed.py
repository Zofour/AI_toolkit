# -*- coding: utf-8 -*-
"""实测不同 num_ctx 下的生成速度(tok/s)与 GPU 卸载比例。"""
import subprocess, time
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


def gen(ctx, num_predict, prompt):
    return requests.post(URL + "/api/generate", json={
        "model": MODEL, "prompt": prompt, "stream": False, "think": False,
        "keep_alive": "5m",
        "options": {"num_ctx": ctx, "num_predict": num_predict, "temperature": 0.7}}, timeout=900).json()


for ctx in [8192, 16384, 32768, 49152, 65536, 98304, 131072]:
    unload()
    t0 = time.time()
    gen(ctx, 1, "hi")                      # 预热加载
    load = time.time() - t0
    d = gen(ctx, 150, "写一段大约一百字的短文，主题是春天。")
    ec, ed = d.get("eval_count", 0), d.get("eval_duration", 1)
    tps = ec / (ed / 1e9)
    pc, pd = d.get("prompt_eval_count", 0), d.get("prompt_eval_duration", 1)
    ptps = pc / (pd / 1e9)
    size, vram = ps()
    pct = round(100.0 * vram / size) if size else 0
    print("ctx=%7d  GPU=%3d%%  gen=%5.2f tok/s  prefill=%6.1f tok/s  load=%5.1fs"
          % (ctx, pct, tps, ptps, load), flush=True)

unload()
print("DONE", flush=True)
