# -*- coding: utf-8 -*-
"""
ComfyUI 客户端 + 工作流构建器
- 通过 HTTP API 提交 prompt、读取 history、上传输入图、取回图片
- 通过 WebSocket 接收实时进度
- 按「模型类型」动态拼装工作流：checkpoint / z_image / anima
"""
import io
import json
import threading
import time
import uuid
import urllib.parse
import urllib.request

try:
    import websocket  # websocket-client
except Exception:  # pragma: no cover
    websocket = None


# ---------------------------------------------------------------- Job
class Job:
    def __init__(self, prompt_id):
        self.prompt_id = prompt_id
        self.events = []
        self.images = []
        self.done = False
        self.error = None
        self.archived = False
        self.history = None
        self.lock = threading.Lock()
        self.cursor = 0

    def emit(self, ev):
        with self.lock:
            self.events.append(ev)

    def snapshot(self):
        with self.lock:
            ev = self.events[self.cursor:]
            self.cursor = len(self.events)
            return ev, self.done

    def finish(self, history=None):
        with self.lock:
            if self.done:
                return
            self.done = True
            self.history = history

    def images_from_history(self):
        imgs = []
        if self.history:
            for node_out in self.history.get('outputs', {}).values():
                for im in node_out.get('images', []) or []:
                    imgs.append(im)
        return imgs


# ---------------------------------------------------------------- Client
class ComfyClient:
    def __init__(self, base="http://127.0.0.1:8000"):
        self.set_base(base)
        self.client_id = str(uuid.uuid4())
        self.jobs = {}
        self.lock = threading.Lock()
        self.connected = False
        self.queue_remaining = 0
        self.last_error = None
        self._stop = False
        self._t = None

    # -- config
    def set_base(self, base):
        self.base = base.rstrip('/')
        host = self.base.split('://', 1)[-1]
        self.ws_url = ('wss://' if self.base.startswith('https') else 'ws://') + host + '/ws'

    def start(self):
        if websocket is None:
            self.last_error = '未安装 websocket-client'
            return
        if self._t and self._t.is_alive():
            return
        self._stop = False
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def stop(self):
        self._stop = True

    def _loop(self):
        while not self._stop:
            try:
                ws = websocket.WebSocketApp(
                    self.ws_url + '?clientId=' + self.client_id,
                    on_open=lambda w: self._open(),
                    on_message=lambda w, m: self._msg(m),
                    on_close=lambda w, c, m: self._close(),
                    on_error=lambda w, e: self._err(e),
                )
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                self._err(e)
            time.sleep(2)

    def _open(self):
        self.connected = True
        self.last_error = None

    def _close(self):
        self.connected = False

    def _err(self, e):
        self.connected = False
        self.last_error = str(e)

    # -- ws dispatch
    def _msg(self, m):
        if isinstance(m, (bytes, bytearray)):
            return  # 预览帧，忽略
        try:
            d = json.loads(m)
        except Exception:
            return
        t = d.get('type')
        data = d.get('data') or {}
        if t == 'status':
            q = (((data.get('status') or {}).get('exec_info') or {}).get('queue_remaining'))
            if q is not None:
                self.queue_remaining = q
            return
        pid = data.get('prompt_id') or d.get('prompt_id')
        job = self.jobs.get(pid) if pid else None
        if t == 'progress':
            if job:
                job.emit({'type': 'progress', 'value': data.get('value', 0),
                          'max': data.get('max', 0), 'node': data.get('node')})
        elif t == 'executing':
            if job:
                if data.get('node') is None:
                    job.emit({'type': 'executing_done'})
                else:
                    job.emit({'type': 'node', 'node': data.get('node')})
        elif t == 'executed':
            out = data.get('output') or {}
            for im in (out.get('images') or []):
                if job:
                    job.emit({'type': 'image', 'image': im})
        elif t == 'execution_start':
            if job:
                job.emit({'type': 'start'})
        elif t == 'execution_cached':
            if job:
                job.emit({'type': 'cached'})
        elif t == 'execution_error':
            msg = data.get('exception_message') or data.get('exception_type') or 'execution error'
            if job:
                job.error = str(msg)
                job.emit({'type': 'error', 'message': str(msg)})
                job.finish()
        elif t == 'execution_success':
            if job:
                job.emit({'type': 'success'})

    # -- http helpers
    def _get(self, path, timeout=30):
        req = urllib.request.Request(self.base + path)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def _post(self, path, obj, timeout=60):
        body = json.dumps(obj).encode('utf-8')
        req = urllib.request.Request(self.base + path, data=body,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read())
            except Exception:
                raise

    def ping(self):
        try:
            raw = self._get('/system_stats', timeout=5)
            d = json.loads(raw)
            dev = (d.get('devices') or [{}])[0]
            return True, {'version': (d.get('system') or {}).get('comfyui_version'),
                          'device': dev.get('name'), 'vram_free': dev.get('vram_free')}
        except Exception as e:
            return False, {'error': str(e)}

    def object_info(self, node=None):
        path = '/object_info' + (('/' + node) if node else '')
        return json.loads(self._get(path, timeout=60))

    def models(self, folder):
        try:
            d = json.loads(self._get('/models/' + folder, timeout=20))
            if isinstance(d, dict):
                return d.get('value', []) or []
            if isinstance(d, list):
                return d
            return []
        except Exception:
            return []

    def loader_enum(self, loader, field):
        """从 object_info 拿某个加载器的可选项（兜底，最可靠）"""
        try:
            d = self.object_info(loader)[loader]['input']['required'][field][0]
            return d if isinstance(d, list) else []
        except Exception:
            return []

    def queue_prompt(self, workflow):
        d = self._post('/prompt', {'prompt': workflow, 'client_id': self.client_id})
        pid = d.get('prompt_id')
        if not pid:
            # 校验失败：返回 node_errors
            raise WorkflowError(d)
        job = Job(pid)
        with self.lock:
            self.jobs[pid] = job
        return pid, job

    def get_history(self, prompt_id):
        try:
            d = json.loads(self._get('/history/' + prompt_id, timeout=20))
            return d.get(prompt_id)
        except Exception:
            return None

    def view_url(self, im):
        q = urllib.parse.urlencode({'filename': im.get('filename'),
                                    'subfolder': im.get('subfolder', ''),
                                    'type': im.get('type', 'output')})
        return '/view?' + q

    def get_image(self, im):
        q = urllib.parse.urlencode({'filename': im.get('filename'),
                                    'subfolder': im.get('subfolder', ''),
                                    'type': im.get('type', 'output')})
        return self._get('/view?' + q, timeout=120)

    def upload_image(self, filename, data):
        boundary = '----aigen' + uuid.uuid4().hex
        q = urllib.parse.urlencode({'type': 'input', 'overwrite': 'true'})
        parts = []
        parts.append(('--' + boundary + '\r\n').encode())
        parts.append(('Content-Disposition: form-data; name="image"; filename="%s"\r\n' % filename).encode())
        parts.append(b'Content-Type: application/octet-stream\r\n\r\n')
        parts.append(data)
        parts.append(('\r\n--' + boundary + '--\r\n').encode())
        body = b''.join(parts)
        req = urllib.request.Request(self.base + '/upload/image?' + q, data=body,
                                     headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())


class WorkflowError(Exception):
    def __init__(self, resp):
        self.resp = resp
        err = (resp or {}).get('error') or {}
        node_errors = (resp or {}).get('node_errors') or {}
        msg = err.get('message') or '工作流校验失败'
        detail = ''
        for nid, ne in list(node_errors.items())[:4]:
            for e in (ne.get('errors') or []):
                detail += f"\n节点{nid}: {e.get('message')} {e.get('details')}"
        super().__init__(msg + detail)


# ---------------------------------------------------------------- 工作流构建
DEF_NEG = "worst quality, low quality, blurry, jpeg artifacts, watermark, text, signature"

ZIMAGE_UNET = "z_image_turbo_bf16.safetensors"
ZIMAGE_CLIP = "qwen_3_4b.safetensors"
ZIMAGE_VAE = "ae.safetensors"
ANIMA_UNET = "anima-base-v1.0.safetensors"
ANIMA_CLIP = "qwen_3_06b_base.safetensors"
ANIMA_VAE = "qwen_image_vae.safetensors"


def _lora_chain(nodes, nid, model_ref, clip_ref, loras, model_only=False):
    """把 loras 串成链，返回 (model_ref, clip_ref, nid)"""
    for l in loras or []:
        lid = str(nid)
        nid += 1
        if model_only:
            nodes[lid] = {'class_type': 'LoraLoaderModelOnly',
                          'inputs': {'model': model_ref, 'lora_name': l['name'],
                                     'strength_model': float(l.get('strength', 1.0))}}
            model_ref = [lid, 0]
        else:
            nodes[lid] = {'class_type': 'LoraLoader',
                          'inputs': {'model': model_ref, 'clip': clip_ref,
                                     'lora_name': l['name'],
                                     'strength_model': float(l.get('strength', 1.0)),
                                     'strength_clip': float(l.get('strength_clip', l.get('strength', 1.0)))}}
            model_ref = [lid, 0]
            clip_ref = [lid, 1]
    return model_ref, clip_ref, nid


def build_workflow(spec):
    """spec 字段:
    model_type: checkpoint|z_image|anima
    ckpt / unet, clip, vae : 模型名（unet 类用）
    loras: [{name, strength, strength_clip}]
    prompt, negative, width, height, steps, cfg, sampler, scheduler, seed, batch, denoise
    input_image: 图生图时的输入图文件名（可选）
    """
    mt = spec.get('model_type', 'checkpoint')
    nodes = {}
    nid = 1

    def add(cls, inputs):
        nonlocal nid
        nodes[str(nid)] = {'class_type': cls, 'inputs': inputs}
        k = str(nid)
        nid += 1
        return k

    positive = spec.get('prompt', '')
    negative = spec.get('negative', DEF_NEG)
    width = int(spec.get('width', 512))
    height = int(spec.get('height', 512))
    steps = int(spec.get('steps', 25))
    cfg = float(spec.get('cfg', 7.0))
    sampler = spec.get('sampler', 'euler')
    scheduler = spec.get('scheduler', 'normal')
    seed = int(spec.get('seed', -1))
    batch = max(1, int(spec.get('batch', 1)))
    denoise = float(spec.get('denoise', 1.0))
    src = spec.get('input_image')

    if mt == 'checkpoint':
        ck = add('CheckpointLoaderSimple', {'ckpt_name': spec['ckpt']})
        model_ref, clip_ref = [ck, 0], [ck, 1]
        vae_ref = [ck, 2]
        model_ref, clip_ref, nid = _lora_chain(nodes, nid, model_ref, clip_ref, spec.get('loras'), False)
        pos = add('CLIPTextEncode', {'text': positive, 'clip': clip_ref})
        neg = add('CLIPTextEncode', {'text': negative, 'clip': clip_ref})
        if src:
            img = add('LoadImage', {'image': src})
            lat = add('VAEEncode', {'pixels': [img, 0], 'vae': vae_ref})
            denoise = min(max(denoise, 0.01), 1.0)
        else:
            lat = add('EmptyLatentImage', {'width': width, 'height': height, 'batch_size': batch})
            denoise = 1.0
        ks = add('KSampler', {'model': model_ref, 'seed': seed, 'steps': steps, 'cfg': cfg,
                              'sampler_name': sampler, 'scheduler': scheduler,
                              'positive': [pos, 0], 'negative': [neg, 0],
                              'latent_image': [lat, 0], 'denoise': denoise})
        dec = add('VAEDecode', {'samples': [ks, 0], 'vae': vae_ref})

    elif mt == 'z_image':
        unet = add('UNETLoader', {'unet_name': spec.get('unet', ZIMAGE_UNET), 'weight_dtype': 'default'})
        clip = add('CLIPLoader', {'clip_name': spec.get('clip', ZIMAGE_CLIP), 'type': 'lumina2', 'device': 'default'})
        vae = add('VAELoader', {'vae_name': spec.get('vae', ZIMAGE_VAE)})
        model_ref = [unet, 0]
        model_ref, _, nid = _lora_chain(nodes, nid, model_ref, None, spec.get('loras'), True)
        pos = add('CLIPTextEncode', {'text': positive, 'clip': [clip, 0]})
        neg = add('ConditioningZeroOut', {'conditioning': [pos, 0]})
        ms = add('ModelSamplingAuraFlow', {'model': model_ref, 'shift': 3.0})
        if src:
            img = add('LoadImage', {'image': src})
            lat = add('VAEEncode', {'pixels': [img, 0], 'vae': [vae, 0]})
            denoise = min(max(denoise, 0.01), 1.0)
        else:
            lat = add('EmptySD3LatentImage', {'width': width, 'height': height, 'batch_size': batch})
            denoise = 1.0
        ks = add('KSampler', {'model': [ms, 0], 'seed': seed, 'steps': steps or 8, 'cfg': cfg or 1.0,
                              'sampler_name': sampler or 'res_multistep', 'scheduler': scheduler or 'simple',
                              'positive': [pos, 0], 'negative': [neg, 0],
                              'latent_image': [lat, 0], 'denoise': denoise})
        dec = add('VAEDecode', {'samples': [ks, 0], 'vae': [vae, 0]})

    elif mt == 'anima':
        unet = add('UNETLoader', {'unet_name': spec.get('unet', ANIMA_UNET), 'weight_dtype': 'default'})
        clip = add('CLIPLoader', {'clip_name': spec.get('clip', ANIMA_CLIP), 'type': 'stable_diffusion', 'device': 'default'})
        vae = add('VAELoader', {'vae_name': spec.get('vae', ANIMA_VAE)})
        model_ref = [unet, 0]
        model_ref, _, nid = _lora_chain(nodes, nid, model_ref, None, spec.get('loras'), True)
        pos = add('CLIPTextEncode', {'text': positive, 'clip': [clip, 0]})
        neg = add('CLIPTextEncode', {'text': negative, 'clip': [clip, 0]})
        if src:
            img = add('LoadImage', {'image': src})
            lat = add('VAEEncode', {'pixels': [img, 0], 'vae': [vae, 0]})
            denoise = min(max(denoise, 0.01), 1.0)
        else:
            lat = add('EmptyLatentImage', {'width': width, 'height': height, 'batch_size': batch})
            denoise = 1.0
        ks = add('KSampler', {'model': model_ref, 'seed': seed, 'steps': steps or 30, 'cfg': cfg or 4.0,
                              'sampler_name': sampler or 'euler', 'scheduler': scheduler or 'simple',
                              'positive': [pos, 0], 'negative': [neg, 0],
                              'latent_image': [lat, 0], 'denoise': denoise})
        dec = add('VAEDecode', {'samples': [ks, 0], 'vae': [vae, 0]})
    else:
        raise ValueError('未知模型类型: ' + str(mt))

    add('SaveImage', {'images': [dec, 0], 'filename_prefix': 'AIGen'})
    return nodes
