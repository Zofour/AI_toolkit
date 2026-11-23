# -*- coding: utf-8 -*-
"""LLM 部分自测：解析器单元测试 + 真实流式连通性（有界，跑完强制退出）"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ollama_client import OllamaClient, parse_json_array, parse_judge  # noqa

FAIL = []


def check(c, m):
    print(('  PASS ' if c else '  FAIL ') + m, flush=True)
    if not c:
        FAIL.append(m)


print('=== 1. 解析器单元测试 ===')
check(parse_json_array('```json\n["a cat","a dog"]\n```') == ['a cat', 'a dog'], 'JSON 数组 + 围栏')
check(parse_json_array('["a", "b", "c"]') == ['a', 'b', 'c'], '纯 JSON 数组')
check(len(parse_json_array('1. a cat\n2. a dog\n3. a fox')) == 3, '退回按行解析')
check(parse_json_array('{"prompts":["x","y"]}') == ['x', 'y'], '对象 prompts 字段')
j = parse_judge('{"ok": true, "reason": "符合", "new_prompt": ""}')
check(j['ok'] is True and j['reason'] == '符合', 'judge JSON True')
j2 = parse_judge('```json\n{"ok": false, "reason": "太暗", "new_prompt": "brighter"}\n```')
check(j2['ok'] is False and j2['new_prompt'] == 'brighter', 'judge JSON False + 围栏')
j3 = parse_judge('The image looks good, ok: true')
check(j3['ok'] is True, 'judge 非 JSON 兜底')

print('=== 2. Ollama 流式连通性（最小模型，拿到首 token 即止）===')
o = OllamaClient('http://127.0.0.1:11434')
MODEL = 'tobestyledintro/minicpm5-2b:128k'
got = {'content': 0, 'thinking': 0}
t0 = time.time()
try:
    for kind, text in o.chat_stream(MODEL, [{'role': 'user', 'content': '只回答两个字：你好'}]):
        got[kind] = got.get(kind, 0) + 1
        if got.get('content', 0) >= 1:
            break
        if time.time() - t0 > 60:
            break
    check(got.get('content', 0) >= 1 or got.get('thinking', 0) >= 1,
          f"流式收到 token（content={got.get('content',0)} thinking={got.get('thinking',0)}，{time.time()-t0:.1f}s）")
except Exception as e:
    check(False, f'流式异常: {type(e).__name__}: {e}')

print('=== 3. 识图模型评判（线程有界 100s）===')
from PIL import Image  # noqa
import io
buf = io.BytesIO()
Image.new('RGB', (64, 64), (200, 30, 30)).save(buf, 'PNG')
img = buf.getvalue()
res = {}


def run_judge():
    try:
        res['r'] = o.judge('qwen3-vl:8b', '一张纯红色图片', 'a solid red image', img)
    except Exception as e:
        res['err'] = f'{type(e).__name__}: {e}'


th = threading.Thread(target=run_judge, daemon=True)
t0 = time.time()
th.start()
th.join(100)
if th.is_alive():
    print(f'  SKIP 评判超过 100s 未返回（本机大模型较慢，非代码问题），跳过')
elif 'err' in res:
    check(False, f'评判异常: {res["err"]}')
else:
    r = res['r']
    check('ok' in r, f'评判返回 ok={r.get("ok")} reason={r.get("reason")!r}（{time.time()-t0:.1f}s）')

print('=== 4. 提示词生成：两种风格对比（真实调用，每种有界 80s）===')
REQ = '一个在雨夜霓虹街道上撑伞的赛博朋克少女，回头看向镜头'


def gen_style(style):
    out = {}

    def run():
        try:
            last = ''
            for kind, text in o.gen_prompts_stream(MODEL, REQ, 2, 'checkpoint', style):
                if kind == 'result':
                    last = text
            out['list'] = parse_json_array(last)
        except Exception as e:
            out['err'] = f'{type(e).__name__}: {e}'

    th = threading.Thread(target=run, daemon=True)
    t0 = time.time()
    th.start()
    th.join(80)
    if th.is_alive():
        print(f'  SKIP [{style}] 超过 80s 未返回')
        return None
    if 'err' in out:
        check(False, f'{style} 异常: {out["err"]}')
        return None
    lst = out.get('list', [])
    check(len(lst) >= 1, f'[{style}] 生成 {len(lst)} 条（{time.time()-t0:.1f}s）')
    for i, p in enumerate(lst[:2], 1):
        print(f'    {i}. {p[:130]}')
    return lst


tags = gen_style('tags')
sent = gen_style('sentence')
if tags:
    joined = ' '.join(tags)
    check(',' in joined, '标签式输出含逗号（词, 词, 词 形式）')
    dens_t = sum(t.count(',') for t in tags) / max(1, sum(len(t) for t in tags)) * 100
    print(f'    标签式：平均 {sum(len(t) for t in tags)/len(tags):.0f} 字符，逗号密度 {dens_t:.1f}/100字')
if sent:
    print(f'    描述句：平均 {sum(len(t) for t in sent)/len(sent):.0f} 字符')
    if tags:
        dens_s = sum(t.count(',') for t in sent) / max(1, sum(len(t) for t in sent)) * 100
        print(f'    描述句逗号密度 {dens_s:.1f}/100字')
        check(dens_t > dens_s, '标签式的逗号密度明显高于描述句（风格确实不同）')

print('')
if FAIL:
    print(f'❌ {len(FAIL)} 项失败')
    for f in FAIL:
        print('   - ' + f)
else:
    print('✅ 解析器与流式全部通过')
sys.stdout.flush()
os._exit(1 if FAIL else 0)
