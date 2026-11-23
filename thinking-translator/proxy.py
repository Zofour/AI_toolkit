# -*- coding: utf-8 -*-
"""OpenAI 兼容反向代理：把上游返回的「思考过程(reasoning)」实时翻译成中文，再流式回给 Chatbox。
- 你只需把 Chatbox 的自定义服务商的 API Host 指向本代理；
- 代理会把请求原样转发到 UPSTREAM_BASE（你的真实服务商），并把返回里的
  reasoning_content / reasoning 字段逐句翻译后再下发。
- 正文 content 默认原样透传（可用 TRANSLATE_CONTENT=1 也翻译）。
环境变量：
  UPSTREAM_BASE     你的真实服务商 base（含 /v1），如 https://api.deepseek.com/v1
  PORT              监听端口，默认 8788
  MODEL_DIR         本地翻译模型目录
  TRANSLATE_CONTENT 置 1 时连正文也翻译（默认 0）
  DEBUG             置 1 打印日志
"""
import os, json, asyncio
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, Response, JSONResponse

from translator import Translator, StreamTranslator

UPSTREAM_BASE = os.environ.get("UPSTREAM_BASE", "").rstrip("/")
PORT = int(os.environ.get("PORT", "8788"))
MODEL_DIR = os.environ.get("MODEL_DIR", os.path.join(os.path.dirname(__file__), "models", "Qwen2.5-1.5B-Instruct"))
TRANSLATE_CONTENT = os.environ.get("TRANSLATE_CONTENT", "0") == "1"
DEBUG = os.environ.get("DEBUG", "0") == "1"
REASON_KEYS = ("reasoning_content", "reasoning")

app = FastAPI()
_tr = None


def log(*a):
    if DEBUG:
        print("[proxy]", *a, flush=True)


class _NullTranslator:  # 模型未就绪时优雅降级为原样输出
    def translate(self, t):
        return t


def get_translator():
    global _tr
    if _tr is None:
        try:
            if TRANSLATOR_BACKEND == "openai":
                print(f"[proxy] translator backend = openai ({TRANSLATOR_API_BASE} / {TRANSLATOR_API_MODEL})", flush=True)
                _tr = OpenAITranslator(TRANSLATOR_API_BASE, TRANSLATOR_API_MODEL)
            else:
                print(f"[proxy] loading local translator from {MODEL_DIR} ...", flush=True)
                _tr = Translator(MODEL_DIR)
            print("[proxy] translator ready", flush=True)
        except Exception as e:
            print(f"[proxy] translator load failed ({e}); fallback to passthrough", flush=True)
            _tr = _NullTranslator()
    return _tr


def sse(obj) -> bytes:
    return ("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8")


@app.get("/")
async def health():
    return {"ok": True, "upstream": UPSTREAM_BASE, "model_dir": MODEL_DIR,
            "translate_content": TRANSLATE_CONTENT}


async def _translate_key(stream: StreamTranslator, loop, delta, key):
    txt = delta.pop(key, None)
    if txt is None:
        return None
    if txt == "":
        return ""
    res = await loop.run_in_executor(None, stream.feed, txt)
    return res


@app.api_route("/{full_path:path}", methods=["POST", "GET"])
async def proxy(request: Request, full_path: str):
    if not UPSTREAM_BASE:
        return JSONResponse({"error": "UPSTREAM_BASE 未设置"}, status_code=500)
    body = await request.body()
    fwd_headers = {}
    for k, v in request.headers.items():
        if k.lower() in ("authorization", "content-type", "accept", "x-api-key", "api-key"):
            fwd_headers[k] = v
    tail = full_path
    if UPSTREAM_BASE.endswith("/v1") and tail.startswith("v1/"):
        tail = tail[3:]  # 避免拼成 /v1/v1/...
    url = f"{UPSTREAM_BASE}/{tail}"
    log("->", url)

    client = httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0))
    req = client.build_request(request.method, url, content=body, headers=fwd_headers,
                               params=dict(request.query_params))
    upstream = await client.send(req, stream=True)

    is_stream = b'"stream":true' in body.replace(b" ", b"").lower() or \
                b'"stream": true' in body.lower()

    if not is_stream:
        raw = await upstream.aread()
        await upstream.aclose(); await client.aclose()
        try:
            data = json.loads(raw)
            tr = get_translator()
            for ch in (data.get("choices") or []):
                msg = ch.get("message") or ch.get("delta") or {}
                for k in REASON_KEYS:
                    if isinstance(msg.get(k), str) and msg[k]:
                        msg[k] = tr.translate(msg[k])
                if TRANSLATE_CONTENT and isinstance(msg.get("content"), str):
                    msg["content"] = tr.translate(msg["content"])
            return JSONResponse(data)
        except Exception as e:
            log("non-stream parse fail", e)
            return Response(raw, media_type=upstream.headers.get("content-type", "application/json"))

    loop = asyncio.get_event_loop()
    tr = get_translator()
    st = StreamTranslator(tr)
    cst = StreamTranslator(tr) if TRANSLATE_CONTENT else None
    template = {"id": "chatcmpl-proxy", "object": "chat.completion.chunk", "model": ""}

    async def gen():
        try:
            async for line in upstream.aiter_lines():
                if line == "":
                    continue
                if not line.startswith("data:"):
                    yield (line + "\n\n").encode("utf-8")
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    rem = st.flush()
                    if cst:
                        rem2 = cst.flush()
                    else:
                        rem2 = ""
                    tail_delta = {}
                    if rem:
                        tail_delta["reasoning_content"] = rem
                    if rem2:
                        tail_delta["content"] = rem2
                    if tail_delta:
                        obj = dict(template)
                        obj["choices"] = [{"index": 0, "delta": tail_delta, "finish_reason": None}]
                        yield sse(obj)
                    yield b"data: [DONE]\n\n"
                    break
                try:
                    obj = json.loads(payload)
                except Exception:
                    yield (line + "\n\n").encode("utf-8")
                    continue
                for kk in ("id", "model", "object", "created"):
                    if kk in obj:
                        template[kk] = obj[kk]
                choices = obj.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or choices[0].get("message") or {}
                    emitted = False
                    for k in REASON_KEYS:
                        if k in delta:
                            r = await _translate_key(st, loop, delta, k)
                            if r:
                                delta[k] = r
                                emitted = True
                    if TRANSLATE_CONTENT and isinstance(delta.get("content"), str) and delta["content"]:
                        c = await loop.run_in_executor(None, cst.feed, delta.pop("content"))
                        if c:
                            delta["content"] = c
                            emitted = True
                    if not emitted and not delta and choices[0].get("finish_reason") is None:
                        continue  # 纯缓冲，不下发空包
                yield sse(obj)
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    import uvicorn
    get_translator()
    print(f"[proxy] listening on http://127.0.0.1:{PORT}  -> upstream {UPSTREAM_BASE}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
