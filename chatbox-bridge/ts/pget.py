"""通用多线程断点续传下载器。
用法: python pget.py <URL> <输出文件> [连接数]
"""
import os
import sys
import threading
import time
import urllib.request

CONNS = 8
RETRY = 400


def head_size(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(r.headers["Content-Length"])


def fetch(url, idx, start, end, fn):
    total = end - start + 1
    have = os.path.getsize(fn) if os.path.exists(fn) else 0
    if have >= total:
        print(f"[{idx}] cached", flush=True)
        return
    for _ in range(RETRY):
        try:
            s = start + have
            if s > end:
                break
            req = urllib.request.Request(url, headers={"Range": f"bytes={s}-{end}"})
            with urllib.request.urlopen(req, timeout=30) as r, open(fn, "ab") as f:
                while True:
                    b = r.read(1 << 16)
                    if not b:
                        break
                    f.write(b)
                    have += len(b)
            if have >= total:
                print(f"[{idx}] done {have}/{total}", flush=True)
                return
        except Exception:
            time.sleep(0.5)
    print(f"[{idx}] incomplete {have}/{total}", flush=True)


def main():
    url = sys.argv[1]
    out = sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else CONNS
    size = head_size(url)
    print(f"size={size}", flush=True)
    if os.path.exists(out) and os.path.getsize(out) == size:
        print("already complete", flush=True)
        return
    step = size // n
    ranges = []
    for i in range(n):
        s = i * step
        e = (size - 1) if i == n - 1 else (s + step - 1)
        ranges.append((i, s, e))
    threads = []
    for (i, s, e) in ranges:
        fn = out + f".part{i}"
        t = threading.Thread(target=fetch, args=(url, i, s, e, fn), daemon=True)
        t.start()
        threads.append((t, fn))
    end = time.time() + 900
    while time.time() < end:
        if all(not t.is_alive() for t, _ in threads):
            break
        time.sleep(2)
    with open(out, "wb") as o:
        for _, fn in threads:
            if os.path.exists(fn):
                with open(fn, "rb") as f:
                    while True:
                        b = f.read(1 << 20)
                        if not b:
                            break
                        o.write(b)
    final = os.path.getsize(out)
    print(f"merged={final} expect={size} ok={final == size}", flush=True)
    if final == size:
        for _, fn in threads:
            try:
                os.remove(fn)
            except OSError:
                pass


if __name__ == "__main__":
    main()
