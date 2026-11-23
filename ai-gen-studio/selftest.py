# -*- coding: utf-8 -*-
"""AI Gen Studio 自测：不常驻，跑完自动退出。
1) 连通性 / 模型清单
2) 四类工作流本地结构校验（对照 ComfyUI object_info，不占 GPU）
3) 一次真实小图生成（端到端），轮询到完成即止
"""
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comfy import ComfyClient, build_workflow  # noqa
from ollama_client import OllamaClient  # noqa

COMFY = "http://127.0.0.1:8000"
OLLAMA = "http://127.0.0.1:11434"
FAIL = []


def log(*a):
    print(*a, flush=True)


def check(cond, msg):
    log(('  PASS ' if cond else '  FAIL ') + msg)
    if not cond:
        FAIL.append(msg)


c = ComfyClient(COMFY)
o = OllamaClient(OLLAMA)

log('=== 1. 连通性 ===')
ok, info = c.ping()
check(ok, f'ComfyUI 可连 {info}')
check(o.ping(), 'Ollama 可连')

ck = c.models('checkpoints')
un = sorted(set(c.models('unet') + c.models('diffusion_models')))
lo = c.models('loras')
log(f'checkpoints({len(ck)}): {ck}')
log(f'unet({len(un)}): {un}')
log(f'loras({len(lo)}): {lo}')

info_all = c.object_info()

log('=== 2. 工作流结构校验（本地，不跑 GPU）===')


def validate(wf):
    errs = []
    for nid, node in wf.items():
        ct = node['class_type']
        if ct not in info_all:
            errs.append(f'节点类型不存在: {ct}')
            continue
        req = info_all[ct]['input'].get('required', {}) or {}
        for k in req:
            if k not in node['inputs']:
                errs.append(f'{ct}#{nid} 缺必填输入 {k}')
    return errs


PY = getattr(sys, 'argv', [])


def wf_check(name, spec):
    try:
        wf = build_workflow(spec)
    except Exception as e:
        check(False, f'{name} 构建异常: {e}')
        return None
    errs = validate(wf)
    check(not errs, f'{name} 结构 OK' + ('' if not errs else ' -> ' + '; '.join(errs)))
    return wf


target_ck = 'cosfMix-v2.safetensors' if 'cosfMix-v2.safetensors' in ck else (ck[0] if ck else 'x')
base_ck = {'steps': 20, 'cfg': 7, 'sampler': 'euler', 'scheduler': 'normal', 'seed': 1, 'batch': 1}

# 上传一张测试输入图（图生图用）
from PIL import Image  # noqa
buf = io.BytesIO()
Image.new('RGB', (64, 64), (120, 120, 120)).save(buf, 'PNG')
up = c.upload_image('selftest_input.png', buf.getvalue())
log('  上传输入图:', up)

w_txt = wf_check('checkpoint txt2img',
                 dict(base_ck, model_type='checkpoint', ckpt=target_ck, prompt='a cat',
                      width=512, height=512, denoise=1.0))
w_i2i = wf_check('checkpoint img2img',
                 dict(base_ck, model_type='checkpoint', ckpt=target_ck, prompt='a cat',
                      denoise=0.6, input_image=up.get('name')))
w_z = wf_check('z_image txt2img',
               dict(model_type='z_image', prompt='a cat', width=1024, height=1024,
                    steps=8, cfg=1, sampler='res_multistep', scheduler='simple', seed=1, batch=1, denoise=1.0))
w_a = wf_check('anima txt2img',
               dict(model_type='anima', prompt='a cat', width=1024, height=1024,
                    steps=30, cfg=4, sampler='euler', scheduler='simple', seed=1, batch=1, denoise=1.0))

RUN_GEN = '--gen' in sys.argv
log('=== 3. 端到端真实生成（小图，1 张）===')
if RUN_GEN and w_txt:
    spec = dict(base_ck, model_type='checkpoint', ckpt=target_ck, prompt='a red apple on a table',
                negative='', width=384, height=384, steps=8, batch=1, denoise=1.0, seed=12345)
    try:
        pid, job = c.queue_prompt(build_workflow(spec))
        log(f'  已提交 prompt_id={pid}，等待完成…')
        t0 = time.time()
        hist = None
        while time.time() - t0 < 90:
            h = c.get_history(pid)
            if h and h.get('status', {}).get('completed'):
                hist = h
                break
            time.sleep(1.5)
        if hist:
            imgs = []
            for node_out in hist.get('outputs', {}).values():
                imgs += node_out.get('images', []) or []
            check(len(imgs) > 0, f'生成完成，产出 {len(imgs)} 张，用时 {time.time()-t0:.1f}s')
            for im in imgs:
                data = c.get_image(im)
                check(len(data) > 1000, f'取回图片 {im["filename"]} ({len(data)} bytes)')
        else:
            check(False, f'90s 内未完成（可能模型过大或出错）')
    except Exception as e:
        check(False, f'端到端生成异常: {type(e).__name__}: {e}')

if not RUN_GEN:
    log('  （跳过真实生成，加 --gen 可执行）')

log('=== 4. Ollama 识图模型（模式2 可用性）===')
for m in o.list_models():
    if m['embedding']:
        continue
    log(f"  {m['name']:<42} vision={m['vision']} caps={','.join(m['caps'])}")

log('')
log('==== 结果 ====')
if FAIL:
    log(f'❌ {len(FAIL)} 项失败:')
    for f in FAIL:
        log('   - ' + f)
    sys.exit(1)
log('✅ 全部通过')
sys.exit(0)
