# -*- coding: utf-8 -*-
"""扫描生成目录里损坏/不完整的图片。默认只报告不删除；加 --delete 才真删。
用法:
  python scan_broken.py               # 只报告
  python scan_broken.py --delete      # 确认后删除
  python scan_broken.py --json        # 机器可读
"""
import io
import json
import os
import sys

DIRS = [
    r'D:\image_temp',
    r'C:\Users\yourname\Documents\ComfyUI\output',
    r'C:\Users\yourname\Documents\ComfyUI\output\AIGen',
    r'C:\Users\yourname\Documents\ComfyUI\temp',
    r'C:\Users\yourname\Documents\ComfyUI\input',
    r'C:\Users\yourname\Documents\ComfyUI\user',
]
EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif')
BACKUP_JUNK = ('.aria2', '.downloading', '.part', '.tmp', '.crdownload')


PNG_IEND = b'\x49\x45\x4e\x44\xae\x42\x60\x82'  # 'IEND' + CRC


def check_image(path):
    """严格检查：0字节 / 解码失败 / 缺少文件尾标记（截断）
    返回 (ok: bool, reason: str, size: int)"""
    try:
        size = os.path.getsize(path)
    except Exception as e:
        return False, f'无法读取: {e}', -1
    if size == 0:
        return False, '0 字节（写入未完成）', 0
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except Exception as e:
        return False, f'读取失败: {e}', size
    low = path.lower()
    eof_note = ''
    # 文件尾完整性（仅供参考：JPEG 常带尾部附加数据，不能据此判损坏）
    if low.endswith('.png'):
        if data[:8] != b'\x89PNG\r\n\x1a\n':
            return False, f'PNG 头不对（可能是误命名）', size
        if not data.endswith(PNG_IEND):
            eof_note = '（尾部无 IEND，但可解码）'
    elif low.endswith(('.jpg', '.jpeg')):
        if data[:2] != b'\xff\xd8':
            return False, f'不是 JPEG（扩展名误命名）', size
        if not data.endswith(b'\xff\xd9'):
            eof_note = '（尾部无 EOI，但可解码）'
    # 像素全解码（截断文件会在此报错）—— 这才是真正的判据
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:
        return False, f'解码失败({type(e).__name__}: {str(e)[:60]})', size
    return True, 'ok' + eof_note, size


def main():
    delete = '--delete' in sys.argv
    as_json = '--json' in sys.argv
    results = {'ok': [], 'broken': [], 'junk': []}

    for base in DIRS:
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            for fn in files:
                p = os.path.join(root, fn)
                low = fn.lower()
                if low.endswith(BACKUP_JUNK) or low.endswith('.aria2'):
                    results['junk'].append({'path': p, 'size': os.path.getsize(p) if os.path.exists(p) else 0})
                    continue
                if not low.endswith(EXTS):
                    continue
                ok, reason, size = check_image(p)
                (results['ok'] if ok else results['broken']).append({'path': p, 'reason': reason, 'size': size})

    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"完好图片: {len(results['ok'])} 张")
        print(f"损坏图片: {len(results['broken'])} 张")
        for b in results['broken']:
            print(f"  ✗ {b['path']}  [{b['size']} B]  {b['reason']}")
        print(f"残留临时文件: {len(results['junk'])} 个")
        for j in results['junk']:
            print(f"  ⚠ {j['path']}  [{j['size']} B]")

    if delete:
        n = 0
        for b in results['broken'] + results['junk']:
            try:
                os.remove(b['path'])
                n += 1
            except Exception as e:
                print('删除失败:', b['path'], e)
        print(f'已删除 {n} 个文件')
    elif results['broken'] or results['junk']:
        print('\n（未删除任何文件；确认后加 --delete 再跑一次）')


if __name__ == '__main__':
    main()
