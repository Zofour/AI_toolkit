"""Chatbox Bridge 电脑端中继：OpenAI 兼容反向代理(捕获) + REST + WebSocket 推送。"""
from __future__ import annotations

import asyncio
import json
import pathlib
import socket
import uuid

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.websockets import WebSocketState

from . import PROTOCOL_VERSION
from .blobs import BlobStore
from .cleanup import expired_keys, run_cleanup
from .config import Config, load_config
from .hub import FEATURES, CONTROL_TYPES, Client, Hub
from .images import collect as collect_images, describe as describe_image
from .notify import Notifier
from .store import Store, now_ms, session_key


# ---------------------------------------------------------------- helpers
def _is_loopback(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    return host in ("127.0.0.1", "::1", "localhost")


def _bearer(value: str | None) -> str | None:
    if not value:
        return None
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value.strip()


def _extract_text(content) -> str:
    """消息 content 可能是 str 或 [{type:text,text:...},...]（多模态）。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(p.get("text", ""))
            elif isinstance(p, str):
                parts.append(p)
        return "\n".join(parts)
    return str(content)


def _lan_ips() -> list[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    # Tailscale 网段优先放在前面
    return sorted(ips, key=lambda x: (not x.startswith("100."), x))


# ---------------------------------------------------------------- app factory
def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    app = FastAPI(title="Chatbox Bridge Relay", version="0.1.0")
    store = Store(cfg["data_dir"], cfg["session_buffer_events"])
    hub = Hub()
    notifier = Notifier(cfg["ntfy_url"], cfg["ntfy_topic"])
    blobstore = BlobStore(str(pathlib.Path(cfg["data_dir"]) / "blobs"), cfg.get("blob_max_files", 800))
    data_path = pathlib.Path(cfg["data_dir"])
    blob_dir = data_path / "blobs"
    log_dir = pathlib.Path(cfg.get("log_dir", "."))
    cleanup_state: dict = {}
    # 会话级临时状态：用户消息去重 / 已推送的工具结果
    _ss: dict = {}

    # 稳定的 serverId
    sid_path = pathlib.Path(cfg["data_dir"]) / "server_id.txt"
    if sid_path.exists():
        server_id = sid_path.read_text(encoding="utf-8").strip()
    else:
        server_id = uuid.uuid4().hex[:12]
        sid_path.write_text(server_id, encoding="utf-8")

    async def emit(session, type_: str, data: dict, message_id: str | None = None) -> dict:
        async with store.lock:
            seq = session.seq + 1
            ev = {
                "v": PROTOCOL_VERSION,
                "type": type_,
                "ts": now_ms(),
                "sessionId": session.key,
                "messageId": message_id,
                "seq": seq,
                "data": data,
            }
            session.append(ev, store.limit)
        await hub.publish(ev)
        return ev

    async def do_cleanup() -> dict:
        st = await asyncio.to_thread(run_cleanup, data_path, blob_dir, log_dir, cfg)
        # 过期会话（默认保留 30 天；0 = 永久保留）
        try:
            keys = expired_keys(store.sessions,
                                float(cfg.get("session_max_age_days", 30)), now_ms())
        except Exception:
            keys = []
        for k in keys:
            store.delete(k)
        for k in keys:
            await hub.broadcast({"v": PROTOCOL_VERSION, "type": "session.deleted", "ts": now_ms(),
                                 "sessionId": k, "messageId": None, "seq": 0, "data": {}})
        st["expired_sessions"] = len(keys)
        cleanup_state.clear()
        cleanup_state.update(st)
        return st

    async def _cleanup_loop():
        while True:
            try:
                st = await do_cleanup()
                if st.get("removed_files") or st.get("expired_sessions"):
                    print(f"[cleanup] 临时文件 {st['removed_files']} 个 / {st.get('freed_mb', 0)} MB；"
                          f"过期会话 {st['expired_sessions']} 个", flush=True)
            except Exception as e:
                print(f"[cleanup] 失败: {e}", flush=True)
            await asyncio.sleep(max(60, int(cfg.get("cleanup_interval_minutes", 60)) * 60))

    @app.on_event("startup")
    async def _on_startup():
        asyncio.create_task(_cleanup_loop())

    async def push_images(session, sstate: dict, contents: list):
        """从若干 content 中抽取图片 → 存 blob → 推送 msg.image（按 blob 去重）。"""
        seen = sstate.setdefault("seen_blobs", set())
        for content in contents:
            try:
                found = await asyncio.to_thread(collect_images, content)
            except Exception:
                found = []
            for data, mime in found:
                name = blobstore.save(data, mime)
                if name in seen:
                    continue
                seen.add(name)
                await emit(session, "msg.image",
                           {"blobId": name, "mime": mime, **describe_image(data)})

    # ------------------------------------------------------------ proxy
    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        # 只允许本机（Chatbox 桌面版）调用；远端要用 token 也走 WS，不开放代理
        if not _is_loopback(request):
            return JSONResponse({"error": {"message": "relay proxy is loopback-only"}}, status_code=403)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": {"message": "invalid json"}}, status_code=400)

        messages = body.get("messages") or []
        model = str(body.get("model") or "unknown")
        system_prompt = _first_text(messages, "system")
        first_user = _first_text(messages, "user")
        last_user = _last_text(messages, "user")

        # 元请求（如“自动生成标题”）只转发、不捕获，避免在手机端产生垃圾会话
        lu = (last_user or "").strip().lower()
        is_meta = (len(messages) == 1 and not body.get("tools")
                   and ("based on the chat history" in lu
                        or "give this conversation" in lu
                        or "title" in lu or "标题" in lu))
        if is_meta and cfg.get("ignore_meta_requests", True):
            upstream_base = request.headers.get("x-upstream-base") or cfg["upstream_base"]
            murl = upstream_base.rstrip("/") + "/chat/completions"
            mh = {"content-type": request.headers.get("content-type", "application/json")}
            auth0 = request.headers.get("authorization")
            if auth0 and cfg["forward_authorization"]:
                mh["authorization"] = auth0
            mclient = httpx.AsyncClient(timeout=httpx.Timeout(connect=20, read=None, write=60, pool=None))
            mresp = await mclient.send(mclient.build_request("POST", murl, json=body, headers=mh), stream=True)
            if not body.get("stream"):
                raw = await mresp.aread()
                await mresp.aclose()
                await mclient.aclose()
                return Response(content=raw, status_code=mresp.status_code,
                                media_type=mresp.headers.get("content-type", "application/json"))

            async def gen_meta():
                try:
                    async for chunk in mresp.aiter_bytes():
                        yield chunk
                finally:
                    await mresp.aclose()
                    await mclient.aclose()

            return StreamingResponse(gen_meta(), status_code=mresp.status_code,
                                     media_type=mresp.headers.get("content-type", "text/event-stream"))
        key = session_key(model, system_prompt, first_user or last_user)
        title = (first_user or last_user or model)[:60].replace("\n", " ")
        session = store.get_or_create(key, title)
        sstate = _ss.setdefault(key, {"last_user": None, "seen_tools": set()})

        # 记录用户提问（去重：带工具的多轮请求里 last_user 不变，避免重复）
        if last_user and last_user != sstate["last_user"]:
            sstate["last_user"] = last_user
            await emit(session, "msg.user", {"role": "user", "text": last_user})
            # 让注入器把“中继会话 <-> Chatbox 会话”的映射记下来
            await hub.dispatch({"v": PROTOCOL_VERSION, "type": "bridge.capture", "ts": now_ms(),
                                "data": {"sessionId": key, "userText": last_user, "title": title}})

        # 工具执行结果：来自后续请求里 role=tool 的消息（只发新的）
        for m in messages:
            if m.get("role") != "tool":
                continue
            tid = str(m.get("tool_call_id") or "")
            if tid and tid not in sstate["seen_tools"]:
                sstate["seen_tools"].add(tid)
                await emit(session, "msg.tool_result",
                           {"toolId": tid, "name": m.get("name"),
                            "text": _extract_text(m.get("content"))})

        # 消息里携带的图片（附件 / Markdown 图片 / 本地文件）→ 推给手机
        await push_images(session, sstate, [_m.get("content") for _m in messages])

        upstream_base = request.headers.get("x-upstream-base") or cfg["upstream_base"]
        url = upstream_base.rstrip("/") + "/chat/completions"
        headers = {"content-type": request.headers.get("content-type", "application/json")}
        auth = request.headers.get("authorization")
        if auth and cfg["forward_authorization"]:
            headers["authorization"] = auth

        mid = uuid.uuid4().hex[:12]
        is_stream = bool(body.get("stream"))

        client = httpx.AsyncClient(timeout=httpx.Timeout(connect=20, read=None, write=60, pool=None))
        req = client.build_request("POST", url, json=body, headers=headers)
        try:
            resp = await client.send(req, stream=True)
        except Exception as e:
            await client.aclose()
            await emit(session, "msg.done", {"text": "", "error": str(e)}, message_id=mid)
            return JSONResponse({"error": {"message": f"upstream error: {e}"}}, status_code=502)

        if not is_stream:
            try:
                raw = await resp.aread()
            finally:
                await resp.aclose()
                await client.aclose()
            text = rtext = ""
            tools0 = []
            try:
                obj = json.loads(raw)
                m0 = ((obj.get("choices") or [{}])[0].get("message") or {})
                text = _extract_text(m0.get("content"))
                rtext = m0.get("reasoning_content") or m0.get("reasoning") or ""
                tools0 = m0.get("tool_calls") or []
            except Exception:
                pass
            if rtext:
                await emit(session, "msg.reason", {"text": rtext}, message_id=mid)
            for i, tc in enumerate(tools0):
                fn = tc.get("function") or {}
                await emit(session, "msg.tool",
                           {"index": i, "id": tc.get("id"), "name": fn.get("name"),
                            "argsDelta": fn.get("arguments") or ""}, message_id=mid)
            if text:
                await emit(session, "msg.begin", {"role": "assistant"}, message_id=mid)
                await emit(session, "msg.delta", {"text": text}, message_id=mid)
            if text or rtext or tools0:
                await emit(session, "msg.done", {"text": text, "finishReason": "stop"}, message_id=mid)
                if hub.online_count == 0 and text:
                    await notifier.notify_done(title, text, session.key, mid)
            return Response(
                content=raw,
                status_code=resp.status_code,
                media_type=resp.headers.get("content-type", "application/json"),
            )

        media = resp.headers.get("content-type", "text/event-stream")

        async def gen():
            acc: list[str] = []
            started = False
            saw = False
            finish = None
            buf = ""
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk  # 原样透传给 Chatbox
                    buf += chunk.decode("utf-8", "ignore")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            continue
                        try:
                            obj = json.loads(payload)
                        except Exception:
                            continue
                        choice = (obj.get("choices") or [{}])[0]
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
                        delta = choice.get("delta") or {}
                        c = delta.get("content")
                        if c:
                            if not started:
                                started = True
                                await emit(session, "msg.begin", {"role": "assistant"}, message_id=mid)
                            acc.append(c)
                            await emit(session, "msg.delta", {"text": c}, message_id=mid)
                        # 思考过程（DeepSeek 等单独返回 reasoning_content）
                        rc = delta.get("reasoning_content") or delta.get("reasoning")
                        if rc:
                            saw = True
                            await emit(session, "msg.reason", {"text": rc}, message_id=mid)
                        # 工具调用（function call 增量）
                        tcs = delta.get("tool_calls")
                        if tcs:
                            saw = True
                            for tc in tcs:
                                fn = tc.get("function") or {}
                                await emit(session, "msg.tool", {
                                    "index": tc.get("index", 0),
                                    "id": tc.get("id"),
                                    "name": fn.get("name"),
                                    "argsDelta": fn.get("arguments") or "",
                                }, message_id=mid)
            except Exception as e:
                await emit(session, "msg.done", {"text": "".join(acc), "error": str(e)}, message_id=mid)
                return
            finally:
                await resp.aclose()
                await client.aclose()
            if started or saw:
                await emit(
                    session, "msg.done",
                    {"text": "".join(acc), "finishReason": finish or "stop"}, message_id=mid
                )
                await push_images(session, sstate, ["".join(acc)])
                if hub.online_count == 0 and "".join(acc):
                    await notifier.notify_done(title, "".join(acc), session.key, mid)

        return StreamingResponse(gen(), status_code=resp.status_code, media_type=media)

    @app.api_route("/v1/{rest:path}", methods=["GET", "POST", "OPTIONS"])
    async def v1_passthrough(rest: str, request: Request):
        """其余 /v1/* 透传（如 /models）。"""
        if not _is_loopback(request):
            return JSONResponse({"error": {"message": "forbidden"}}, status_code=403)
        upstream_base = request.headers.get("x-upstream-base") or cfg["upstream_base"]
        url = upstream_base.rstrip("/") + "/" + rest
        headers = {}
        if request.headers.get("authorization") and cfg["forward_authorization"]:
            headers["authorization"] = request.headers["authorization"]
        data = await request.body()
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.request(request.method, url, headers=headers, content=data,
                                params=dict(request.query_params))
        return Response(content=r.content, status_code=r.status_code,
                        media_type=r.headers.get("content-type", "application/json"))

    # ------------------------------------------------------------ REST (phone)
    def _authed(request: Request) -> bool:
        t = request.query_params.get("token") or _bearer(request.headers.get("authorization"))
        return bool(t) and t == cfg["token"]

    @app.get("/blobs/{name}")
    async def blob(name: str, request: Request):
        if not _authed(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if "/" in name or ".." in name or not blobstore.exists(name):
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(str(blobstore.path(name)))

    @app.post("/cleanup")
    async def cleanup_now(request: Request):
        if not _authed(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await do_cleanup()

    @app.get("/health")
    async def health():
        return {"ok": True, "clients": hub.online_count, "injectors": hub.injector_count,
                "sessions": len(store.sessions), "serverId": server_id, "protocol": PROTOCOL_VERSION,
                "cleanup": dict(cleanup_state)}

    @app.get("/sessions")
    async def sessions(request: Request):
        if not _authed(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return {"sessions": store.list_meta()}

    @app.get("/sessions/{sid}/messages")
    async def messages(sid: str, request: Request, since: int = 0, limit: int = 800):
        if not _authed(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        s = store.get(sid)
        if not s:
            return JSONResponse({"error": "not found"}, status_code=404)
        evs = [e for e in s.events if int(e.get("seq", 0)) > since]
        if limit and len(evs) > limit:
            evs = evs[-limit:]
        return {"events": evs}

    @app.delete("/sessions/{sid}")
    async def delete_session(sid: str, request: Request):
        if not _authed(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        removed = store.delete(sid)
        # 广播给所有客户端，手机端据此刻同步移除
        await hub.publish({"v": PROTOCOL_VERSION, "type": "session.deleted", "ts": now_ms(),
                           "sessionId": sid, "messageId": None, "seq": 0, "data": {}})
        return {"ok": removed}

    @app.get("/pair", response_class=HTMLResponse)
    async def pair(request: Request):
        """仅本机打开，打印 token / 连接地址 / 二维码。"""
        if not _is_loopback(request):
            return HTMLResponse("<h1>仅本机可访问</h1>", status_code=403)
        token = cfg["token"]
        port = cfg["port"]
        ips = _lan_ips()
        hosts = [f"ws://127.0.0.1:{port}/ws"] + [f"ws://{ip}:{port}/ws" for ip in ips]
        target = next((h for h in hosts if "100." in h), hosts[-1])
        img = _qr_data_uri(f"{target}?token={token}")
        rows = "".join(
            f"<tr><td style='padding:4px 10px'><code>{h}</code></td></tr>" for h in hosts
        )
        return f"""<!doctype html><meta charset=utf-8>
        <title>Chatbox Bridge 配对</title>
        <body style="font-family:system-ui;max-width:680px;margin:40px auto">
        <h2>Chatbox Bridge · 配对</h2>
        <p>在安卓 App「设置」里：<br>①打开二维码扫描，或②手动粘贴下面的 WebSocket 地址与 Token。</p>
        <p><b>Token</b>: <code>{token}</code></p>
        <table style="border-collapse:collapse">{rows}</table>
        <p style="margin-top:16px"><img src="{img}" width="220" height="220" alt="qr"></p>
        <p style="color:#888">提示：出门在外用 <code>100.x</code>（Tailscale）地址；在家可用局域网地址。</p>
        </body>"""

    # ------------------------------------------------------------ WebSocket
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        token = ws.query_params.get("token") or _bearer(ws.headers.get("authorization"))
        if token != cfg["token"]:
            await ws.close(code=4401)
            return
        await ws.accept()
        c = await hub.register(ws)
        await hub.send(c, hub.hello(server_id, store.list_meta(), hub.injector_count))
        try:
            while True:
                raw = await ws.receive_text()
                await _handle_client_msg(c, raw)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            await hub.unregister(c)
            if ws.client_state == WebSocketState.CONNECTED:
                try:
                    await ws.close()
                except Exception:
                    pass

    async def _handle_client_msg(c: Client, raw: str):
        try:
            msg = json.loads(raw)
        except Exception:
            await hub.send(c, {"v": PROTOCOL_VERSION, "type": "error", "ts": now_ms(),
                               "data": {"error": "invalid json"}})
            return
        t = str(msg.get("type") or "")
        data = msg.get("data") or {}

        if t == "ping":
            await hub.send(c, {"v": PROTOCOL_VERSION, "type": "pong", "ts": now_ms(), "data": {}})
            return

        if t == "subscribe":
            sid = data.get("sessionId")
            if sid:
                c.subs.add(sid)
            else:
                c.all = True
            replayed = 0
            # 仅当显式给了 sinceSeq 才回放历史（避免"只订阅未来"时拉全量）
            if "sinceSeq" in data:
                since = int(data.get("sinceSeq") or 0)
                targets = [sid] if sid else []
                for sk in targets:
                    s = store.get(sk)
                    if not s:
                        continue
                    for ev in s.events:
                        if int(ev.get("seq", 0)) > since:
                            await hub.send(c, ev)
                            replayed += 1
            await hub.send(c, {"v": PROTOCOL_VERSION, "type": "subscribed", "ts": now_ms(),
                               "data": {"sessionId": sid, "all": c.all, "replayed": replayed}})
            return

        if t == "injector.map":
            sid = data.get("sessionId")
            s = store.get(sid) if sid else None
            if s:
                if data.get("chatboxId"):
                    s.chatbox_id = str(data["chatboxId"])
                if data.get("title"):
                    s.title = str(data["title"])[:80]
                await hub.broadcast({"v": PROTOCOL_VERSION, "type": "session.upsert", "ts": now_ms(),
                                     "data": s.to_meta()})
            return

        if t == "injector.register":
            hub.injectors.add(c)
            await hub.send(c, {"v": PROTOCOL_VERSION, "type": "injector.registered", "ts": now_ms(),
                               "data": {"ok": True}})
            await hub.broadcast({"v": PROTOCOL_VERSION, "type": "bridge.status", "ts": now_ms(),
                                 "data": {"canControl": True, "injectors": hub.injector_count}})
            return

        if t == "injector.report":
            # 注入器把 DOM 自动化结果告知手机
            await hub.broadcast({"v": PROTOCOL_VERSION, "type": "control.result", "ts": now_ms(),
                                 "data": {"ok": bool(data.get("ok")), "mode": "inject",
                                          "error": data.get("stage") if not data.get("ok") else None,
                                          "reqId": data.get("reqId")}})
            return

        if t == "control.new":
            req_id = data.get("reqId")
            n = await hub.dispatch({"v": PROTOCOL_VERSION, "type": "control.new", "ts": now_ms(),
                                    "data": {"reqId": req_id}})
            await hub.send(c, {"v": PROTOCOL_VERSION, "type": "control.result", "ts": now_ms(),
                               "data": {"ok": n > 0, "mode": "new", "reqId": req_id,
                                        "error": None if n > 0 else "no_injector"}})
            return

        if t == "control.send":
            text = (data.get("text") or "").strip()
            req_id = data.get("reqId")
            sid = data.get("sessionId")
            s = store.get(sid) if sid else None
            if not text:
                await hub.send(c, {"v": PROTOCOL_VERSION, "type": "control.result", "ts": now_ms(),
                                   "data": {"ok": False, "error": "empty", "reqId": req_id}})
                return
            n = await hub.dispatch({"v": PROTOCOL_VERSION, "type": "control.dispatch", "ts": now_ms(),
                                    "data": {"text": text, "reqId": req_id, "sessionId": sid,
                                             "title": (s.title if s else ""),
                                             "chatboxId": (s.chatbox_id if s else "")}})
            await hub.send(c, {"v": PROTOCOL_VERSION, "type": "control.result", "ts": now_ms(),
                               "data": {"ok": n > 0, "mode": "inject", "reqId": req_id,
                                        "error": None if n > 0 else "no_injector"}})
            return

        if t.startswith("control."):
            # ---- 其余回控类型：尚未实现 ----
            await hub.send(c, {"v": PROTOCOL_VERSION, "type": "control.result", "ts": now_ms(),
                               "data": {"ok": False, "error": "not_implemented",
                                        "reqType": t, "reqId": data.get("reqId")}})
            return

        await hub.send(c, {"v": PROTOCOL_VERSION, "type": "error", "ts": now_ms(),
                           "data": {"error": f"unknown type: {t}"}})

    app.state.cfg = cfg
    app.state.store = store
    app.state.hub = hub
    app.state.server_id = server_id
    return app


def _first_text(messages, role) -> str:
    for m in messages:
        if m.get("role") == role:
            return _extract_text(m.get("content"))
    return ""


def _last_text(messages, role) -> str:
    for m in reversed(messages):
        if m.get("role") == role:
            return _extract_text(m.get("content"))
    return ""


def _qr_data_uri(text: str) -> str:
    try:
        import io
        import base64
        import qrcode  # type: ignore
        img = qrcode.make(text)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""
