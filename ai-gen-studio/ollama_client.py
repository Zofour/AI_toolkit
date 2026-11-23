# -*- coding: utf-8 -*-
"""Ollama 客户端：模型能力探测、提示词生成（流式）、模式2 图像评判"""
import base64
import json
import re
import urllib.request


class OllamaClient:
    def __init__(self, base="http://127.0.0.1:11434"):
        self.base = base.rstrip('/')
        self._caps = {}

    # ---------------- 基础
    def _post(self, path, obj, timeout=1800, stream=False):
        body = json.dumps(obj).encode('utf-8')
        req = urllib.request.Request(self.base + path, data=body,
                                     headers={'Content-Type': 'application/json'})
        return urllib.request.urlopen(req, timeout=timeout)

    def ping(self):
        try:
            with urllib.request.urlopen(self.base + '/api/tags', timeout=5) as r:
                json.loads(r.read())
            return True
        except Exception as e:
            return False

    def refresh(self):
        """清掉能力缓存，下次扫描重新探测（新增模型后调用）"""
        self._caps.clear()

    def list_models(self):
        with urllib.request.urlopen(self.base + '/api/tags', timeout=15) as r:
            d = json.loads(r.read())
        out = []
        for m in d.get('models', []):
            name = m.get('name')
            caps = self.capabilities(name)
            out.append({'name': name, 'size': m.get('size', 0), 'caps': caps,
                        'vision': 'vision' in caps, 'embedding': 'embedding' in caps})
        out.sort(key=lambda x: x['name'])
        return out

    def capabilities(self, model):
        if model in self._caps:
            return self._caps[model]
        caps = []
        try:
            with self._post('/api/show', {'model': model}, timeout=30) as r:
                caps = json.loads(r.read()).get('capabilities', []) or []
        except Exception:
            caps = []
        self._caps[model] = caps
        return caps

    # ---------------- 流式对话
    def chat_stream(self, model, messages):
        """yield (kind, text) ; kind in {thinking, content}"""
        r = self._post('/api/chat', {'model': model, 'messages': messages, 'stream': True},
                       timeout=3600, stream=True)
        for raw in r:
            line = raw.decode('utf-8', 'ignore').strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            msg = d.get('message') or {}
            if msg.get('thinking'):
                yield 'thinking', msg['thinking']
            if msg.get('content'):
                yield 'content', msg['content']
            if d.get('done'):
                break

    def chat(self, model, messages, timeout=3600):
        with self._post('/api/chat', {'model': model, 'messages': messages, 'stream': False},
                        timeout=timeout) as r:
            d = json.loads(r.read())
        return d.get('message') or {}

    # ---------------- 提示词生成
    def gen_prompts_stream(self, model, requirement, n, image_model_hint='', style='tags'):
        """style: tags（词,词,词）/ sentence（描述句）/ auto（按生图模型类型）"""
        head = (
            "You are a professional AI image prompt engineer. "
            "The user writes an image request in Chinese. "
            f"Produce exactly {n} DIFFERENT English prompts that each fully satisfy the request. "
        )
        if style == 'sentence':
            body = (
                "Write each prompt as ONE fluent, descriptive natural-language sentence or short paragraph "
                "covering subject, action, environment, lighting, composition, mood and quality words. "
                "Vary the style and angle between prompts so the user can choose. "
            )
        elif style == 'auto':
            if 'z_image' in image_model_hint or 'anima' in image_model_hint:
                body = (
                    "Write each prompt as fluent natural-language descriptive sentences "
                    "(subject, action, environment, lighting, composition, quality). "
                )
            else:
                body = (
                    "Each prompt MUST be a COMMA-SEPARATED list of short English tags / descriptive words "
                    "(danbooru style, adjectives and nouns), no full sentences, no periods. "
                )
        else:  # tags
            body = (
                "Each prompt MUST be a COMMA-SEPARATED list of short English tags / descriptive words "
                "(adjective or noun phrases), danbooru style. "
                "Example format: '1girl, solo, long silver hair, red eyes, looking at viewer, "
                "cyberpunk city, neon lights, rain, night, cinematic lighting, masterpiece, best quality'. "
                "DO NOT write full sentences. DO NOT use periods. "
                "Put the main subject first and quality tags last. "
                "Vary the tags and approach between prompts so the user can choose. "
            )
        sys = (head + body
               + "Use English only. Output ONLY a JSON array of strings, no markdown, no explanation.")
        user = f"图片需求: {requirement}\n请输出 {n} 条英文提示词的 JSON 数组。"
        msgs = [{'role': 'system', 'content': sys}, {'role': 'user', 'content': user}]
        buf = []
        for kind, text in self.chat_stream(model, msgs):
            yield kind, text
            if kind == 'content':
                buf.append(text)
        yield 'result', ''.join(buf)

    # ---------------- 模式2 评判
    def judge(self, model, requirement, prompt_used, image_bytes):
        sys = (
            "You are a strict image quality inspector for an AI image generation loop. "
            "You will receive the user's ORIGINAL requirement, the PROMPT used to generate the image, "
            "and the generated image itself. Decide whether the image satisfies the original requirement. "
            "Reply with ONLY JSON: "
            '{"ok": true|false, "reason": "<short reason in Chinese>", '
            '"new_prompt": "<if not ok, a single improved English prompt to try next; else empty>"}'
        )
        b64 = base64.b64encode(image_bytes).decode('ascii')
        user = (f"原始需求: {requirement}\n"
                f"生成所用提示词: {prompt_used}\n"
                "请判断这张图片是否满足原始需求，并按 JSON 格式回复。")
        msgs = [{'role': 'system', 'content': sys},
                {'role': 'user', 'content': user, 'images': [b64]}]
        msg = self.chat(model, msgs)
        return parse_judge(msg.get('content', ''))


def parse_json_array(text):
    """从模型输出中尽力解析字符串数组"""
    if not text:
        return []
    t = text.strip()
    # 去掉 ```json 围栏
    t = re.sub(r'^```[a-zA-Z]*\s*', '', t)
    t = re.sub(r'\s*```$', '', t).strip()
    try:
        arr = json.loads(t)
        if isinstance(arr, list):
            return [str(x).strip() for x in arr if str(x).strip()]
        if isinstance(arr, dict) and 'prompts' in arr:
            return [str(x).strip() for x in arr['prompts'] if str(x).strip()]
    except Exception:
        pass
    # 退回：抓取最外层 [ ... ]
    m = re.search(r'\[.*\]', t, re.S)
    if m:
        try:
            arr = json.loads(m.group(0))
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()]
        except Exception:
            pass
    # 再退回：按行拆，去掉编号/引号/短横线
    lines = []
    for ln in t.splitlines():
        ln = ln.strip().strip(',').strip('"').strip()
        ln = re.sub(r'^\s*[-*\d]+[\.\):\-]\s*', '', ln)
        if ln and not ln.startswith('[') and not ln.startswith('{'):
            lines.append(ln)
    return lines


def parse_judge(text):
    if not text:
        return {'ok': False, 'reason': '模型无输出', 'new_prompt': '', 'raw': text}
    t = re.sub(r'^```[a-zA-Z]*\s*', '', text.strip())
    t = re.sub(r'\s*```$', '', t).strip()
    obj = None
    try:
        obj = json.loads(t)
    except Exception:
        m = re.search(r'\{.*\}', t, re.S)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                obj = None
    if isinstance(obj, dict):
        ok = obj.get('ok')
        if isinstance(ok, str):
            ok = ok.strip().lower() in ('true', 'yes', '1', '是')
        return {'ok': bool(ok), 'reason': str(obj.get('reason', '') or ''),
                'new_prompt': str(obj.get('new_prompt', '') or ''), 'raw': text}
    low = t.lower()
    ok = ('"ok": true' in low.replace(' ', '')) or ('true' in low and 'false' not in low)
    return {'ok': ok, 'reason': t[:200], 'new_prompt': '', 'raw': text}
