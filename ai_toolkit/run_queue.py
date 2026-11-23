#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_queue.py —— 串行跑片队列（格林德沃 → 邓布利多），中途不并发抢 GPU"""
import subprocess
import sys
import time
from pathlib import Path

SCRIPT = r"C:\chatbox_temp\ai_toolkit\bili_interp_fast.py"
OUT = r"D:\video_interp"
LOG = Path(r"D:\video_interp\_queue.log")

JOBS = [
    r"D:\video_interp\_src\格林德沃之罪_中文版.mp4",
    # 邓布利多之谜：用户 2026-11-22 决定不跑，片源与中间文件已删
]
COMMON = ["--fps", "60", "--width", "1920", "--fast", "--jobs", "2", "--pipe", "3", "--out-dir", OUT]


def log(msg):
    line = f"[queue] {time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


if __name__ == "__main__":
    for i, src in enumerate(JOBS, 1):
        log(f"==== {i}/{len(JOBS)} 开始: {Path(src).name} ====")
        t0 = time.time()
        r = subprocess.run([sys.executable, SCRIPT, src] + COMMON)
        used = (time.time() - t0) / 3600
        log(f"==== {i}/{len(JOBS)} 结束: {Path(src).name}  returncode={r.returncode}  用时 {used:.2f} 小时 ====")
    log("==== 全部完成 ====")
