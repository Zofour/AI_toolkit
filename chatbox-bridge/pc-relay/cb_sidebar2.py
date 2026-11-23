"""列出所有会话项(session-item)的全部属性，找“当前选中”的标识。"""
import cdp

JS = r"""
(()=>{
  const items=[...document.querySelectorAll('[data-testid="session-item"]')];
  return JSON.stringify(items.map(e=>({
    id:e.getAttribute('data-session-id'),
    ariaSelected:e.getAttribute('aria-selected'),
    ariaCurrent:e.getAttribute('aria-current'),
    dataActive:e.getAttribute('data-active'),
    cls:(e.className&&e.className.toString())||'',
    title:(e.innerText||'').replace(/\s+/g,' ').trim().slice(0,40)
  })),null,1);
})()
"""

if __name__ == "__main__":
    c = cdp.CDP(9333)
    try:
        print(c.ev(JS).get("result", {}).get("result", {}).get("value"))
    finally:
        c.close()
