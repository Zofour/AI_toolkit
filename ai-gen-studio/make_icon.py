# -*- coding: utf-8 -*-
"""生成 AI Gen Studio 图标（渐变底 + 星芒），输出 icon.ico / icon.png"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

BASE = os.path.dirname(os.path.abspath(__file__))
S = 512


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def sparkle(draw, cx, cy, R, fill, inner=0.20):
    """四角星芒：外半径 R，内半径 inner*R"""
    pts = []
    for i in range(8):
        ang = math.pi / 2 * (i / 2) - math.pi / 2
        if i % 2 == 0:
            r = R
        else:
            r = R * inner
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    draw.polygon(pts, fill=fill)


def main():
    # 渐变底（圆角矩形）
    top, bot = (92, 140, 255), (124, 77, 255)
    grad = Image.new('RGB', (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        gd.line([(0, y), (S, y)], fill=lerp(top, bot, y / (S - 1)))

    mask = Image.new('L', (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)

    # 高光
    glow = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    gdr = ImageDraw.Draw(glow)
    gdr.ellipse([-S * 0.25, -S * 0.55, S * 0.85, S * 0.35], fill=(255, 255, 255, 46))
    glow = glow.filter(ImageFilter.GaussianBlur(28))
    img = Image.alpha_composite(img, Image.composite(glow, Image.new('RGBA', (S, S), (0, 0, 0, 0)), mask))

    d = ImageDraw.Draw(img)
    # 大星芒（左下偏中）
    sparkle(d, S * 0.42, S * 0.56, S * 0.34, (255, 255, 255, 255), inner=0.18)
    # 小星芒（右上）
    sparkle(d, S * 0.755, S * 0.285, S * 0.145, (255, 255, 255, 230), inner=0.24)

    img.save(os.path.join(BASE, 'icon.png'))
    img.save(os.path.join(BASE, 'icon.ico'),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print('生成:', os.path.join(BASE, 'icon.ico'))
    print('预览:', os.path.join(BASE, 'icon.png'))
    # 顺便导出 16/32 的放大预览，方便检查小尺寸效果
    prev = Image.new('RGBA', (16 * 10 + 32 * 10 + 20, 32 * 10), (24, 26, 34, 255))
    prev.paste(img.resize((16, 16), Image.LANCZOS).resize((160, 160), Image.NEAREST), (0, 0))
    prev.paste(img.resize((32, 32), Image.LANCZOS).resize((320, 320), Image.NEAREST), (180, 0))
    prev.save(os.path.join(BASE, 'icon_preview.png'))
    print('小尺寸预览: icon_preview.png')


if __name__ == '__main__':
    main()
