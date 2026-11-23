# -*- coding: utf-8 -*-
"""qwen3.8-27b-rvn Ollama 自检：文本 / 思考 / 视觉。"""
import base64, json, sys, time
import requests

API = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3.8-27b-rvn:q3km"


def call(payload, timeout=300):
    t0 = time.time()
    r = requests.post(API, json=payload, timeout=timeout)
    r.raise_for_status()
    d = r.json()
    dt = time.time() - t0
    tps = d.get("eval_count", 0) / (d.get("eval_duration", 1) / 1e9)
    return d, dt, tps


def main():
    img = sys.argv[1] if len(sys.argv) > 1 else None

    print("=== 1) 文本（关闭思考） ===")
    d, dt, tps = call({"model": MODEL, "prompt": "用中文一句话介绍你自己。",
                       "stream": False, "think": False,
                       "options": {"num_predict": 80, "num_ctx": 8192}})
    print("response:", d["response"].strip())
    print("thinking:", (d.get("thinking") or "").strip()[:200] or "(空)")
    print("~%.1f tok/s, wall %.1fs" % (tps, dt))

    print("\n=== 2) 思考模式开启（think=true） ===")
    d, dt, tps = call({"model": MODEL, "prompt": "9.11 和 9.9 哪个大？",
                       "stream": False, "think": True,
                       "options": {"num_predict": 400, "num_ctx": 8192}})
    print("thinking:", (d.get("thinking") or "").strip()[:300])
    print("response:", d["response"].strip()[:300])
    print("~%.1f tok/s" % tps)

    if img:
        print("\n=== 3) 视觉（%s） ===" % img)
        with open(img, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        d, dt, tps = call({"model": MODEL,
                           "prompt": "请用中文详细描述这张图片的内容。",
                           "images": [b64], "stream": False, "think": False,
                           "options": {"num_predict": 300, "num_ctx": 8192}})
        print("response:", d["response"].strip())
        print("~%.1f tok/s, wall %.1fs" % (tps, dt))
    else:
        print("\n(未提供图片，跳过视觉测试)")


if __name__ == "__main__":
    main()
