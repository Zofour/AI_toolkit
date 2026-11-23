"""探查 Chatbox 侧边栏（会话列表）的 DOM 结构。"""
import cdp

JS = r"""
(()=>{
  const out=[];
  for(const e of document.querySelectorAll('a,button,li,div')){
    const r=e.getBoundingClientRect();
    if(r.width<60||r.height<18||r.height>110) continue;
    if(r.left>320) continue;
    const t=(e.innerText||'').replace(/\s+/g,' ').trim();
    if(!t||t.length>80) continue;
    const hasSame=[...e.querySelectorAll('*')].some(c=>(c.innerText||'').replace(/\s+/g,' ').trim()===t);
    if(hasSame) continue;
    out.push({tag:e.tagName, txt:t, rect:[Math.round(r.left),Math.round(r.top),Math.round(r.width),Math.round(r.height)],
              cls:(e.className&&e.className.toString().slice(0,70))||'',
              attrs:[...e.attributes].map(a=>a.name+'='+String(a.value).slice(0,28)).slice(0,7)});
  }
  return JSON.stringify(out.slice(0,40),null,1);
})()
"""

if __name__ == "__main__":
    c = cdp.CDP(9333)
    try:
        print(c.ev(JS).get("result", {}).get("result", {}).get("value"))
    finally:
        c.close()
