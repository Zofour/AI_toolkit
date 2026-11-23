# -*- coding: utf-8 -*-
"""按时间窗口找「崩溃瞬间正在写」的文件，并校验完整性。只报告，不删除。
用法: python scan_recent.py "2026-10-09 20:00" "2026-10-09 20:51"
"""
import io
import json
import os
import sys
from datetime import datetime

DIRS = [
    r'D:\image_temp',
    r'C:\Users\yourname\Documents\ComfyUI',
    r'C:\chatbox_temp',
    r'C:\Users\yourname\Desktop\working!',
    r'C:\Users\yourname\Desktop\else\SD-WEBUI-AKI-V5.0\sd-webui-aki-v4.10\models',
    r'D:\Comfy-Desktop\ComfyUI-Shared',
    r'D:\Comfy-Desktop\ComfyUI-Cache',
    r'D:\Comfy-Desktop\ComfyUI-Installs',
]
EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')
JUNK = ('.aria2', '.downloading', '.part', '.tmp', '.crdownload', '.partial')


def img_ok(path):
    try:
        from PIL import Image
        with open(path, 'rb') as f:
            data = f.read()
        if not data:
            return False, '0 字节'
        Image.open(io.BytesIO(data)).load()
        return True, 'ok'
    except Exception as e:
        return False, f'{type(e).__name__}: {str(e)[:60]}'


def main():
    t0 = datetime.strptime(sys.argv[1], '%Y-%m-%d %H:%M')
    t1 = datetime.strptime(sys.argv[2], '%Y-%m-%d %H:%M')
    rows = []
    for base in DIRS:
        if not os.path.isdir(base):
            continue
        for root, _d, files in os.walk(base):
            for fn in files:
                p = os.path.join(root, fn)
                try:
                    st = os.stat(p)
                    mt = datetime.fromtimestamp(st.st_mtime)
                except Exception:
                    continue
                if not (t0 <= mt <= t1):
                    continue
                low = fn.lower()
                tag = 'file'
                detail = ''
                if low.endswith(JUNK):
                    tag = 'JUNK'
                    detail = '未完成的临时/下载文件'
                elif low.endswith(EXTS):
                    ok, why = img_ok(p)
                    tag = 'IMG-OK' if ok else 'IMG-BROKEN'
                    detail = why
                elif low.endswith('.json'):
                    try:
                        json.loads(open(p, 'r', encoding='utf-8').read())
                        tag = 'JSON-OK'
                    except Exception as e:
                        tag = 'JSON-BROKEN'
                        detail = str(e)[:60]
                if st.st_size == 0 and not low.endswith(('.py',)):
                    tag += '/0B'
                rows.append((mt, tag, st.st_size, p, detail))
    rows.sort()
    print(f'窗口 {t0} ~ {t1} 内被写入的文件：{len(rows)} 个\n')
    for mt, tag, size, p, detail in rows:
        flag = '  ' if tag in ('IMG-OK', 'JSON-OK', 'file') else '⚠ '
        print(f'{flag}{mt:%m-%d %H:%M:%S}  [{tag:>11}]  {size:>12,} B  {p}' + (f'  <- {detail}' if detail else ''))
    bad = [r for r in rows if 'BROKEN' in r[1] or 'JUNK' in r[1]]
    print(f'\n可疑（损坏/未完成）: {len(bad)} 个')


if __name__ == '__main__':
    main()
