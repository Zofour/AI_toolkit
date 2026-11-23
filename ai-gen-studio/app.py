# -*- coding: utf-8 -*-
"""AI Gen Studio —— 文本模型 + ComfyUI 生图 一体化本地应用"""
import argparse
import io
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime

from flask import Flask, Response, jsonify, request, send_from_directory

from comfy import ComfyClient, WorkflowError, build_workflow
from ollama_client import OllamaClient, parse_json_array

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
HISTORY_PATH = os.path.join(BASE_DIR, 'history.json')

DEFAULT_CONFIG = {
    "port": 5000,
    "remote_port": 8848,
    "comfy_url": "http://127.0.0.1:8000",
    "ollama_url": "http://127.0.0.1:11434",
    "save_dir": "",
    "temp_dir": "D:\\image_temp",
    "negative": "worst quality, low quality, blurry, jpeg artifacts, watermark, text, signature",
    "ckpt_dirs": [
        "C:\\Users\\yourname\\Documents\\ComfyUI\\models\\checkpoints",
        "D:\\Comfy-Desktop\\ComfyUI-Shared\\models\\checkpoints",
        "C:\\Users\\yourname\\Desktop\\else\\SD-WEBUI-AKI-V5.0\\sd-webui-aki-v4.10\\models\\Stable-diffusion"
    ],
    "defaults": {
        "width": 512, "height": 512, "steps": 25, "cfg": 7.0,
        "sampler": "euler", "scheduler": "normal", "batch": 1, "denoise": 0.6
    }
}

_cfg_lock = threading.Lock()


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                user = json.load(f)
            for k, v in user.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception:
            pass
    return cfg


def save_config(cfg):
    with _cfg_lock:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)


CONFIG = load_config()
comfy = ComfyClient(CONFIG['comfy_url'])
ollama = OllamaClient(CONFIG['ollama_url'])

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, 'static'), static_url_path='/static')


@app.after_request
def _no_cache(resp):
    """API 响应一律禁缓存，避免新增模型后浏览器还拿旧列表"""
    if request.path.startswith('/api/'):
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
    return resp


# ------------------------------------------------------------------ 静态
@app.route('/')
def index():
    return send_from_directory(os.path.join(BASE_DIR, 'static'), 'index.html')


# ------------------------------------------------------------------ 配置
@app.route('/api/config', methods=['GET', 'POST'])
def api_config():
    global CONFIG, comfy, ollama
    if request.method == 'POST':
        body = request.get_json(force=True, silent=True) or {}
        CONFIG = load_config()
        for k in ('port', 'comfy_url', 'ollama_url', 'save_dir', 'temp_dir'):
            if k in body and body[k] is not None:
                CONFIG[k] = body[k]
        if isinstance(body.get('defaults'), dict):
            CONFIG['defaults'].update(body['defaults'])
        save_config(CONFIG)
        comfy.set_base(CONFIG['comfy_url'])
        ollama.base = CONFIG['ollama_url'].rstrip('/')
        return jsonify({'ok': True, 'config': CONFIG})
    return jsonify(load_config())


def _ensure_dir(p):
    if p and not os.path.isdir(p):
        try:
            os.makedirs(p, exist_ok=True)
        except Exception:
            pass


def tailscale_ip():
    """取本机 Tailscale IPv4（远程模式只绑这个地址，不暴露给局域网）"""
    for exe in (r'C:\Program Files\Tailscale\tailscale.exe', 'tailscale'):
        try:
            out = subprocess.check_output([exe, 'ip', '-4'], timeout=15,
                                          stderr=subprocess.DEVNULL)
            ip = out.decode('utf-8', 'ignore').strip().splitlines()
            if ip and ip[0].strip():
                return ip[0].strip()
        except Exception:
            continue
    return None


# ------------------------------------------------------------------ 状态 / 模型
@app.route('/api/status')
def api_status():
    o = ollama.ping()
    c, info = comfy.ping()
    return jsonify({'ollama': o, 'comfy': c, 'comfy_info': info,
                    'queue_remaining': comfy.queue_remaining,
                    'ws_connected': comfy.connected,
                    'config': {'temp_dir': CONFIG.get('temp_dir'),
                               'save_dir': CONFIG.get('save_dir')}})


def _scan_ckpt_sizes(dirs):
    """扫模型目录，返回 {相对名: 字节数}，用于智能猜 SD1.5/SDXL"""
    out = {}
    for base in dirs or []:
        if not base or not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for fn in files:
                if not fn.lower().endswith(('.ckpt', '.safetensors')):
                    continue
                rel = os.path.relpath(os.path.join(root, fn), base).replace('/', '\\')
                try:
                    out[rel] = os.path.getsize(os.path.join(root, fn))
                except Exception:
                    pass
    return out


def classify_unet(name):
    n = (name or '').lower()
    if 'z_image' in n:
        return 'z_image'
    if 'anima' in n:
        return 'anima'
    return None


@app.route('/api/models')
def api_models():
    text = []
    ollama_err = None
    try:
        for m in ollama.list_models():
            if m['embedding']:
                continue
            text.append({'name': m['name'], 'vision': m['vision'], 'caps': m['caps'],
                         'size': m['size']})
    except Exception as e:
        ollama_err = str(e)

    comfy_ok, comfy_info = comfy.ping()
    comfy_err = None if comfy_ok else (comfy_info.get('error') or '未连接')

    # ComfyUI 没起就不去慢慢等超时
    ckpts, unets, loras = [], [], []
    if comfy_ok:
        ckpts = comfy.models('checkpoints') or comfy.loader_enum('CheckpointLoaderSimple', 'ckpt_name')
        unets = sorted(set(comfy.models('unet') + comfy.models('diffusion_models')))
        if not unets:
            unets = comfy.loader_enum('UNETLoader', 'unet_name')
        loras = comfy.models('loras') or comfy.loader_enum('LoraLoader', 'lora_name')

    big = []
    for u in sorted(set(unets)):
        k = classify_unet(u)
        if k:
            big.append({'name': u, 'kind': k})
    seen = set()
    ckpt_list = []
    for c in sorted(set(ckpts)):
        if c not in seen:
            seen.add(c)
            ckpt_list.append(c)

    samplers = ['euler', 'euler_ancestral', 'dpmpp_2m', 'dpmpp_2m_sde', 'res_multistep', 'ddim', 'uni_pc', 'lcm']
    schedulers = ['normal', 'karras', 'simple', 'exponential', 'sgm_uniform', 'ddim_uniform']
    if comfy_ok:
        try:
            req = comfy.object_info('KSampler')['KSampler']['input']['required']
            samplers = req['sampler_name'][0]
            schedulers = req['scheduler'][0]
        except Exception:
            pass

    return jsonify({
        'text_models': text,
        'ollama_error': ollama_err,
        'comfy_error': comfy_err,
        'image_models': {
            'checkpoints': ckpt_list,
            'big': big,
        },
        'ckpt_sizes': _scan_ckpt_sizes(CONFIG.get('ckpt_dirs')),
        'samplers': samplers,
        'schedulers': schedulers,
        'loras': sorted(set(loras)),
        'defaults': CONFIG.get('defaults', {}),
        'config': {'temp_dir': CONFIG.get('temp_dir'), 'save_dir': CONFIG.get('save_dir')},
    })


# ------------------------------------------------------------------ 提示词生成（SSE）
@app.route('/api/prompts', methods=['POST'])
def api_prompts():
    body = request.get_json(force=True, silent=True) or {}
    model = body.get('model')
    req = (body.get('requirement') or '').strip()
    n = int(body.get('count') or 4)
    n = max(1, min(10, n))
    hint = body.get('image_model_hint') or ''
    style = (body.get('style') or 'tags').strip()
    if not model or not req:
        return jsonify({'error': '缺少文本模型或需求'}), 400

    def gen():
        try:
            yield sse({'type': 'start', 'count': n, 'style': style})
            result = ''
            for kind, text in ollama.gen_prompts_stream(model, req, n, hint, style):
                if kind == 'result':
                    result = text
                    break
                yield sse({'type': kind, 'text': text})
            prompts = parse_json_array(result)
            if not prompts and result.strip():
                prompts = [result.strip()]
            yield sse({'type': 'prompts', 'prompts': prompts[:10], 'raw': result})
            yield sse({'type': 'end'})
        except Exception as e:
            yield sse({'type': 'error', 'message': str(e)})

    return Response(gen(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def sse(obj):
    return 'data: ' + json.dumps(obj, ensure_ascii=False) + '\n\n'


# ------------------------------------------------------------------ 生图
@app.route('/api/generate', methods=['POST'])
def api_generate():
    body = request.get_json(force=True, silent=True) or {}
    kind = body.get('model_kind', 'checkpoint')
    spec = {
        'model_type': kind,
        'prompt': body.get('prompt', ''),
        'negative': body.get('negative', ''),
        'width': body.get('width', 512),
        'height': body.get('height', 512),
        'steps': body.get('steps', 25),
        'cfg': body.get('cfg', 7.0),
        'sampler': body.get('sampler', 'euler'),
        'scheduler': body.get('scheduler', 'normal'),
        'seed': body.get('seed', -1),
        'batch': body.get('batch', 1),
        'denoise': body.get('denoise', 0.6),
        'loras': body.get('loras') or [],
        'input_image': body.get('input_image') or None,
    }
    if spec['seed'] is None or int(spec['seed']) < 0:
        spec['seed'] = random.randint(0, 2 ** 32 - 1)
    else:
        spec['seed'] = int(spec['seed'])

    if kind == 'checkpoint':
        spec['ckpt'] = body.get('model')
    else:
        spec['unet'] = body.get('model')

    try:
        wf = build_workflow(spec)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    try:
        pid, _job = comfy.queue_prompt(wf)
    except WorkflowError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': '提交失败: ' + str(e)}), 500

    meta = body.get('meta') or {}
    meta.setdefault('model', body.get('model'))
    meta.setdefault('model_kind', kind)
    meta.setdefault('prompt', spec['prompt'])
    meta.setdefault('negative', spec['negative'])
    meta.setdefault('params', {k: spec[k] for k in ('width', 'height', 'steps', 'cfg',
                                                    'sampler', 'scheduler', 'seed', 'batch', 'denoise')})
    _pending_meta[pid] = meta

    return jsonify({'prompt_id': pid, 'seed': spec['seed']})


# ------------------------------------------------------------------ 进度 SSE
@app.route('/api/events/<pid>')
def api_events(pid):
    job = comfy.jobs.get(pid)

    def gen():
        if job is None:
            yield sse({'type': 'error', 'message': '任务不存在'})
            return
        last_beat = 0
        while True:
            evs, done = job.snapshot()
            for e in evs:
                yield sse(e)
            now = time.time()
            if now - last_beat > 1.0:
                last_beat = now
                yield sse({'type': 'heartbeat', 'queue_remaining': comfy.queue_remaining,
                           'ws': comfy.connected})
            if done:
                break
            # 兜底：WS 丢消息时靠 history 判定完成
            if not evs:
                h = comfy.get_history(pid)
                if h and h.get('status', {}).get('completed'):
                    job.finish(h)
                    continue
                if job.error:
                    job.finish()
                    continue
            time.sleep(0.3)

        # 收尾：整理图片 + 归档 temp + 记历史
        hist = job.history or comfy.get_history(pid) or {}
        if not job.history:
            job.history = hist
        imgs = _collect_images(hist)
        meta = _pending_meta.pop(pid, {})
        archived = _archive_to_temp(imgs, meta) if imgs else []
        meta_info = _record_history(pid, archived, job, meta)
        yield sse({'type': 'done', 'images': archived, 'error': job.error, 'meta': meta_info})
        yield sse({'type': 'end'})

    return Response(gen(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def _collect_images(history):
    out = []
    for node_out in (history or {}).get('outputs', {}).values():
        for im in node_out.get('images', []) or []:
            out.append(im)
    return out


_pending_meta = {}


def _safe_part(s, maxlen):
    """文件名安全片段：非法字符替换、去首尾空格点、限长"""
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', s or '')
    s = re.sub(r'\s+', ' ', s).strip().strip('.')
    if maxlen and len(s) > maxlen:
        s = s[:maxlen].rstrip()
    return s


def build_filename(model, prompt, ts, idx, ext='.png'):
    """命名规则：生图模型名 + 提示词 + 时间戳_序号"""
    m = _safe_part(os.path.splitext(os.path.basename(model or ''))[0], 40)
    p = _safe_part(prompt, 60)
    parts = [x for x in (m, p) if x] or ['AIGen']
    base = '+'.join(parts) + '+' + ts + '_' + ('%02d' % idx)
    if len(base) > 150:
        base = base[:150].rstrip('+_ ')
    return base + ext


def _archive_to_temp(images, meta):
    """把生成的图片复制到 temp 目录，命名 = 模型名+提示词+时间戳_序号"""
    temp_dir = CONFIG.get('temp_dir') or ''
    _ensure_dir(temp_dir)
    model = (meta or {}).get('model') or ''
    prompt = (meta or {}).get('prompt') or ''
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = []
    for i, im in enumerate(images, 1):
        try:
            data = comfy.get_image(im)
        except Exception:
            continue
        fn = build_filename(model, prompt, ts, i)
        path = os.path.join(temp_dir, fn) if temp_dir else fn
        k = 1
        while temp_dir and os.path.exists(path):
            k += 1
            stem, ext = os.path.splitext(fn)
            path = os.path.join(temp_dir, f'{stem}_v{k}{ext}')
        fn = os.path.basename(path)
        try:
            with open(path, 'wb') as f:
                f.write(data)
        except Exception:
            path = ''
        out.append({'name': fn, 'path': path, 'ts': ts, 'idx': i,
                    'comfy': {'filename': im.get('filename'), 'subfolder': im.get('subfolder', ''),
                              'type': im.get('type', 'output')}})
    return out


def _record_history(pid, archived, job, meta):
    """写入 history.json（meta 由 /api/generate 的 meta 字段提供）"""
    meta = meta or {}
    rec = {
        'ts': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'prompt_id': pid,
        'mode': meta.get('mode'),
        'io_mode': meta.get('io_mode'),
        'model': meta.get('model'),
        'model_kind': meta.get('model_kind'),
        'requirement': meta.get('requirement', ''),
        'prompt': meta.get('prompt', ''),
        'negative': meta.get('negative', ''),
        'params': meta.get('params', {}),
        'round': meta.get('round'),
        'images': archived,
        'error': job.error,
    }
    hist = []
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                hist = json.load(f)
        except Exception:
            hist = []
    hist.append(rec)
    with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    return {'ts': rec['ts'], 'count': len(archived)}


# ------------------------------------------------------------------ 输入图上传
@app.route('/api/upload', methods=['POST'])
def api_upload():
    f = request.files.get('image')
    if not f:
        return jsonify({'error': '没有文件'}), 400
    data = f.read()
    if len(data) > 60 * 1024 * 1024:
        return jsonify({'error': '图片过大(>60MB)'}), 400
    name = re.sub(r'[^0-9A-Za-z_.\-]', '_', f.filename or 'input.png')
    if not name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        name += '.png'
    try:
        r = comfy.upload_image(name, data)
        real = r.get('name', name)
    except Exception as e:
        return jsonify({'error': '上传到 ComfyUI 失败: ' + str(e)}), 500
    w = h = None
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        w, h = im.size
    except Exception:
        pass
    return jsonify({'name': real, 'subfolder': r.get('subfolder', ''),
                    'width': w, 'height': h})


# ------------------------------------------------------------------ 图片代理
@app.route('/api/image')
def api_image():
    fn = request.args.get('filename')
    im = {'filename': fn, 'subfolder': request.args.get('subfolder', ''),
          'type': request.args.get('type', 'output')}
    try:
        data = comfy.get_image(im)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    mime = 'image/png'
    low = (fn or '').lower()
    if low.endswith('.jpg') or low.endswith('.jpeg'):
        mime = 'image/jpeg'
    elif low.endswith('.webp'):
        mime = 'image/webp'
    return Response(data, mimetype=mime)


@app.route('/__aigendownload')
def aigendownload():
    """手机 App 专用：下载 temp 里的图。App 会拦截这个路径并写入相册；
    万一没拦住，Content-Disposition 会让它变成真下载（走系统下载器）。"""
    name = request.args.get('name', '')
    temp_dir = CONFIG.get('temp_dir') or ''
    safe = os.path.basename(name)
    path = os.path.join(temp_dir, safe)
    if not temp_dir or not os.path.isfile(path):
        return 'not found', 404
    resp = send_from_directory(temp_dir, safe)
    resp.headers['Content-Disposition'] = "attachment; filename*=UTF-8''" + urllib.parse.quote(safe)
    return resp


@app.route('/api/tempfile')
def api_tempfile():
    """直接读取 temp 目录里的文件（预览/打包）"""
    name = request.args.get('name', '')
    temp_dir = CONFIG.get('temp_dir') or ''
    safe = os.path.basename(name)
    path = os.path.join(temp_dir, safe)
    if not temp_dir or not os.path.isfile(path):
        return jsonify({'error': '不存在'}), 404
    return send_from_directory(temp_dir, safe)


# ------------------------------------------------------------------ 保存
@app.route('/api/save', methods=['POST'])
def api_save():
    body = request.get_json(force=True, silent=True) or {}
    save_dir = body.get('dir') or CONFIG.get('save_dir') or ''
    if not save_dir:
        return jsonify({'error': '未设置保存目录'}), 400
    _ensure_dir(save_dir)
    src = body.get('temp_path')
    data = None
    if src and os.path.isfile(src):
        with open(src, 'rb') as f:
            data = f.read()
    else:
        im = body.get('comfy') or {}
        try:
            data = comfy.get_image(im)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    # 默认用 temp 文件的原名（已是「模型名+提示词+时间戳_序号」）
    fn = body.get('filename') or os.path.basename(src or '') or f"AIGen_{ts}.png"
    fn = re.sub(r'[\\/:*?"<>|]', '_', fn)
    fn = os.path.splitext(fn)
    fn = fn[0][:150] + (fn[1] or '.png')
    path = os.path.join(save_dir, fn)
    try:
        with open(path, 'wb') as f:
            f.write(data)
    except Exception as e:
        return jsonify({'error': '写入失败: ' + str(e)}), 500
    return jsonify({'ok': True, 'path': path})


# ------------------------------------------------------------------ 模式2 评判
@app.route('/api/judge', methods=['POST'])
def api_judge():
    body = request.get_json(force=True, silent=True) or {}
    model = body.get('model')
    requirement = body.get('requirement', '')
    prompt_used = body.get('prompt', '')
    im = body.get('image') or {}
    temp_path = body.get('temp_path')
    data = None
    if temp_path and os.path.isfile(temp_path):
        with open(temp_path, 'rb') as f:
            data = f.read()
    elif im:
        try:
            data = comfy.get_image(im)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    if data is None:
        return jsonify({'error': '无法读取图片'}), 400
    try:
        res = ollama.judge(model, requirement, prompt_used, data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify(res)


# ------------------------------------------------------------------ 队列控制
@app.route('/api/interrupt', methods=['POST'])
def api_interrupt():
    try:
        comfy._post('/interrupt', {})
    except Exception:
        pass
    try:
        comfy._post('/queue', {'clear': True})
    except Exception:
        pass
    return jsonify({'ok': True})


@app.route('/api/queue')
def api_queue():
    try:
        d = json.loads(comfy._get('/queue', timeout=10))
        return jsonify({'running': len(d.get('queue_running', [])),
                        'pending': len(d.get('queue_pending', []))})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ------------------------------------------------------------------ 历史
@app.route('/api/history', methods=['GET', 'DELETE'])
def api_history():
    if request.method == 'DELETE':
        with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False)
        return jsonify({'ok': True})
    hist = []
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                hist = json.load(f)
        except Exception:
            hist = []
    return jsonify(hist[::-1])


@app.route('/api/history/meta', methods=['POST'])
def api_history_meta():
    """前端在开始生图前写入本轮元数据，供归档时使用"""
    body = request.get_json(force=True, silent=True) or {}
    pid = body.get('prompt_id')
    if pid:
        _pending_meta[pid] = {k: body.get(k) for k in
                              ('mode', 'io_mode', 'model', 'model_kind', 'requirement',
                               'prompt', 'negative', 'params', 'round')}
    return jsonify({'ok': True})


def startup_scan():
    """启动后扫描一遍模型列表（并清除能力缓存，保证最新）"""
    print('-' * 60)
    ollama.refresh()
    try:
        ms = [m for m in ollama.list_models() if not m['embedding']]
        print(f'[启动扫描] Ollama 文本模型 {len(ms)} 个:')
        for m in ms:
            tag = ('👁 ' if m['vision'] else '   ') + ('🧠 ' if 'thinking' in m['caps'] else '   ')
            print(f'           {tag} {m["name"]}')
    except Exception as e:
        print(f'[启动扫描] Ollama 不可用: {e}')
    try:
        ck = comfy.models('checkpoints') or comfy.loader_enum('CheckpointLoaderSimple', 'ckpt_name')
        un = sorted(set(comfy.models('unet') + comfy.models('diffusion_models'))) \
            or comfy.loader_enum('UNETLoader', 'unet_name')
        big = [u for u in un if classify_unet(u)]
        lo = comfy.models('loras') or comfy.loader_enum('LoraLoader', 'lora_name')
        print(f'[启动扫描] ComfyUI: 标准模型 {len(ck)} 个, 大模型 {len(big)} 个, LoRA {len(lo)} 个')
        for b in big:
            print(f'           [{classify_unet(b)}] {b}')
    except Exception as e:
        print(f'[启动扫描] ComfyUI 不可用: {e}')
    print('-' * 60)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='AI Gen Studio')
    ap.add_argument('--host', default=None, help='绑定地址（默认 127.0.0.1）')
    ap.add_argument('--port', type=int, default=None, help='端口')
    ap.add_argument('--remote', action='store_true',
                    help='远程模式：只绑 Tailscale IP + remote_port，不暴露给局域网')
    args = ap.parse_args()

    host = args.host or '127.0.0.1'
    port = args.port or int(CONFIG.get('port', 5000))
    remote = args.remote

    if remote:
        ip = args.host or tailscale_ip()
        if not ip:
            print('❌ 未检测到 Tailscale IP。请确认 Tailscale 已登录并运行（tailscale ip -4）。')
            sys.exit(1)
        host = ip
        port = args.port or int(CONFIG.get('remote_port', 8848))
        if host in ('0.0.0.0', '::'):
            print('❌ 远程模式不允许绑定 0.0.0.0（会暴露给局域网）。')
            sys.exit(1)

    comfy.start()
    print('=' * 62)
    if remote:
        print(' AI Gen Studio · 远程模式（仅 Tailscale 可达）')
        print(f' 电脑本地访问   http://127.0.0.1:{port}   ← 连不上（故意）')
        print(f' 手机访问       http://{host}:{port}')
    else:
        print(' AI Gen Studio · 本地模式')
        print(f' 本机访问       http://{host}:{port}')
    print(f' 绑定           {host}:{port}')
    print(f' ComfyUI: {CONFIG["comfy_url"]}   Ollama: {CONFIG["ollama_url"]}')
    print(f' temp: {CONFIG["temp_dir"]}   save: {CONFIG.get("save_dir") or "(未设置)"}')
    print('=' * 62)
    startup_scan()
    app.run(host=host, port=port, threaded=True, debug=False)
