"""Chatbox 注入器：把手机发来的消息注入 Chatbox "对应会话" 的输入框并发送。

流程：
- 中继捕获到某会话的新用户消息时，会发 bridge.capture；本注入器随即读取
  Chatbox「当前活动会话」的 data-session-id，建立 中继会话 <-> Chatbox会话 的映射
  （并回传中继，使手机显示 Chatbox 的标题）。
- 收到 control.dispatch 时：按映射点选对应会话 -> 聚焦输入框 -> 真实打字 -> 点发送。

前置：Chatbox 以 --remote-debugging-port=9333 启动（见 start_bridge.bat）。
用法: python chatbox_inject.py [--cdp 9333]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import websocket  # websocket-client

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cdp  # noqa: E402
from relay.config import load_config  # noqa: E402

MAP_FILE = os.path.join(HERE, "_cb_map.json")

ACTIVE_JS = (
    "(()=>{const a=[...document.querySelectorAll('[data-testid=\"session-item\"]')]"
    ".find(e=>/bg-chatbox-background-(?:brand-secondary|secondary-hover)/.test((e.className||'').toString()));"
    "if(!a)return '';return JSON.stringify({id:a.getAttribute('data-session-id'),"
    "title:(a.innerText||'').replace(/\\s+/g,' ').trim()});})()"
)


def click_by_id_js(cid: str) -> str:
    return ("(()=>{const e=document.querySelector('[data-session-id=\"" + cid + "\"]');"
            "if(!e)return 'notfound';e.click();return 'ok';})()")


def click_by_title_js(title: str) -> str:
    t = json.dumps(title, ensure_ascii=False)
    return ("(()=>{const t=" + t + ";const items=[...document.querySelectorAll("
            "'[data-testid=\"session-item\"]')];"
            "let e=items.find(x=>(x.innerText||'').replace(/\\s+/g,' ').trim()===t);"
            "if(!e)e=items.find(x=>(x.innerText||'').replace(/\\s+/g,' ').trim().includes(t));"
            "if(!e)return 'notfound';e.click();return 'ok';})()")


FOCUS = ("(()=>{const t=[...document.querySelectorAll('textarea')]"
         ".find(x=>/输入/.test(x.placeholder||''))||document.querySelector('textarea');"
         "if(!t)return 'no_input';t.focus();try{t.setSelectionRange(0,(t.value||'').length);}catch(e){}"
         "return 'ok';})()")
SEND = ("(()=>{const b=[...document.querySelectorAll('button')]"
        ".find(x=>(x.getAttribute('aria-label')||'').includes('发送'));"
        "if(!b)return 'no_send_btn';if(b.disabled)return 'send_disabled';b.click();return 'ok';})()")

CLICK_NEW = ("(()=>{const b=[...document.querySelectorAll('button')]"
             ".find(x=>/^新对话/.test((x.innerText||'').replace(/\\s+/g,' ').trim()));"
             "if(!b)return 'no_btn';b.click();return 'ok';})()")
MODEL_LABEL = ("(()=>{const pick=(sel)=>{for(const e of document.querySelectorAll(sel)){"
               "const t=(e.innerText||'').replace(/\\s+/g,' ').trim();"
               "if(t&&t.length<=40&&/DeepSeek|V4\\.1|flash/i.test(t))return t;}return '';};"
               "return pick('button')||pick('span');})()")


class Injector:
    def __init__(self, relay_ws: str, token: str, cdp_port: int):
        self.relay_ws = relay_ws
        self.token = token
        self.cdp_port = cdp_port
        self.cdp = None
        self.map = self._load()

    # ---------- 映射持久化 ----------
    def _load(self) -> dict:
        try:
            with open(MAP_FILE, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self):
        try:
            with open(MAP_FILE, "w", encoding="utf-8") as f:
                json.dump(self.map, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ---------- CDP ----------
    def conn(self):
        if self.cdp is None:
            self.cdp = cdp.CDP(self.cdp_port)
        return self.cdp

    def active_session(self):
        r = self.conn().ev(ACTIVE_JS).get("result", {}).get("result", {}).get("value") or ""
        if not r:
            return None
        try:
            return json.loads(r)
        except Exception:
            return None

    # ---------- 新建会话 ----------
    def new_chat(self) -> str:
        """在 Chatbox 里点“新对话”，返回当前模型标签。"""
        c = self.conn()
        r = c.ev(CLICK_NEW).get("result", {}).get("result", {}).get("value")
        if r != "ok":
            raise RuntimeError(f"new:{r}")
        time.sleep(0.7)
        return c.ev(MODEL_LABEL).get("result", {}).get("result", {}).get("value") or ""

    # ---------- 学习映射 ----------
    def learn(self, relay_sid: str, title: str) -> dict | None:
        a = self.active_session()
        if not a or not a.get("id"):
            return None
        self.map[relay_sid] = {"cbId": a["id"], "title": a.get("title") or title}
        self._save()
        return self.map[relay_sid]

    # ---------- 执行注入 ----------
    def inject(self, text: str, sid: str | None, title: str, cb_id: str):
        c = self.conn()
        target = None
        if sid and sid in self.map:
            target = self.map[sid].get("cbId")
        if not target and cb_id:
            target = cb_id
        switched = "current"
        if target:
            r = c.ev(click_by_id_js(target)).get("result", {}).get("result", {}).get("value")
            print(f"[injector] 切到会话 {target}: {r}", flush=True)
            if r == "ok":
                switched = "byId"
                time.sleep(0.8)
        if switched == "current" and title:
            r = c.ev(click_by_title_js(title)).get("result", {}).get("result", {}).get("value")
            if r == "ok":
                switched = "byTitle"
                print(f"[injector] 按标题切到「{title}」", flush=True)
                time.sleep(0.8)
        if switched == "current":
            print("[injector] 未能定位会话，按当前会话注入", flush=True)

        r = c.ev(FOCUS).get("result", {}).get("result", {}).get("value")
        if r != "ok":
            raise RuntimeError(f"focus:{r}")
        time.sleep(0.15)
        c.insert_text(text)
        time.sleep(0.5)
        r2 = c.ev(SEND).get("result", {}).get("result", {}).get("value")
        if r2 != "ok":
            raise RuntimeError(f"send:{r2}")
        return switched

    # ---------- 主循环 ----------
    def run(self):
        url = f"{self.relay_ws}?token={self.token}"
        while True:
            try:
                ws = websocket.create_connection(url, timeout=60, suppress_origin=True)
                ws.send(json.dumps({"type": "injector.register", "data": {}}))
                print("[injector] 已连上中继，等待指令…", flush=True)
                while True:
                    try:
                        raw = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not raw:
                        continue
                    msg = json.loads(raw)
                    t = msg.get("type")
                    data = msg.get("data") or {}
                    if t == "bridge.capture":
                        try:
                            m = self.learn(data.get("sessionId"), data.get("title"))
                            if m:
                                ws.send(json.dumps({"type": "injector.map", "data": {
                                    "sessionId": data.get("sessionId"),
                                    "chatboxId": m["cbId"], "title": m["title"]}}))
                        except Exception as e:
                            self.cdp = None
                            print(f"[injector] 学习映射失败: {e}", flush=True)
                    elif t == "control.new":
                        req_id = data.get("reqId")
                        try:
                            label = self.new_chat()
                            low = label.lower()
                            stage = "new" if ("flash" in low and "4.1" in label) else f"new(model={label})"
                            ws.send(json.dumps({"type": "injector.report",
                                                "data": {"reqId": req_id, "ok": True, "stage": stage}}))
                            print(f"[injector] 已新建会话，模型={label}", flush=True)
                        except Exception as e:
                            self.cdp = None
                            ws.send(json.dumps({"type": "injector.report",
                                                "data": {"reqId": req_id, "ok": False, "stage": str(e)}}))
                            print(f"[injector] 新建会话失败: {e}", flush=True)
                    elif t == "control.dispatch":
                        text = data.get("text", "")
                        req_id = data.get("reqId")
                        try:
                            mode = self.inject(text, data.get("sessionId"),
                                               data.get("title") or "", data.get("chatboxId") or "")
                            ws.send(json.dumps({"type": "injector.report", "data": {
                                "reqId": req_id, "ok": True, "stage": mode}}))
                            print(f"[injector] 已注入({mode}): {text[:50]}", flush=True)
                        except Exception as e:
                            self.cdp = None
                            ws.send(json.dumps({"type": "injector.report", "data": {
                                "reqId": req_id, "ok": False, "stage": str(e)}}))
                            print(f"[injector] 注入失败: {e}", flush=True)
            except Exception as e:
                print(f"[injector] 中继连接异常: {e}；3 秒后重试", flush=True)
                time.sleep(3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp", type=int, default=9333)
    ap.add_argument("--relay", default=None)
    args = ap.parse_args()
    cfg = load_config()
    relay_ws = args.relay or f"ws://127.0.0.1:{cfg['port']}/ws"
    print(f"[injector] relay={relay_ws}  cdp=127.0.0.1:{args.cdp}", flush=True)
    Injector(relay_ws, cfg["token"], args.cdp).run()


if __name__ == "__main__":
    main()
