# -*- coding: utf-8 -*-
"""扫描整个 ExampleGame_Data，提取所有含假名的日文串 -> jp_strings.json"""
import os, re, json, collections

GAME = r"C:\Users\yourname\Desktop\game！\ss\示例游戏"
DATA = os.path.join(GAME, "ExampleGame_Data")
HERE = os.path.dirname(os.path.abspath(__file__))

JP = re.compile(
    r"[\u3000-\u303f\u3040-\u30ff\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef"
    r"\u2010-\u2027\u2460-\u24ff"
    r"A-Za-z0-9 .,!?;:'\"()\[\]{}\-_/\\@#%&*+=<>~|^`$]{2,}"
)
KANA = re.compile(r"[\u3040-\u30ff]")
SKIP = {".ress", ".resource", ".dll", ".exe", ".json", ".xml", ".txt", ".bat"}

res = collections.Counter()
CH = 8 * 1024 * 1024
targets = []
for root, _, fs in os.walk(DATA):
    for f in fs:
        if os.path.splitext(f)[1].lower() in SKIP:
            continue
        targets.append(os.path.join(root, f))

for p in targets:
    try:
        with open(p, "rb") as f:
            tail = ""
            while True:
                b = f.read(CH)
                if not b:
                    break
                s = tail + b.decode("utf-8", "ignore")
                tail = s[-64:]
                for m in JP.finditer(s):
                    g = m.group(0).strip()
                    if len(g) >= 2 and KANA.search(g):
                        res[g] += 1
    except Exception as e:
        print("ERR", os.path.basename(p), e)

uniq = sorted(res, key=lambda s: (-len(s), s))
json.dump(uniq, open(os.path.join(HERE, "jp_strings.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=0)
print("unique:", len(uniq), "chars:", sum(map(len, uniq)))
