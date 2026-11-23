# -*- coding: utf-8 -*-
import json, requests
r = requests.post("http://127.0.0.1:11434/api/chat", json={
    "model": "qwen3.8-27b-rvn:q3km",
    "messages": [{"role": "user", "content": "9.11 和 9.9 哪个大？简短回答。"}],
    "stream": False, "think": True,
    "options": {"num_predict": 300, "num_ctx": 8192},
}, timeout=300)
d = r.json()
m = d.get("message", {})
print("FIELDS:", list(m.keys()))
print("--- thinking field ---")
print((m.get("thinking") or "")[:400])
print("--- content field ---")
print((m.get("content") or "")[:400])
