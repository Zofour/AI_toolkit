#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
hfdl.py - 多线程 / 断点续传下载 HuggingFace(或 hf-mirror) 仓库里的大文件(GGUF 等)。

用法:
  python hfdl.py --repo 0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored-GGUF \
      --out-dir D:\\ollama_gguf --files a.gguf b.gguf --conns 8 \
      [--endpoint https://hf-mirror.com] [--revision main]

特性:
  - 按 Range 分块、多线程并发下载，单块失败自动重试（重新解析签名 URL，规避 1h 过期）
  - 进度/状态写 <out>.state.json，可随时中断后重跑续传
  - 完成后 .part 改名为正式文件；大小校验通过才完成
  - 打印 PROGRESS 行（含速度/ETA），便于外部轮询
支持 Python 3.8+；依赖 requests（本机已装）。
"""
import argparse, json, os, sys, threading, time

try:
    import requests
except ImportError:
    sys.exit("需要 requests: pip install requests")

_lock = threading.Lock()
_stop = threading.Event()


def resolve_url(endpoint, repo, revision, filename):
    return "{}/{}/resolve/{}/{}".format(endpoint.rstrip("/"), repo, revision, filename)


def head_size(url):
    r = requests.head(url, allow_redirects=True, timeout=(15, 30))
    cl = r.headers.get("Content-Length")
    if cl and cl.isdigit() and int(cl) > 0:
        return int(cl)
    # fallback: ranged GET
    r = requests.get(url, headers={"Range": "bytes=0-0"}, allow_redirects=True,
                     timeout=(15, 30), stream=True)
    cr = r.headers.get("Content-Range", "")
    r.close()
    if "/" in cr:
        return int(cr.split("/")[-1])
    raise RuntimeError("无法获取文件大小 (url=%s)" % url)


def load_state(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def download_one(url, out_path, conns, log):
    state_path = out_path + ".state.json"
    size = head_size(url)
    log("SIZE %s = %d bytes (%.2f GiB)" % (os.path.basename(out_path), size, size / 1024**3))

    if os.path.exists(out_path) and os.path.getsize(out_path) == size:
        log("SKIP %s 已存在且大小一致" % out_path)
        return True

    part = out_path + ".part"
    # 预分配
    with open(part, "wb") as f:
        f.truncate(size)

    state = load_state(state_path)
    if state.get("size") != size:
        state = {"size": size, "chunks": {}}
    chunks = state.setdefault("chunks", {})

    n = max(1, int(conns))
    block = (size + n - 1) // n

    def worker(idx):
        start = idx * block
        end = min(start + block, size) - 1
        if start >= size:
            return
        key = str(idx)
        with _lock:
            done = chunks.get(key, 0)
        pos = start + done
        while pos <= end and not _stop.is_set():
            headers = {"Range": "bytes=%d-%d" % (pos, end)}
            try:
                with requests.get(url, headers=headers, stream=True,
                                  timeout=(15, 60), allow_redirects=True) as r:
                    if r.status_code not in (200, 206):
                        raise RuntimeError("HTTP %s" % r.status_code)
                    with open(part, "r+b") as f:
                        f.seek(pos)
                        for chunk in r.iter_content(1 << 20):
                            if _stop.is_set():
                                return
                            if not chunk:
                                break
                            f.write(chunk)
                            pos += len(chunk)
                            with _lock:
                                chunks[key] = pos - start
                            if pos > end:
                                break
            except Exception as e:
                log("[retry %s] %s" % (key, e))
                time.sleep(2)
        with _lock:
            chunks[key] = pos - start

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)]
    t0 = time.time()
    last_bytes = 0
    last_t = t0
    for t in threads:
        t.start()

    while any(t.is_alive() for t in threads):
        time.sleep(3)
        with _lock:
            got = sum(chunks.values())
        now = time.time()
        inst = (got - last_bytes) / max(0.001, now - last_t)
        last_bytes, last_t = got, now
        eta = (size - got) / inst if inst > 0 else 0
        log("PROGRESS %s %.2f%%  %.2f/%.2f GiB  %.2f MB/s  ETA %s" % (
            os.path.basename(out_path), got * 100.0 / size, got / 1024**3, size / 1024**3,
            inst / 1024**2, time.strftime("%H:%M:%S", time.gmtime(eta))))
        save_state(state_path, state)

    with _lock:
        got = sum(chunks.values())
    ok = (got == size) and (os.path.getsize(part) == size)
    total = time.time() - t0
    if ok:
        os.replace(part, out_path)
        try:
            os.remove(state_path)
        except OSError:
            pass
        log("DONE %s  %.2f GiB  %s  (avg %.2f MB/s)" % (
            out_path, size / 1024**3, time.strftime("%H:%M:%S", time.gmtime(total)),
            size / total / 1024**2))
        return True
    log("INCOMPLETE %s  (got %d / %d bytes) 可重跑续传" % (out_path, got, size))
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--files", nargs="+", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--endpoint", default="https://hf-mirror.com")
    ap.add_argument("--revision", default="main")
    ap.add_argument("--conns", type=int, default=8)
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)

    def log(m):
        print(time.strftime("[%H:%M:%S] ") + m, flush=True)

    allok = True
    for fn in a.files:
        url = resolve_url(a.endpoint, a.repo, a.revision, fn)
        out = os.path.join(a.out_dir, os.path.basename(fn))
        log("=== %s" % out)
        try:
            allok &= download_one(url, out, a.conns, log)
        except Exception as e:
            log("ERROR %s: %s" % (fn, e))
            allok = False
    log("ALL_DONE ok=%s" % allok)


if __name__ == "__main__":
    main()
