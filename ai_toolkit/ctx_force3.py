# -*- coding: utf-8 -*-
"""精确定位显存悬崖：num_gpu=999 下逐档测 vram_used + tok/s。"""
import subprocess, time
import requests

MODEL = "qwen3.8-27b-rvn:q3km"
URL = "http://127.0.0.1:11434"


def gpu_used():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15).stdout.strip().splitlines()[0]
        return int(out)
    except Exception:
        return -1


def unload():
    try:
        requests.post(URL + "/api/generate", json={"model": MODEL, "keep_alive": 0}, timeout=30)
    except Exception:
        pass
    time.sleep(3)


def gen(ctx, npred, prompt):
    return requests.post(URL + "/api/generate", json={
        "model": MODEL, "prompt": prompt, "stream": False, "think": False, "keep_alive": "5m",
        "options": {"num_ctx": ctx, "num_predict": npred, "temperature": 0.7, "num_gpu": 999}},
        timeout=900).json()


for ctx in [32768, 40960, 49152, 53248, 57344, 61440, 65536]:
    unload()
    gen(ctx, 1, "hi")
    before = gpu_used()
    d = gen(ctx, 120, "写一段大约一百字的短文，主题是春天。")
    peak = gpu_used()
    ec, ed = d.get("eval_count", 0), d.get("eval_duration", 1)
    tps = ec / (ed / 1e9)
    print("ctx=%7d  gen=%6.2f tok/s  vram_before=%5dMB peak=%5dMB" % (ctx, tps, before, peak), flush=True)

unload()
print("DONE", flush=True)
