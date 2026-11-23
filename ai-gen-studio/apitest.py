# -*- coding: utf-8 -*-
"""HTTP 层自测：进程内起 Flask，测完立即关闭（不常驻）。"""
import json
import os
import sys
import threading
import time
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from werkzeug.serving import make_server  # noqa
import app as A  # noqa

PORT = 5055
BASE = f'http://127.0.0.1:{PORT}'
FAIL = []


def log(*a):
    print(*a, flush=True)


def check(c, m):
    log(('  PASS ' if c else '  FAIL ') + m)
    if not c:
        FAIL.append(m)


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=30).read())


def post(path, obj):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode(),
                                 headers={'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


# 用临时目录做 temp / save 测试
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_test_temp')
SAV = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_test_save')
A.CONFIG['temp_dir'] = TMP
A.CONFIG['save_dir'] = SAV

srv = make_server('127.0.0.1', PORT, A.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
A.comfy.start()
time.sleep(0.6)

try:
    log('=== 1. 基础接口 ===')
    st = get('/api/status')
    check(st['comfy'] and st['ollama'], f"status comfy={st['comfy']} ollama={st['ollama']}")
    mm = get('/api/models')
    check(len(mm['image_models']['checkpoints']) > 0,
          f"checkpoints={len(mm['image_models']['checkpoints'])} big={[b['kind'] for b in mm['image_models']['big']]}")
    check(len(mm['samplers']) > 10, f"samplers={len(mm['samplers'])} schedulers={len(mm['schedulers'])}")
    check(len(mm['text_models']) > 0, f"text_models={len(mm['text_models'])}")

    log('=== 2. 生图 + 进度 SSE + 归档 temp ===')
    body = {
        'model_kind': 'checkpoint', 'model': 'cosfMix-v2.safetensors',
        'prompt': 'a red apple, studio light', 'negative': 'bad',
        'width': 384, 'height': 384, 'steps': 6, 'cfg': 7,
        'sampler': 'euler', 'scheduler': 'normal', 'seed': 777, 'batch': 2, 'denoise': 1.0,
        'meta': {'mode': 1, 'io_mode': 'txt2img', 'requirement': '一个红苹果'}
    }
    r = post('/api/generate', body)
    check('prompt_id' in r, f"提交生图 prompt_id={r.get('prompt_id')} seed={r.get('seed')}")
    pid = r['prompt_id']

    events = []
    done_imgs = []
    t0 = time.time()
    resp = urllib.request.urlopen(BASE + '/api/events/' + pid, timeout=120)
    cur = []
    stopped = False
    for raw in resp:
        if time.time() - t0 > 100:
            break
        line = raw.decode('utf-8', 'ignore').rstrip('\n')
        if line.strip() == '':
            if cur:
                payload = [l[5:] for l in cur if l.startswith('data:')]
                cur = []
                if payload:
                    d = json.loads(payload[0])
                    events.append(d['type'])
                    if d['type'] == 'done':
                        done_imgs = d['images']
                    if d['type'] == 'end':
                        stopped = True
                        break
            continue
        cur.append(line)
    check('progress' in events or 'cached' in events, f"收到进度事件（类型集合: {sorted(set(events))}）")
    check(len(done_imgs) == 2, f"done 返回 {len(done_imgs)} 张归档记录")
    existing = [im for im in done_imgs if im['path'] and os.path.isfile(im['path'])]
    check(len(existing) == 2, f"temp 目录实际落盘 {len(existing)} 个文件 -> {TMP}")
    print('    归档文件名:')
    for im in done_imgs:
        print('      ', im['name'])

    log('=== 3. 图片代理 / tempfile ===')
    if done_imgs:
        raw = urllib.request.urlopen(BASE + '/api/tempfile?name=' + urllib.parse.quote(done_imgs[0]['name']), timeout=20).read()
        check(len(raw) > 1000, f"tempfile 读取 {len(raw)} bytes")
        cu = done_imgs[0]['comfy']
        raw2 = urllib.request.urlopen(BASE + '/api/image?filename=' + urllib.parse.quote(cu['filename']), timeout=20).read()
        check(len(raw2) > 1000, f"comfy 原图代理 {len(raw2)} bytes")

    log('=== 4. 保存 ===')
    if done_imgs:
        s = post('/api/save', {'temp_path': done_imgs[0]['path']})
        check(s.get('ok') and os.path.isfile(s.get('path', '')), f"保存成功 -> {os.path.basename(s.get('path',''))}")

    log('=== 5. 历史 ===')
    h = get('/api/history')
    check(len(h) >= 1 and h[0]['images'], f"history 条数={len(h)} 最新图数={len(h[0]['images']) if h else 0}")

    log('=== 6. config 读写 ===')
    c = post('/api/config', {'save_dir': SAV})
    check(c['ok'] and c['config']['save_dir'] == SAV, 'config 保存回读 OK')

finally:
    srv.shutdown()
    log('服务已关闭')

log('')
if FAIL:
    log(f'❌ {len(FAIL)} 项失败')
    for f in FAIL:
        log('   - ' + f)
    sys.exit(1)
log('✅ HTTP 层全部通过')
sys.exit(0)
