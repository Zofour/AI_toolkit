"""把测试实例切到"新对话"（清空当前会话视图）。"""
import cdp

JS = ("(()=>{const b=[...document.querySelectorAll('button')]"
      ".find(x=>(x.innerText||'').trim()==='新对话');"
      "if(b){b.click();return 'clicked';}return 'no_btn';})()")

if __name__ == "__main__":
    c = cdp.CDP(9333)
    try:
        print(c.ev(JS).get("result", {}).get("result", {}).get("value"))
    finally:
        c.close()
