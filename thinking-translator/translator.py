# -*- coding: utf-8 -*-
"""本地翻译引擎：把英文（技术性推理文本）翻译成简体中文。
- 用 Qwen2.5-Instruct（BPE，无需 sentencepiece），GPU 推理。
- 代码围栏 ```...``` 内的内容原样保留，不送翻译。
- 支持批量与逐句（流式）翻译。
"""
import os, re, torch

SYS_PROMPT = (
    "你是专业的技术文档翻译引擎。把用户给出的英文翻译成简体中文。规则：\n"
    "1) 只输出译文本身，不要任何解释、前言、后缀，也不要用代码围栏把整段包起来；\n"
    "2) 保持原有 Markdown 结构与换行（列表、编号、标题照旧）；\n"
    "3) 代码、命令、变量名、函数名、类名、文件路径、URL、API 名、数字、"
    "以及数学公式（$...$、\\(...\\)、\\[...\\]）一律原样保留，不翻译、不改写；\n"
    "4) 术语准确、语气自然，符合中文技术表达；若输入已是中文则原样输出。"
)


def _strip_fence_wrap(s: str) -> str:
    s = s.strip()
    m = re.match(r"^```[a-zA-Z0-9_+-]*\s*\n(.*)\n```$", s, re.S)
    if m:
        return m.group(1).strip()
    return s


class Translator:
    def __init__(self, model_dir: str, device: str = "cuda", dtype=torch.float16,
                 max_new_tokens: int = 512):
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.tok = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
        if self.tok.pad_token_id is None:
            self.tok.pad_token = self.tok.eos_token
        self.tok.padding_side = "left"
        dt = dtype if not (device == "cpu") else torch.float32
        kw = dict(local_files_only=True)
        try:
            self.model = AutoModelForCausalLM.from_pretrained(model_dir, dtype=dt, **kw)
        except TypeError:  # 旧版 transformers
            self.model = AutoModelForCausalLM.from_pretrained(model_dir, torch_dtype=dt, **kw)
        self.model = self.model.to(device).eval()
        self.device = device
        self.max_new = max_new_tokens

    def _chat_ids(self, text: str):
        msgs = [{"role": "system", "content": SYS_PROMPT},
                {"role": "user", "content": text}]
        ids = self.tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True,
                                           return_dict=False)
        if ids and isinstance(ids[0], list):
            ids = ids[0]
        return list(ids)

    @torch.inference_mode()
    def translate_batch(self, texts, batch_size: int = 8):
        """texts: 英文句子/段落列表 -> 中文列表（长度一致）。"""
        out = []
        for i in range(0, len(texts), batch_size):
            chunk = list(texts[i:i + batch_size])
            id_lists = [self._chat_ids(t) for t in chunk]
            maxlen = max(len(x) for x in id_lists)
            pad = self.tok.pad_token_id
            rows = [[pad] * (maxlen - len(x)) + x for x in id_lists]
            input_ids = torch.tensor(rows, device=self.device)
            attn = (input_ids != pad).long()
            gen = self.model.generate(input_ids, attention_mask=attn,
                                      max_new_tokens=self.max_new, do_sample=False,
                                      num_beams=1, pad_token_id=pad)
            gen = gen[:, maxlen:]
            outs = self.tok.batch_decode(gen, skip_special_tokens=True)
            out.extend(_strip_fence_wrap(o) for o in outs)
        return out

    def translate(self, text: str) -> str:
        return self.translate_batch([text])[0]


class OpenAITranslator:
    """用本机已运行的 OpenAI 兼容服务（Ollama / LM Studio 等）当翻译引擎。
    与 Translator 接口一致（translate / translate_batch），可互换。"""
    def __init__(self, base="http://127.0.0.1:11434/v1", model="qwen3-vl:8b",
                 api_key="ollama", timeout=120):
        import requests  # 延迟导入
        self._req = requests
        self.base = base.rstrip("/")
        self.model = model
        self.key = api_key
        self.timeout = timeout

    def translate_batch(self, texts, batch_size=8):
        out = []
        for t in texts:
            payload = {
                "model": self.model, "temperature": 0, "stream": False,
                "messages": [{"role": "system", "content": SYS_PROMPT},
                             {"role": "user", "content": t}],
            }
            r = self._req.post(f"{self.base}/chat/completions", json=payload,
                               headers={"Authorization": f"Bearer {self.key}"},
                               timeout=self.timeout)
            r.raise_for_status()
            txt = r.json()["choices"][0]["message"].get("content") or ""
            out.append(_strip_fence_wrap(txt))
        return out

    def translate(self, text):
        return self.translate_batch([text])[0]


# ---------- 代码/公式感知的分段 ----------
_FENCE = re.compile(r"^\s*```")


def split_code_blocks(text: str):
    """把文本按 ``` 围栏切成 [(is_code, chunk), ...]。"""
    parts, buf, in_code = [], [], False
    for line in text.splitlines(keepends=True):
        is_fence = bool(_FENCE.match(line))
        if is_fence:
            parts.append((in_code, "".join(buf))); buf = []
            in_code = not in_code
            parts.append((True, line))  # 围栏标记本身原样
            continue
        buf.append(line)
    parts.append((in_code, "".join(buf)))
    return [(c, s) for c, s in parts if s != ""]


def has_letters(s: str) -> bool:
    return bool(re.search(r"[A-Za-z]{2,}", s))


class StreamTranslator:
    """面向流式的翻译器：喂入碎片，返回可立即下发的（已翻译/原样）文本。"""
    SENT_END = "。！？!?；;"

    def __init__(self, translator: Translator, min_flush: int = 40):
        self.t = translator
        self.buf = ""
        self.min_flush = min_flush
        self.in_code = False

    def _find_cut(self, s: str) -> int:
        nl = s.rfind("\n")
        if nl >= 0:
            return nl + 1
        if len(s) >= self.min_flush:
            for i in range(len(s) - 1, -1, -1):
                if s[i] in self.SENT_END:
                    return i + 1
        return 0

    def _proc(self, seg: str) -> str:
        # 按行处理，并跨 feed 调用保持 ``` 围栏状态，避免把代码块也翻译了
        out = []
        for line in seg.splitlines(keepends=True):
            if _FENCE.match(line):
                self.in_code = not self.in_code
                out.append(line)                 # 围栏标记原样
                continue
            if self.in_code or not has_letters(line):
                out.append(line)
            else:
                out.append(self.t.translate(line))
        return "".join(out)

    def feed(self, text: str) -> str:
        self.buf += text
        out = []
        while True:
            cut = self._find_cut(self.buf)
            if cut <= 0:
                break
            seg, self.buf = self.buf[:cut], self.buf[cut:]
            out.append(self._proc(seg))
        return "".join(out)

    def flush(self) -> str:
        if not self.buf:
            return ""
        seg, self.buf = self.buf, ""
        return self._proc(seg)
