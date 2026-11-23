# -*- coding: utf-8 -*-
"""从 ModelScope 下载一个 transformers 模型到本地目录（可断点续传，不依赖 modelscope 包）。
用法: python download_model.py <ms_repo_id> <local_dir>     例如: Qwen/Qwen2.5-1.5B-Instruct D:\\models\\Qwen2.5-1.5B-Instruct
"""
import os, sys, json, time, requests

SKIP_EXT = ('.gitattributes',)
API = "https://www.modelscope.cn/api/v1/models/{repo}/repo/files?Revision=master&Root="
FILE = "https://www.modelscope.cn/api/v1/models/{repo}/repo?Revision=master&FilePath={path}"

def list_files(repo):
    r = requests.get(API.format(repo=repo), timeout=30)
    r.raise_for_status()
    data = r.json()
    files = []
    # 兼容两种返回结构
    items = data.get('Data', {}).get('Files') or data.get('Data', {}).get('files') or []
    if isinstance(items, list):
        for it in items:
            p = it.get('Path') or it.get('path') or it.get('Name') or it.get('name')
            if p and not it.get('Type') == 'tree':
                files.append(p)
    return files

def download(repo, dst, path):
    url = FILE.format(repo=repo, path=path)
    out = os.path.join(dst, path.replace('/', os.sep))
    os.makedirs(os.path.dirname(out) or dst, exist_ok=True)
    tmp = out + '.part'
    have = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    headers = {'Range': f'bytes={have}-'} if have else {}
    t0 = time.time()
    with requests.get(url, stream=True, timeout=60, headers=headers) as r:
        if have and r.status_code == 200:
            have = 0  # 服务器不支持续传则重来
            mode = 'wb'
        else:
            r.raise_for_status()
            mode = 'ab' if have else 'wb'
        total = int(r.headers.get('Content-Length', 0)) + have
        done = have
        with open(tmp, mode) as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk); done += len(chunk)
                if done % (20 << 20) < (1 << 20):
                    spd = done / max(time.time() - t0, 1e-6) / 1e6
                    print(f"  {path}: {done/1e6:.0f}/{total/1e6:.0f} MB ({spd:.1f} MB/s)", flush=True)
        if total and done < total:
            raise IOError(f"incomplete {path}: {done}/{total}")
    os.replace(tmp, out)
    print(f"  done {path} ({os.path.getsize(out)/1e6:.1f} MB)", flush=True)
    return out

def main():
    repo, dst = sys.argv[1], sys.argv[2]
    os.makedirs(dst, exist_ok=True)
    files = list_files(repo)
    print(f"repo={repo} files={len(files)}\n" + "\n".join("  " + f for f in files), flush=True)
    for f in files:
        if f.endswith(SKIP_EXT):
            continue
        out = os.path.join(dst, f.replace('/', os.sep))
        if os.path.exists(out) and os.path.getsize(out) > 0:
            print(f"  skip existing {f}", flush=True); continue
        for attempt in range(3):
            try:
                download(repo, dst, f); break
            except Exception as e:
                print(f"  retry {f} ({attempt+1}/3): {e}", flush=True); time.sleep(3)
    print("ALL DONE ->", dst, flush=True)

if __name__ == '__main__':
    main()
