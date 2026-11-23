# -*- coding: utf-8 -*-
r"""给定根目录 + 时间窗口，列出期间被写入/修改的所有文件。
用法: python find_written.py "2026-10-09 20:45:30" "2026-10-09 20:51:00" <根目录1> <根目录2>
"""
import os
import sys
from datetime import datetime

SKIP = {'$Recycle.Bin', 'System Volume Information', 'Windows', 'WinSxS', 'Temp',
        'node_modules', '.git', '__pycache__', 'Cache', 'Code Cache', 'GPUCache'}


def main():
    t0 = datetime.strptime(sys.argv[1], '%Y-%m-%d %H:%M:%S')
    t1 = datetime.strptime(sys.argv[2], '%Y-%m-%d %H:%M:%S')
    roots = sys.argv[3:]
    hits = []
    for root0 in roots:
        for root, dirs, files in os.walk(root0):
            dirs[:] = [d for d in dirs if d not in SKIP]
            for fn in files:
                p = os.path.join(root, fn)
                try:
                    st = os.stat(p)
                except Exception:
                    continue
                mt = datetime.fromtimestamp(st.st_mtime)
                if t0 <= mt <= t1:
                    hits.append((mt, st.st_size, p))
    hits.sort()
    print(f'窗口 {t0}~{t1} 共 {len(hits)} 个文件')
    for mt, size, p in hits:
        print(f'  {mt:%m-%d %H:%M:%S}  {size:>13,} B  {p}')


if __name__ == '__main__':
    main()
