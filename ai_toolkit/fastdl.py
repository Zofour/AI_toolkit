# -*- coding: utf-8 -*-
"""多线程分块 + 断点续传 下载器（国内镜像/直链皆可）。

用法:
  python fastdl.py <URL> <OUT> [--conns 8] [--retries 6]
- 若 OUT 已存在且未完成，会按已下载字节数继续（依赖服务端支持 Range）。
- 需要重定向跟随（gh-proxy / hf-mirror 会 302 到 CDN）。
"""
import argparse
import os
import sys
import threading
import time

import requests


def head_info(url, sess):
    r = sess.get(url, stream=True, timeout=(15, 30), allow_redirects=True)
    r.close()
    return r.status_code, r.headers, r.url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--conns", type=int, default=8)
    ap.add_argument("--retries", type=int, default=8)
    a = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0"
    st, hdr, final = head_info(a.url, sess)
    total = int(hdr.get("content-length") or 0)
    accept = hdr.get("accept-ranges", "")
    print("status=%s size=%.1fMB ranges=%s" % (st, total / 1e6, accept))
    if total == 0:
        print("no content-length; fallback single stream")
    if os.path.exists(a.out) and total:
        have = os.path.getsize(a.out)
        if have >= total:
            print("already complete (%.1fMB)" % (have / 1e6))
            return
    else:
        have = 0

    part = a.out + ".part"
    # 用 .part 记录，完成后改名
    if os.path.exists(part):
        have = max(have, os.path.getsize(part))
    else:
        have = 0
    f = open(part, "r+b" if os.path.exists(part) else "wb")
    f.truncate(total)
    f.close()

    n = max(1, a.conns)
    chunk = (total - have + n - 1) // n if total else 0
    lock = threading.Lock()
    done = {"v": have}
    t0 = time.time()

    def worker(idx, lo, hi):
        for attempt in range(a.retries):
            try:
                hh = {"Range": "bytes=%d-%d" % (lo, hi - 1)}
                with sess.get(final, headers=hh, stream=True, timeout=(15, 60)) as r:
                    if r.status_code not in (200, 206):
                        raise RuntimeError("HTTP %s" % r.status_code)
                    pos = lo
                    with open(part, "r+b") as wf:
                        wf.seek(lo)
                        for ch in r.iter_content(1 << 20):
                            wf.write(ch)
                            pos += len(ch)
                            with lock:
                                done["v"] += len(ch)
                    return
            except Exception as e:
                if attempt == a.retries - 1:
                    print("  worker %d FAIL @%d: %s" % (idx, lo, e))
                    return
                time.sleep(1.5)

    if total:
        ths = []
        lo = have
        i = 0
        while lo < total:
            hi = min(total, lo + chunk)
            t = threading.Thread(target=worker, args=(i, lo, hi), daemon=True)
            t.start(); ths.append(t); lo = hi; i += 1
        # 进度
        while any(t.is_alive() for t in ths):
            time.sleep(1.0)
            el = time.time() - t0
            print("  %.1f/%.1fMB  %.1fMB/s" % (done["v"] / 1e6, total / 1e6,
                                               (done["v"] - have) / 1e6 / max(el, 1e-3)))
        for t in ths:
            t.join()
    final_size = os.path.getsize(part)
    if total and final_size != total:
        print("INCOMPLETE %d/%d; rerun to resume" % (final_size, total))
        return
    os.replace(part, a.out)
    print("DONE %.1fMB in %.0fs -> %s" % (final_size / 1e6, time.time() - t0, a.out))


if __name__ == "__main__":
    main()
