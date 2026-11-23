# -*- coding: utf-8 -*-
import requests, time, sys
sys.stdout.reconfigure(encoding="utf-8")
H = "http://127.0.0.1:11434"
SYS = ("你是专业的技术文档翻译引擎。把用户给出的英文翻译成简体中文。规则："
       "1)只输出译文，不要任何解释或前言；2)保持原有Markdown结构与换行；"
       "3)代码、命令、变量名、函数名、文件路径、URL、数字、数学公式一律原样保留，不翻译；"
       "4)若输入已是中文则原样输出。")
lines = [
    "First, I need to understand what the user is really asking for.",
    "The time complexity is O(n log n) and the space complexity is O(1).",
    "I should be careful about the edge case where the input list is empty.",
    "Let me verify: if n = 5, the loop runs exactly five times.",
]
t0 = time.time()
for L in lines:
    r = requests.post(H + "/api/chat", json={
        "model": "qwen3-vl:8b", "think": False, "stream": False,
        "options": {"temperature": 0},
        "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": L}],
    }, timeout=120).json()
    msg = r.get("message", {})
    print(f"{time.time()-t0:5.2f}s | thinking={bool(msg.get('thinking'))} | {msg.get('content','').strip()}")

# 一次请求里带代码块，看是否保留
big = ("The iterative approach uses three pointers.\n"
       "```python\ndef reverse(head):\n    prev = None\n    return prev\n```\n"
       "The space complexity is O(1).")
t0 = time.time()
r = requests.post(H + "/api/chat", json={"model": "qwen3-vl:8b", "think": False, "stream": False,
    "options": {"temperature": 0},
    "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": big}]}, timeout=120).json()
print(f"\n--- code block test ({time.time()-t0:.2f}s) ---")
print(r.get("message", {}).get("content", "").strip())
