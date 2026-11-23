"""验证新版选择器：new_chat -> inject（在空闲测试实例上）。"""
import os
import time

import chatbox_inject as I
import cdp

PORT = 9334

inj = I.Injector("ws://127.0.0.1:1/ws", "x", PORT)
try:
    print("new_chat:", repr(inj.new_chat()))
    print("active   :", inj.active_session())
    time.sleep(1.0)
    print("inject   :", inj.inject("修复验证-新选择器", None, "", ""))
    time.sleep(2.0)
    print("active2  :", inj.active_session())
finally:
    try:
        inj.conn().close()
    except Exception:
        pass

c = cdp.CDP(PORT)
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_fix.png")
c.screenshot(p)
c.close()
print("[shot]", p)
