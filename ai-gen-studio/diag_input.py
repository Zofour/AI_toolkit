# -*- coding: utf-8 -*-
"""精确诊断：真实格式 / 能否解码 / 尾部字节 / 修改时间。不删除任何东西。"""
import io
import os
import struct
from datetime import datetime

D = r'C:\Users\yourname\Documents\ComfyUI\input'


def sniff(data):
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'PNG'
    if data[:2] == b'\xff\xd8':
        return 'JPEG'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'WEBP'
    if data[:3] == b'GIF':
        return 'GIF'
    if data[:2] == b'BM':
        return 'BMP'
    if b'ftyp' in data[:12]:
        return 'MP4/HEIF'
    if data[:4] == b'II*\x00' or data[:4] == b'MM\x00*':
        return 'TIFF'
    return '未知(' + data[:8].hex() + ')'


def main():
    files = sorted(os.listdir(D))
    bad = []
    for fn in files:
        p = os.path.join(D, fn)
        if not os.path.isfile(p):
            continue
        size = os.path.getsize(p)
        mt = datetime.fromtimestamp(os.path.getmtime(p))
        with open(p, 'rb') as f:
            data = f.read()
        fmt = sniff(data)
        tail = data[-12:].hex()
        dec = 'ok'
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(data))
            im.load()
            dec = f'ok {im.size} {im.mode}'
        except Exception as e:
            dec = f'FAIL {type(e).__name__}: {str(e)[:50]}'
        ext = os.path.splitext(fn)[1].lower()
        mismatch = (ext in ('.jpg', '.jpeg') and fmt != 'JPEG') or (ext == '.png' and fmt != 'PNG')
        dec_ok = dec.startswith('ok')
        if not dec_ok or mismatch or fmt == '未知':
            bad.append((fn, fmt, ext, size, mt, tail, dec, mismatch))
    print(f'input 目录共 {len(files)} 个文件，可疑 {len(bad)} 个\n')
    for fn, fmt, ext, size, mt, tail, dec, mm in bad:
        print(f'{fn}')
        print(f'   真实格式={fmt}  扩展名={ext}  {"【扩展名不符！文件其实是好的】" if mm else ""}')
        print(f'   {size:,} B   修改时间={mt:%Y-%m-%d %H:%M}   末12字节={tail}')
        print(f'   解码={dec}')


if __name__ == '__main__':
    main()
