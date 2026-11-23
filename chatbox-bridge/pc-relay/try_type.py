"""验证：用 CDP 真实输入文本 -> React 是否启用发送键。
用法: python try_type.py "要输入的文字"
"""
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("\\", 1)[0])
from cdp import CDP  # noqa: E402

FOCUS = "(()=>{const t=[...document.querySelectorAll('textarea')].find(t=>/输入你的问题/.test(t.placeholder||''))||document.querySelector('textarea');if(!t)return 'no_input';t.focus();t.select();return 'focused';})()"


def state(c):
    r = c.ev("JSON.stringify({val:(document.querySelector('textarea')||{}).value||'',"
             "send:[...document.querySelectorAll('button')].filter(b=>(b.getAttribute('aria-label')||'').includes('发送')).map(b=>b.disabled)})")
    return r.get("result", {}).get("result", {}).get("value")


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "BRIDGE_TEST_456"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 9333
    c = CDP(port)
    try:
        print("focus:", c.ev(FOCUS).get("result", {}).get("result", {}).get("value"))
        time.sleep(0.3)
        c.i += 1
        c.ws.send(json.dumps({"id": c.i, "method": "Input.insertText", "params": {"text": text}}))
        while True:
            m = json.loads(c.ws.recv())
            if m.get("id") == c.i:
                break
        time.sleep(0.5)
        print("after insertText:", state(c))
    finally:
        c.close()


if __name__ == "__main__":
    main()
