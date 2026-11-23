# -*- coding: utf-8 -*-
"""实测 qwen3.8-27b-rvn:q3km 在不同 num_ctx 下的显存占用与 GPU 卸载情况。"""
import json, subprocess, time
import requests

MODEL = "qwen3.8-27b-rvn:q3km"
URL = "http://127.0.0.1:11434"


def gpu_mem():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15).stdout.strip().splitlines()[0]
        used, free = [int(x) for x in out.split(",")]
        return used, free
    except Exception:
        return -1, -1


def unload():
    try:
        requests.post(URL + "/api/generate", json={"model": MODEL, "keep_alive": 0}, timeout=30)
    except Exception:
        pass
    time.sleep(3)


def ps():
    try:
        d = requests.get(URL + "/api/ps", timeout=15).json()
        for m in d.get("models", []):
            if m.get("name", "").startswith(MODEL):
                return {"size": m.get("size"), "vram": m.get("size_vram"),
                        "ctx": m.get("context_length")}
    except Exception:
        pass
    return None


print("baseline VRAM used/free MB:", gpu_mem(), flush=True)

for ctx in [8192, 16384, 24576, 32768, 49152, 65536, 98304, 131072]:
    unload()
    t0 = time.time()
    err = None
    try:
        r = requests.post(URL + "/api/generate", json={
            "model": MODEL, "prompt": "hi", "stream": False, "think": False,
            "keep_alive": "5m", "options": {"num_ctx": ctx, "num_predict": 1}}, timeout=900)
        err = r.json().get("error")
    except Exception as e:
        err = str(e)
    dt = time.time() - t0
    g_used, g_free = gpu_mem()
    p = ps()
    vram = p["vram"] if p else 0
    size = p["size"] if p else 0
    frac = (100.0 * vram / size) if size else 0
    print("ctx=%7d  load=%5.1fs  nvidia_used=%5dMB free=%5dMB  ps_size=%s vram=%s (%s%%)  err=%s"
          % (ctx, dt, g_used, g_free, size, vram, round(frac), err), flush=True)

unload()
print("DONE", flush=True)
