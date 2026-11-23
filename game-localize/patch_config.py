# -*- coding: utf-8 -*-
"""把 XUnity.AutoTranslator 的 Config.ini 指到本机翻译服务。可反复执行（幂等）。"""
import os, re, shutil, sys

GAME = r"C:\Users\yourname\Desktop\game！\ss\示例游戏"
CFG = os.path.join(GAME, "AutoTranslator", "Config.ini")
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8791/translate"

WANT = {
    "Service": {
        "Endpoint": "CustomTranslate",
        "FallbackEndpoint": "",
    },
    "General": {
        "Language": "zh",
        "FromLanguage": "ja",
    },
    "Custom": {
        "Url": URL,
    },
}

bak = CFG + ".orig_bak"
if not os.path.exists(bak):
    shutil.copy2(CFG, bak)
    print("backup ->", bak)

text = open(CFG, encoding="utf-8-sig").read()
lines = text.splitlines()
out, section = [], ""
seen = {s: set() for s in WANT}
for ln in lines:
    m = re.match(r"^\[(.+?)\]\s*$", ln.strip())
    if m:
        section = m.group(1)
        out.append(ln)
        continue
    m = re.match(r"^([^=;#\[\]]+)\s*=(.*)$", ln)
    if m and section in WANT and m.group(1).strip() in WANT[section]:
        k = m.group(1).strip()
        out.append(f"{k}={WANT[section][k]}")
        seen[section].add(k)
    else:
        out.append(ln)

# 补缺失的键/节
for sec, kv in WANT.items():
    missing = {k: v for k, v in kv.items() if k not in seen[sec]}
    if not missing:
        continue
    hdr = f"[{sec}]"
    if hdr in out:
        i = out.index(hdr) + 1
        while i < len(out) and not out[i].strip().startswith("["):
            i += 1
        out[i:i] = [f"{k}={v}" for k, v in missing.items()]
    else:
        out += [hdr] + [f"{k}={v}" for k, v in missing.items()]

open(CFG, "w", encoding="utf-8", newline="\r\n").write("\n".join(out) + "\n")
print("patched:", CFG)
for sec, kv in WANT.items():
    print(f"  [{sec}] " + ", ".join(f"{k}={v}" for k, v in kv.items()))
