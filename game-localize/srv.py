# -*- coding: utf-8 -*-
"""
本机离线翻译服务器 —— 对接 XUnity.AutoTranslator 的 CustomTranslate 接口。

协议（CustomTranslate.dll 内置模板）：
    GET  {Url}?from={ja}&to={zh}&text={urlencoded}
    响应体 = 纯文本译文

引擎：
  --engine qwen   自带 Qwen2.5-1.5B-Instruct（默认，完全离线，不依赖 Ollama）
  --engine ollama 本机 Ollama / LM Studio（OpenAI 兼容）

特性：
  * 富文本标签 <color=#xxx> / &lt;...&gt; / {0} 占位符先挖空后回填，不会被翻译破坏
  * 译文落盘缓存（cache.jsonl），重复文本 0 延迟
  * 翻译失败/空 → 原样返回，绝不把游戏文本搞乱
"""
import argparse, html, json, os, re, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(HERE, "cache.jsonl")
LOG_PATH = os.path.join(HERE, "server.log")

SYS_PROMPT = (
    "你是日语→简体中文的游戏本地化译者，负责成人向经营/剧情游戏的台词。\n"
    "要求：\n"
    "1) 只输出简体中文译文本身。不要解释、不要加引号、不要写“这句话的意思是”，不要复述日文；\n"
    "2) 忠实原意，保留语气与人称（私→我，お前→你/你这家伙），口语自然；\n"
    "3) 【0】【1】这类占位标记和换行原样保留；英文专有名词（stats、wall sex 等）不译；\n"
    "4) 若原文已是中文，原样返回。\n"
    "示例：\n"
    "日：ガイドちゃんといいます。よろしくお願いします。\n"
    "中：我叫小向导，请多指教。\n"
    "日：この部屋には「wall sex」という行為が割り当てられています。\n"
    "中：这个房间分配的行为是「wall sex」。\n"
    "日：お客様の頭上にある統計から、何を望んでいるかわかります。\n"
    "中：看客人头上的状态栏，就知道他想要什么。"
)

# 短词条 / 按钮 / 标题：只要名词短语，不要句子
SYS_SHORT = (
    "你是游戏界面的日语→简体中文翻译。用户给你的是按钮、菜单项或短标题，"
    "只需译成简洁的中文词条（名词短语），不要变成句子，不要解释。只输出译文。\n"
    "示例：\n"
    "日：はじめから\n中：开始新游戏\n"
    "日：クレジット\n中：制作人员\n"
    "日：終了\n中：退出\n"
    "日：設定\n中：设置\n"
    "日：お客様\n中：客人\n"
    "日：所持金\n中：持有金钱"
)

# 术语表：完全匹配时直接返回，不走模型
def _load_glossary():
    p = os.path.join(HERE, "glossary.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"glossary not loaded: {e!r}")
        return {}


_log_lock = threading.Lock()
def log(msg):
    line = time.strftime("[%H:%M:%S] ") + msg
    with _log_lock:
        print(line, flush=True)
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


# ---------------- 占位符保护 ----------------
PROTECT_PATTERNS = [
    re.compile(r"&lt;.*?&gt;"),            # XUnity 转义后的富文本
    re.compile(r"<[^<>\n]{1,80}>"),         # 原生富文本标签
    re.compile(r"\[[a-zA-Z_]{2,20}\]"),     # [color] 之类 BBCode
    re.compile(r"\{[^{}\n]{0,20}\}"),      # {0} 变量
    re.compile(r"%[sdif]", re.I),           # printf
    re.compile(r"\\n|\r"),                  # 转义换行
]

def protect(text):
    slots = []
    def repl(m):
        slots.append(m.group(0))
        return f"【{len(slots)-1}】"
    out = text
    for p in PROTECT_PATTERNS:
        out = p.sub(repl, out)
    return out, slots

def restore(text, slots):
    def repl(m):
        i = int(m.group(1))
        return slots[i] if 0 <= i < len(slots) else m.group(0)
    return re.sub(r"【(\d+)】", repl, text)


def cleanup(src, out):
    """把模型的常见多余包装去掉。"""
    s = (out or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
    s = re.sub(r"\n?```$", "", s).strip()
    for pref in ("译文：", "译文:", "翻译：", "翻译:", "中文：", "中文:", "中：", "中:", "中译：", "汉语：", "简体中文：", "日语：原文"):
        if s.startswith(pref):
            s = s[len(pref):].strip()
    s = s.strip().strip('“”"').strip()
    # 模型偶尔会复述原文
    if s == src:
        return s
    return s


class Engine:
    def __init__(self, kind, model_dir, device, ollama_base, ollama_model):
        self.kind = kind
        self.lock = threading.Lock()
        self.backend = None
        if kind == "ollama":
            import requests
            self._req = requests
            self.base, self.model = ollama_base.rstrip("/"), ollama_model
            log(f"engine=ollama base={self.base} model={self.model}")
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        t0 = time.time()
        self._t = torch
        self.tok = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
        if self.tok.pad_token_id is None:
            self.tok.pad_token = self.tok.eos_token
        self.tok.padding_side = "left"
        self.model = AutoModelForCausalLM.from_pretrained(
            model_dir, dtype=torch.float16, local_files_only=True).to(device).eval()
        self.device = device
        log(f"engine=qwen model={model_dir} device={device} loaded in {time.time()-t0:.1f}s")

    def _qwen(self, texts, max_new, sys_prompt=SYS_PROMPT):
        torch = self._t
        idl = []
        for t in texts:
            msgs = [{"role": "system", "content": sys_prompt},
                    {"role": "user", "content": t}]
            ids = self.tok.apply_chat_template(msgs, add_generation_prompt=True,
                                               tokenize=True, return_dict=False)
            if ids and isinstance(ids[0], list):
                ids = ids[0]
            idl.append(list(ids))
        mx = max(len(x) for x in idl)
        pad = self.tok.pad_token_id
        rows = [[pad] * (mx - len(x)) + x for x in idl]
        ii = torch.tensor(rows, device=self.device)
        am = (ii != pad).long()
        with torch.inference_mode():
            g = self.model.generate(ii, attention_mask=am, max_new_tokens=max_new,
                                    do_sample=False, num_beams=1, pad_token_id=pad)
        g = g[:, mx:]
        return [o.strip() for o in self.tok.batch_decode(g, skip_special_tokens=True)]

    def _ollama(self, text, max_new, sys_prompt=SYS_PROMPT):
        payload = {"model": self.model, "temperature": 0, "stream": False,
                   "max_tokens": max_new,
                   "messages": [{"role": "system", "content": sys_prompt},
                                {"role": "user", "content": text}]}
        r = self._req.post(f"{self.base}/chat/completions", json=payload,
                           headers={"Authorization": "Bearer ollama"}, timeout=180)
        r.raise_for_status()
        return (r.json()["choices"][0]["message"].get("content") or "").strip()

    def translate_many(self, texts, sys_prompt=SYS_PROMPT, max_new=256):
        with self.lock:
            if self.kind == "ollama":
                return [self._ollama(t, 512, sys_prompt) for t in texts]
            return self._qwen(texts, max_new, sys_prompt)


# ---------------- 缓存 ----------------
class Cache:
    def __init__(self, path):
        self.path = path
        self.d = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        o = json.loads(line)
                        self.d[o["s"]] = o["t"]
                    except Exception:
                        pass
        log(f"cache loaded: {len(self.d)} entries")

    def append(self, s, t):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"s": s, "t": t}, ensure_ascii=False) + "\n")


ENGINE = None
CACHE = None
GLOSSARY = {}


def is_short_label(t):
    """按钮/菜单项/标题：短、无句末标点。"""
    s = t.strip()
    return len(s) <= 14 and not re.search(r"[。！？!?…\n]", s)


def translate_one(text):
    if not text or not text.strip():
        return text
    key = text.strip()
    if key in GLOSSARY:
        return GLOSSARY[key]
    if key in CACHE.d:
        return CACHE.d[key]
    masked, slots = protect(text)
    short = is_short_label(masked)
    sys_p = SYS_SHORT if short else SYS_PROMPT
    max_new = 48 if short else min(768, max(96, int(len(masked) * 3) + 32))
    out = ""
    try:
        raw = cleanup(text, ENGINE.translate_many([masked], sys_p, max_new)[0])
        if not re.search(r"[\u4e00-\u9fff]", raw) and re.search(r"[\u3040-\u30ff]", text):
            # 模型跑飞去翻译成英文了，重试一次并强制中文
            raw = cleanup(text, ENGINE.translate_many(
                ["把下面这句日文翻译成简体中文，只输出中文译文：\n" + masked],
                SYS_PROMPT, max_new)[0])
        got = len(re.findall(r"【(\d+)】", raw))
        out = restore(raw, slots)
        # 占位符/标签必须完整还原，否则宁可保留原文，也不要把标签吃掉
        if not out.strip() or got != len(slots) or re.search(r"【\d+】", out):
            out = text
    except Exception as e:
        log(f"ERR {e!r} :: {text[:60]}")
        out = text
    CACHE.d[key] = out
    CACHE.append(key, out)
    log(f"{key[:50]!r} -> {out[:50]!r}")
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        pass

    def _send(self, code, body, ctype="text/plain; charset=utf-8"):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query, keep_blank_values=True)
        if u.path.rstrip("/") in ("/health", "/ping"):
            return self._send(200, "ok")
        text = (q.get("text") or q.get("q") or [""])[0]
        if not text:
            return self._send(200, "ok")
        return self._send(200, translate_one(text))

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        ctype = (self.headers.get("Content-Type") or "").lower()
        text = ""
        try:
            if "json" in ctype:
                o = json.loads(raw.decode("utf-8"))
                text = o.get("text") or o.get("q") or ""
            else:
                q = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                text = (q.get("text") or q.get("q") or [""])[0]
        except Exception:
            pass
        if not text:
            text = (parse_qs(u.query).get("text") or [""])[0]
        return self._send(200, translate_one(text) if text else "ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--engine", default=os.environ.get("TL_ENGINE", "qwen"),
                    choices=["qwen", "ollama"])
    ap.add_argument("--model-dir", default=os.environ.get(
        "TL_MODEL_DIR", r"C:\chatbox_temp\thinking-translator\models\Qwen2.5-1.5B-Instruct"))
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--ollama-base", default="http://127.0.0.1:11434/v1")
    ap.add_argument("--ollama-model", default="gemma3:12b")
    a = ap.parse_args()

    global ENGINE, CACHE, GLOSSARY
    CACHE = Cache(CACHE_PATH)
    GLOSSARY = _load_glossary()
    log(f"glossary loaded: {len(GLOSSARY)} entries")
    ENGINE = Engine(a.engine, a.model_dir, a.device, a.ollama_base, a.ollama_model)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    log(f"READY http://{a.host}:{a.port}/translate")
    print("=" * 60, flush=True)
    print(f"  翻译服务已就绪: http://{a.host}:{a.port}/translate", flush=True)
    print("  打开游戏即可，Ctrl+C 结束", flush=True)
    print("=" * 60, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
