# -*- coding: utf-8 -*-
"""生成模拟"手机拍纸"的测试照片，用于验证 PaperScanCore。"""
import os, math, random
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testdata")
os.makedirs(OUT, exist_ok=True)
random.seed(7)
np.random.seed(7)

FONT = "C:/Windows/Fonts/msyh.ttc"
FONTB = "C:/Windows/Fonts/msyhbd.ttc"


def make_page(pw=1240, ph=1754):
    img = Image.new("RGB", (pw, ph), (252, 250, 246))
    d = ImageDraw.Draw(img)
    f_title = ImageFont.truetype(FONTB, 40)
    f_h = ImageFont.truetype(FONTB, 26)
    f_b = ImageFont.truetype(FONT, 21)
    f_s = ImageFont.truetype(FONT, 17)

    d.text((90, 80), "第三章  扫描与文档处理", font=f_title, fill=(20, 20, 25))
    d.line([(90, 140), (pw - 90, 140)], fill=(60, 60, 70), width=2)

    y = 175
    for i, txt in enumerate(["一、实验目的", ]):
        d.text((90, y), txt, font=f_h, fill=(25, 25, 30))
    y += 40
    body = ["1. 掌握手机拍摄文档的基本流程，理解透视畸变产生的原因；",
            "2. 学会利用图像亮度与色彩信息分割纸张区域；",
            "3. 通过透视变换将倾斜的纸张还原为正向矩形；",
            "4. 使用背景估计与除法归一化消除阴影和色偏，使纸面变白。"]
    for t in body:
        d.text((110, y), t, font=f_b, fill=(35, 35, 40))
        y += 34

    y += 20
    d.text((90, y), "二、处理流程", font=f_h, fill=(25, 25, 30))
    y += 42
    steps = ["① 采集图像：白平衡设置为自动，避免强逆光；",
             "② 纸张检测：阈值分割 + 形态学 + 凸包 + 四角点拟合；",
             "③ 透视矫正：四点单应性变换，双线性重采样；",
             "④ 阴影去除：大尺度闭运算估计背景亮度，逐通道相除；",
             "⑤ 增强：色阶拉伸、S 形对比、反锐化掩模锐化。"]
    for t in steps:
        d.text((110, y), t, font=f_b, fill=(35, 35, 40))
        y += 34

    y += 24
    d.text((90, y), "三、实验数据记录", font=f_h, fill=(25, 25, 30))
    y += 44
    # 表格
    x0, x1 = 110, pw - 110
    cols = [x0, x0 + 120, x0 + 380, x0 + 560, x1]
    rows = 6
    row_h = 42
    for r in range(rows + 1):
        d.line([(x0, y + r * row_h), (x1, y + r * row_h)], fill=(70, 70, 80), width=1)
    for c in cols:
        d.line([(c, y), (c, y + rows * row_h)], fill=(70, 70, 80), width=1)
    head = ["序号", "样本名称", "纸张占比", "亮度均值"]
    for i, h in enumerate(head):
        d.text((cols[i] + 12, y + 10), h, font=f_s, fill=(20, 20, 25))
    data = [["1", "A-01 正视", "62%", "214"],
            ["2", "A-02 侧拍", "70%", "196"],
            ["3", "B-01 逆光", "48%", "142"],
            ["4", "B-02 阴影", "55%", "128"],
            ["5", "C-01 杂背景", "40%", "171"]]
    for r, row in enumerate(data):
        for i, v in enumerate(row):
            d.text((cols[i] + 12, y + (r + 1) * row_h + 10), v, font=f_s, fill=(40, 40, 45))

    # 手写体签名 + 红色印章
    d.text((720, ph - 260), "任课教师：张老师", font=f_b, fill=(30, 30, 60))
    d.text((720, ph - 215), "2026 年 11 月 20 日", font=f_s, fill=(30, 30, 60))
    seal = Image.new("RGBA", (230, 230), (0, 0, 0, 0))
    ds = ImageDraw.Draw(seal)
    ds.ellipse([8, 8, 222, 222], outline=(200, 30, 40, 235), width=7)
    fs = ImageFont.truetype(FONTB, 26)
    ds.text((46, 88), "实验中心", font=fs, fill=(200, 30, 40, 235))
    seal = seal.rotate(-12, expand=False, resample=Image.BICUBIC)
    img.paste(seal, (600, ph - 330), seal)
    # 轻微纸张纹理
    arr = np.asarray(img).astype(np.float32)
    arr += np.random.normal(0, 1.6, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def desk_bg(w, h, kind="wood"):
    if kind == "wood":
        base = np.zeros((h, w, 3), np.float32)
        for i in range(3):
            base[..., i] = np.linspace(96, 150, h)[:, None] * (0.85 if i == 2 else 1.0)
        # 木纹
        xx = np.arange(w)[None, :]
        yy = np.arange(h)[:, None]
        grain = 12 * np.sin(xx / 26.0 + 3 * np.sin(yy / 90.0)) + 8 * np.sin(yy / 13.0)
        base += grain[..., None]
        base += np.random.normal(0, 5, (h, w, 3))
        base = base * np.array([1.0, 0.86, 0.72])
    else:  # 杂乱：书本、布面
        base = np.random.normal(70, 6, (h, w, 3))
        img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        for _ in range(26):
            x = random.randint(-100, w); y = random.randint(-100, h)
            ww = random.randint(120, 420); hh = random.randint(140, 380)
            col = tuple(random.randint(20, 130) for _ in range(3))
            d.rectangle([x, y, x + ww, y + hh], fill=col)
            d.rectangle([x, y, x + ww, y + hh], outline=(15, 15, 18), width=3)
        img = img.filter(ImageFilter.GaussianBlur(1.2))
        base = np.asarray(img).astype(np.float32)
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))


def homography(src, dst):
    """求解 H 使 dst = H * src（各 4 点，numpy 最小二乘）。"""
    A = []
    b = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    A = np.array(A, np.float64); b = np.array(b, np.float64)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    return np.append(sol, 1.0).reshape(3, 3)


def paste_perspective(canvas_arr, page, quad):
    """把 page 按 quad（TL,TR,BR,BL，canvas 坐标）透视贴进 canvas_arr。"""
    ph, pw = page.size[1], page.size[0]
    H, W = canvas_arr.shape[:2]
    dst = [(0, 0), (pw, 0), (pw, ph), (0, ph)]
    # canvas -> page
    Minv = homography(list(quad), dst)
    xs = [p[0] for p in quad]; ys = [p[1] for p in quad]
    x0 = max(0, int(min(xs)) - 2); x1 = min(W - 1, int(max(xs)) + 2)
    y0 = max(0, int(min(ys)) - 2); y1 = min(H - 1, int(max(ys)) + 2)
    gy, gx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    ones = np.ones_like(gx, dtype=np.float64)
    P = np.stack([gx.ravel().astype(np.float64), gy.ravel().astype(np.float64), ones.ravel()])
    Q = Minv @ P
    u = Q[0] / Q[2]
    v = Q[1] / Q[2]
    inside = (u >= 0) & (u <= pw - 1) & (v >= 0) & (v <= ph - 1)
    parr = np.asarray(page).astype(np.float32)
    ui = np.clip(np.round(u).astype(int), 0, pw - 1)
    vi = np.clip(np.round(v).astype(int), 0, ph - 1)
    samp = parr[vi, ui]
    sub = canvas_arr[y0:y1 + 1, x0:x1 + 1]
    m = inside.reshape(sub.shape[0], sub.shape[1])
    sub[m] = samp.reshape(sub.shape[0], sub.shape[1], 3)[m]
    return m


def light(arr, shadow_dir=(0.55, 0.35), strength=0.55, warm=(1.02, 1.0, 0.95), vig=0.25):
    H, W = arr.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx = xx / W; ny = yy / H
    band = np.exp(-(((nx - shadow_dir[0]) ** 2) / (2 * 0.10 ** 2) + ((ny - shadow_dir[1]) ** 2) / (2 * 0.10 ** 2)))
    lm = 1.0 - strength * band
    r = np.sqrt((nx - 0.5) ** 2 + (ny - 0.5) ** 2)
    lm *= (1.0 - vig * r ** 2)
    out = arr * lm[..., None] * np.array(warm, np.float32)
    return out


def save(name, arr, q=82):
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    img.save(os.path.join(OUT, name), quality=q, subsampling=1)
    print("saved", name, img.size)


def build(name, quad_rel, bg_kind, shadow, warm, vig, scale_w=1600):
    page = make_page()
    W = scale_w
    H = int(W * 3 / 4)
    quads = [(int(x * W), int(y * H)) for x, y in quad_rel]
    bg = desk_bg(W, H, bg_kind)
    arr = np.asarray(bg).astype(np.float32)
    paste_perspective(arr, page, quads)
    arr = light(arr, strength=shadow, warm=warm, vig=vig)
    arr += np.random.normal(0, 3.0, arr.shape)
    save(name + ".jpg", arr)


def main():
    # A 正视微旋转，纸张约 62%
    build("A_frontal", [(0.18, 0.08), (0.80, 0.13), (0.84, 0.90), (0.14, 0.86)],
          "wood", 0.30, (1.0, 0.99, 0.97), 0.18)
    # B 强透视 + 阴影 + 暖色偏
    build("B_persp_shadow", [(0.10, 0.16), (0.86, 0.05), (0.94, 0.93), (0.20, 0.82)],
          "wood", 0.62, (1.05, 1.0, 0.90), 0.30)
    # C 纸张较小 + 杂乱背景
    build("C_clutter", [(0.28, 0.20), (0.74, 0.24), (0.76, 0.86), (0.26, 0.82)],
          "clutter", 0.35, (0.97, 0.99, 1.05), 0.22)
    # D 低照度 + 强阴影 + 冷色偏
    build("D_dim", [(0.14, 0.12), (0.84, 0.18), (0.88, 0.88), (0.10, 0.80)],
          "wood", 0.75, (0.92, 0.97, 1.08), 0.38)


if __name__ == "__main__":
    main()
