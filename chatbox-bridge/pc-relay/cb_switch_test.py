"""测试：读取活动会话 + 按 data-session-id 点选切换。"""
import json
import time

import cdp
import chatbox_inject as I


def main():
    c = cdp.CDP(9333)
    items = json.loads(c.ev(
        "JSON.stringify([...document.querySelectorAll('[data-testid=\"session-item\"]')]"
        ".map(e=>({id:e.getAttribute('data-session-id'),title:(e.innerText||'').replace(/\\s+/g,' ').trim().slice(0,30)})))"
    )["result"]["result"]["value"])
    print("会话数:", len(items))
    for it in items[:5]:
        print("  ", it["id"], it["title"])

    inj = I.Injector("ws://127.0.0.1:1/ws", "x", 9333)  # 仅用其方法
    print("当前活动:", inj.active_session())

    # 选一个不同于当前的第 2 个会话点过去
    cur = inj.active_session()
    target = next((x for x in items if cur and x["id"] != cur.get("id")), None)
    if target:
        print("点击 ->", target["id"], target["title"])
        r = inj.conn().ev(I.click_by_id_js(target["id"]))["result"]["result"]["value"]
        print("click:", r)
        time.sleep(1.2)
        print("切换后活动:", inj.active_session())
    inj.conn().close()


if __name__ == "__main__":
    main()
