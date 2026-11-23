# -*- coding: utf-8 -*-
"""FileHub 服务端自检：接口 + Range + 缩略图，全部进程外 HTTP 调用。"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8730"
TOKEN = "CHANGE_ME_TOKEN"


def get(path, headers=None, raw=False):
    sep = "&" if "?" in path else "?"
    url = f"{BASE}{path}{sep}t={TOKEN}"
    req = urllib.request.Request(url, headers=headers or {})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        return r.status, dict(r.headers), (body if raw else json.loads(body)), time.time() - t0


def main():
    ok = True

    def check(label, cond, extra=""):
        nonlocal ok
        print(("  PASS  " if cond else "  FAIL  ") + label + ("  " + extra if extra else ""))
        if not cond:
            ok = False

    s, h, d, _ = get("/api/ping")
    check("ping", d.get("ok") and "roots" in d, str(d))

    s, h, d, _ = get("/api/roots")
    check("roots", s == 200 and d["count" if "count" in d else "entries"] is not None,
          f"{len(d['entries'])} roots")

    s, h, d, _ = get("/api/list?path=" + urllib.parse.quote("图片"))
    n = len(d["entries"])
    check("list 图片", s == 200 and n > 0, f"{n} entries")
    if n:
        print("        示例:", ", ".join(e["name"] for e in d["entries"][:5]))

    # 找一个视频
    s, h, d, _ = get("/api/list?path=" + urllib.parse.quote("视频"))
    vids = [e for e in d["entries"] if e["type"] == "video"]
    print(f"        视频 {len(vids)} 个")
    imgs = [e for e in d["entries"] if e["type"] == "image"]
    print(f"        图片 {len(imgs)} 个")

    # 从图片根找一个图片做缩略图与 Range 测试
    s, h, d, _ = get("/api/list?path=" + urllib.parse.quote("图片"))
    imgs = [e for e in d["entries"] if e["type"] == "image"]
    if not imgs:
        s, h, d, _ = get("/api/list?path=" + urllib.parse.quote("AI生图"))
        imgs = [e for e in d["entries"] if e["type"] == "image"]

    if imgs:
        p = urllib.parse.quote(imgs[0]["path"])
        s, h, body, dt = get(f"/f?path={p}", raw=True)
        check("image full GET", s == 200 and len(body) > 1000, f"{len(body)} bytes in {dt*1000:.0f}ms")
        s, h, body2, dt = get(f"/t?path={p}&w=400", raw=True)
        check("image thumb", s == 200 and body2[:2] == b"\xff\xd8", f"{len(body2)} bytes, cache={h.get('X-Thumb-Cache')}")
        s, h, body3, dt = get(f"/t?path={p}&w=400", raw=True)
        check("thumb cache hit", h.get("X-Thumb-Cache") == "hit", f"{dt*1000:.0f}ms")
    else:
        check("找一张图片", False)

    if vids:
        p = urllib.parse.quote(vids[0]["path"])
        s, h, body, dt = get(f"/f?path={p}", headers={"Range": "bytes=0-1023"}, raw=True)
        check("video Range 0-1023", s == 206 and len(body) == 1024,
              h.get("Content-Range", ""))
        s, h, body, dt = get(f"/f?path={p}", headers={"Range": "bytes=100000-"}, raw=True)
        check("video Range open-ended", s == 206 and len(body) > 0, f"{len(body)} bytes")
        s, h, body, dt = get(f"/t?path={p}&w=400", raw=True)
        check("video thumb", s == 200 and body[:2] == b"\xff\xd8",
              f"{len(body)} bytes in {dt*1000:.0f}ms")
    else:
        check("找一个视频", False)

    # 鉴权 / 越权
    try:
        urllib.request.urlopen(f"{BASE}/api/list?path={urllib.parse.quote('图片')}&t=bad", timeout=10)
        check("错误令牌应 401", False)
    except urllib.error.HTTPError as e:
        check("错误令牌 -> 401", e.code == 401)
    try:
        urllib.request.urlopen(f"{BASE}/f?path=..%2F..%2FWindows%2Fwin.ini&t={TOKEN}", timeout=10)
        check("路径穿越应被拒", False)
    except urllib.error.HTTPError as e:
        check("路径穿越被拒", e.code in (400, 404), f"code={e.code}")

    print("\n结果:", "全部通过" if ok else "有失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
