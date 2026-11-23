# -*- coding: utf-8 -*-
"""生成应用图标：蓝底 + 白色稿纸 + 扫描线。"""
import os
from PIL import Image, ImageDraw

ROOT = r"C:\chatbox_temp\paper-scan\android\app\src\main\res"
SIZES = {"mipmap-mdpi": 48, "mipmap-hdpi": 72, "mipmap-xhdpi": 96,
         "mipmap-xxhdpi": 144, "mipmap-xxxhdpi": 192}


def icon(size):
    s = 4  # 超采样
    n = size * s
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 圆角蓝底
    d.rounded_rectangle([0, 0, n - 1, n - 1], radius=int(n * 0.22), fill=(47, 107, 255, 255))
    # 纸
    mx, my = int(n * 0.24), int(n * 0.15)
    pw, ph = int(n * 0.52), int(n * 0.70)
    d.rounded_rectangle([mx, my, mx + pw, my + ph], radius=int(n * 0.055), fill=(255, 255, 255, 255))
    # 文字线
    line_x0 = mx + int(n * 0.09)
    line_x1 = mx + pw - int(n * 0.09)
    for i in range(4):
        y = my + int(n * 0.17) + i * int(n * 0.105)
        d.rounded_rectangle([line_x0, y, line_x1 - (int(n * 0.07) if i == 3 else 0), y + int(n * 0.028)],
                            radius=int(n * 0.02), fill=(150, 168, 200, 255))
    # 扫描光带
    d.polygon([(mx - int(n * 0.06), my + int(n * 0.46)), (mx + pw + int(n * 0.06), my + int(n * 0.33)),
               (mx + pw + int(n * 0.06), my + int(n * 0.42)), (mx - int(n * 0.06), my + int(n * 0.55))],
              fill=(120, 240, 210, 235))
    img = img.resize((size, size), Image.LANCZOS)
    return img


def main():
    for folder, px in SIZES.items():
        d = os.path.join(ROOT, folder)
        os.makedirs(d, exist_ok=True)
        ic = icon(px)
        ic.save(os.path.join(d, "ic_launcher.png"))
        print("wrote", d, px)


if __name__ == "__main__":
    main()
