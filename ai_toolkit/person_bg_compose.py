# -*- coding: utf-8 -*-
"""把人像（纯白底棚拍）合成到「真实世界环境背景」上，并模拟**不干净的抠图**效果，
用于训练可处理真实抠图的风格化 AI。

关键点：
- 白底键控（与画面边缘连通的近白区域判为背景）得到 alpha，再人为做成「不规则 / 羽化 / 残留边」的脏抠图。
- 背景从一批真实感场景图里随机取窗（随机缩放 / 平移 / 翻转 / 旋转 / 色调 / 虚化），
  使「人物周围的环境边框」尽量不重复，避免下游过拟合。
- 人物底边与画布底边对齐（半身像的裁切线落在画布外），只在上/左/右留出背景余量。

用法:
  python person_bg_compose.py --limit 8 --out-sub _sample      # 抽样预览
  python person_bg_compose.py                                   # 全量（mirror group_XXX\）
  python person_bg_compose.py --limit 200 --out-sub _sample200
"""
import argparse
import json
import os
import random
import glob
import numpy as np
import cv2
from PIL import Image

W, H = 1920, 1080

# rembg (u2net) 语义抠图：模型放本机，避免联网
os.environ.setdefault("U2NET_HOME", r"C:\chatbox_temp\ai_toolkit\models\rembg")
_SESS = None


def get_sess():
    global _SESS
    if _SESS is None:
        from rembg import new_session
        _SESS = new_session("u2net")
    return _SESS


def base_alpha(bgr):
    """基础 alpha = u2net(语义软边) ∪ 非白像素(白底直接反相)。"""
    minc = bgr.min(axis=2).astype(np.int16)
    sat = (bgr.max(axis=2).astype(np.int16) - minc)
    nonwhite = ((minc < 248) | (sat > 12)).astype(np.float32)
    try:
        from rembg import remove
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        out = remove(Image.fromarray(rgb), session=get_sess())
        u = np.asarray(out)[:, :, 3].astype(np.float32) / 255.0
        if u.shape != nonwhite.shape:
            u = cv2.resize(u, (nonwhite.shape[1], nonwhite.shape[0]))
    except Exception as e:
        print("rembg failed, fallback colorkey:", e)
        u = np.zeros_like(nonwhite)
    a = np.maximum(u, nonwhite)
    # 清理：只留最大连通块 + 小孔填充
    pu = (a > 0.5).astype(np.uint8)
    n2, lab2, stats, _ = cv2.connectedComponentsWithStats(pu, connectivity=8)
    if n2 > 1:
        big = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        keep = np.zeros(n2, np.uint8); keep[big] = 1
        for i in range(1, n2):
            if stats[i, cv2.CC_STAT_AREA] > 0.01 * stats[big, cv2.CC_STAT_AREA]:
                keep[i] = 1
        pu = keep[lab2]
    pu = cv2.morphologyEx(pu, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    a = np.maximum(a * (pu > 0), pu.astype(np.float32))
    # 退底：白上白（近白衣物）导致抠不净 / 面积过小时，用大核闭运算+填洞恢复成实心。
    # 因为原图该类区域本来就是白色（衣=底），保留原像素即可“找回”白衣服，
    # 且边缘自然带一圈没抠净的白底 —— 正是“脏抠图”效果。
    if (a > 0.5).mean() < 0.14:
        k = 161
        pu = (a > 0.5).astype(np.uint8)
        pu = cv2.morphologyEx(pu, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
        n2, lab2, st, _ = cv2.connectedComponentsWithStats(pu, connectivity=8)
        if n2 > 1:
            big = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
            pu = (lab2 == big).astype(np.uint8)
        ff = pu.copy()
        hm = np.zeros((pu.shape[0] + 2, pu.shape[1] + 2), np.uint8)
        cv2.floodFill(ff, hm, (0, 0), 2)
        holes = ((ff != 2) & (pu == 0)).astype(np.uint8)
        pu = cv2.bitwise_or(pu, holes)
        pu = cv2.erode(pu, np.ones((3, 3), np.uint8))  # 微收回白边
        a = cv2.GaussianBlur(pu.astype(np.float32), (0, 0), 1.2)
    a = cv2.GaussianBlur(a, (0, 0), 0.7)
    return a


# ---------------------------------------------------------------- matte
def white_key_alpha(bgr):
    """纯白底键控：白底几乎恒为 #FFFFFF，故直接按阈值判背景（含叉腰等封闭空隙）。
    返回 float32 alpha(0..1)。"""
    minc = bgr.min(axis=2).astype(np.int16)
    maxc = bgr.max(axis=2).astype(np.int16)
    sat = maxc - minc
    white = ((minc >= 252) & (sat <= 8)).astype(np.uint8)  # 背景（纯白）
    person = (1 - white).astype(np.uint8)
    # 去掉细碎噪点：只保留较大的前景连通块
    n2, lab2, stats, _ = cv2.connectedComponentsWithStats(person, connectivity=8)
    if n2 > 1:
        areas = stats[1:, cv2.CC_STAT_AREA]
        big = 1 + int(np.argmax(areas))
        keep = np.zeros(n2, np.uint8)
        keep[big] = 1
        for i in range(1, n2):
            if stats[i, cv2.CC_STAT_AREA] > 0.004 * stats[big, cv2.CC_STAT_AREA]:
                keep[i] = 1
        person = keep[lab2]
    person = cv2.morphologyEx(person, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    person = cv2.morphologyEx(person, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    a = person.astype(np.float32)
    # 边缘细节：靠近轮廓、且偏灰（发丝）的像素半透明
    band = cv2.dilate(person, np.ones((9, 9), np.uint8)) - cv2.erode(person, np.ones((9, 9), np.uint8))
    soft = np.clip((250 - minc) / 40.0, 0, 1).astype(np.float32)
    a = np.where(band > 0, a * np.clip(0.30 + 0.70 * soft, 0, 1), a)
    return a


def smooth_noise(rng, h, w, cells, blocky=False):
    gh = max(2, int(cells * h / max(h, w)))
    gw = max(2, int(cells * w / max(h, w)))
    small = rng.random((gh, gw)).astype(np.float32) * 2 - 1
    interp = cv2.INTER_NEAREST if blocky else cv2.INTER_CUBIC
    n = cv2.resize(small, (w, h), interpolation=interp)
    return n


def apply_imperfect_matte(rng, bgr, alpha):
    """把干净的 alpha 变成不规则/羽化/带残留的脏抠图，返回 (new_alpha, rim_kind)."""
    h, w = alpha.shape
    pu = (alpha > 0.5).astype(np.uint8) * 255
    dist_out = cv2.distanceTransform(255 - pu, cv2.DIST_L2, 3)   # 外侧到人物距离
    dist_in = cv2.distanceTransform(pu, cv2.DIST_L2, 3)          # 内侧到背景距离
    sd = dist_out - dist_in                                      # 负=人物内
    # 低频不规则位移场（平滑 + 块状混合），制造参差轮廓
    cells = rng.uniform(3.0, 9.0)
    n_smooth = smooth_noise(rng, h, w, cells, blocky=False)
    n_block = smooth_noise(rng, h, w, rng.uniform(2.0, 6.0), blocky=True)
    beta = rng.uniform(0.0, 0.55)
    noise = (1 - beta) * n_smooth + beta * n_block
    amt = rng.uniform(2.0, 13.0)                                 # 位移幅度(px)
    softness = rng.uniform(1.0, 3.2)
    a = np.clip(0.5 - (sd - noise * amt) / softness, 0, 1)
    # 保留原有的发丝半透明
    a = np.minimum(a, np.maximum(alpha, 0.0) * 0.5 + a * 0.5)

    # 残留边：模拟「背景没抠净」——亮边(白底残留)/暗边(阴影光晕)/彩边(环境溢出)
    rim_kind = "none"
    if rng.random() < 0.55:
        rim_kind = rng.choice(["light", "dark", "color"])
        t = rng.uniform(1.0, 3.6)
        band = np.clip((t - np.abs(sd)) / 1.2, 0, 1).astype(np.float32)
        # 让残留边呈局部斑块状（只出现于轮廓的一部分），避免整圈描边像贴纸
        patch = np.clip((noise - rng.uniform(-0.15, 0.7)) / 0.35, 0, 1).astype(np.float32)
        patch = cv2.GaussianBlur(patch, (0, 0), rng.uniform(2, 6))
        band = band * np.clip(0.25 + 0.9 * patch, 0, 1)
        band = cv2.GaussianBlur(band, (0, 0), 0.8)
        if rim_kind == "light":
            bg_ref = bgr.mean(axis=(0, 1))
            rim_col = np.clip(bgr * 0.0 + 255.0, 0, 255)  # 白
        elif rim_kind == "dark":
            rim_col = bgr * rng.uniform(0.15, 0.45)
        else:
            rim_col = bgr * rng.uniform(0.6, 1.1) + rng.uniform(-20, 20)
        strength = rng.uniform(0.12, 0.42)
        bgr = (bgr * (1 - band[..., None] * strength) +
               rim_col * (band[..., None] * strength)).astype(np.uint8)
        a = np.clip(a + band * rng.uniform(0.0, 0.35), 0, 1)

    # 抠漏的小孔/碎块：在人物内部近边处随机挖掉小块（残留背景）
    if rng.random() < 0.30:
        holes = np.zeros((h, w), np.float32)
        k = rng.integers(1, 5)
        ys, xs = np.where((sd > -18) & (sd < -1))
        if len(ys) > 0:
            for _ in range(int(k)):
                j = rng.integers(0, len(ys))
                cy, cx = int(ys[j]), int(xs[j])
                r = int(rng.integers(2, 8))
                cv2.circle(holes, (cx, cy), r, 1.0, -1)
        holes = cv2.GaussianBlur(holes, (0, 0), 1.2)
        a = np.clip(a - holes * rng.uniform(0.6, 1.0), 0, 1)
    return a, rim_kind, bgr


# ---------------------------------------------------------------- background
def prep_background(rng, bg_bgr, zoom, blur_choices=(0.0, 0.0, 0.6, 1.0, 1.6, 2.4, 3.4),
                    vignette=True):
    """随机缩放/翻转/旋转/裁剪成 1920x1080，再随机虚化与调色。"""
    h, w = bg_bgr.shape[:2]
    scale = zoom
    nw, nh = max(W + 40, int(w * scale)), max(H + 40, int(h * scale))
    im = cv2.resize(bg_bgr, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
    if rng.random() < 0.5:
        im = im[:, ::-1]
    if rng.random() < 0.3:
        im = im[::-1]
    ang = rng.uniform(-5, 5)
    M = cv2.getRotationMatrix2D((nw / 2, nh / 2), ang, 1.0)
    im = cv2.warpAffine(im, M, (nw, nh), flags=cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_REPLICATE)
    # 随机窗
    x0 = rng.integers(0, max(1, nw - W))
    y0 = rng.integers(0, max(1, nh - H))
    crop = im[y0:y0 + H, x0:x0 + W]
    if crop.shape[0] != H or crop.shape[1] != W:
        crop = cv2.resize(crop, (W, H))
    # 虚化（景深）
    sig = rng.choice(list(blur_choices))
    if sig > 0:
        crop = cv2.GaussianBlur(crop, (0, 0), float(sig))
    # 亮度/对比度/饱和/色调抖动
    f = crop.astype(np.float32)
    f *= rng.uniform(0.80, 1.18)
    f += rng.uniform(-16, 16)
    mean = f.mean()
    f = (f - mean) * rng.uniform(0.88, 1.15) + mean
    hsv = cv2.cvtColor(np.clip(f, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 0] = (hsv[..., 0] + rng.uniform(-8, 8)) % 180
    hsv[..., 1] = np.clip(hsv[..., 1] * rng.uniform(0.80, 1.20), 0, 255)
    f = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)
    # 暗角
    vg = rng.uniform(0.0, 0.16) if vignette else 0.0
    if vg > 0:
        yy, xx = np.mgrid[0:H, 0:W]
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        f *= (1 - vg * np.clip(r - 0.55, 0, 1.6))[..., None]
    return np.clip(f, 0, 255).astype(np.uint8)


def harmonize(person_bgr, mask_bool, bg_mean, w=0.35):
    p = person_bgr.astype(np.float32)
    pm = p[mask_bool].mean(axis=0) if mask_bool.any() else bg_mean
    ratio = np.clip(bg_mean / np.maximum(pm, 1.0), 0.80, 1.20)
    adj = 1 + w * (ratio - 1)
    return np.clip(p * adj, 0, 255).astype(np.uint8)


def compose_one(rng, src_bgr, bg_bgr):
    a0 = base_alpha(src_bgr.copy())
    a, rim_kind, src_bgr = apply_imperfect_matte(rng, src_bgr, a0)

    # 裁到人物内容包围盒（人物底部若是裁切线则保留之）
    ys_, xs_ = np.where(a > 0.02)
    if len(ys_):
        y1, y2 = int(ys_.min()), int(ys_.max()) + 1
        x1, x2 = int(xs_.min()), int(xs_.max()) + 1
        pad = 8
        y1, x1 = max(0, y1 - pad), max(0, x1 - pad)
        y2, x2 = min(a.shape[0], y2 + pad), min(a.shape[1], x2 + pad)
        a = a[y1:y2, x1:x2]
        src_bgr = src_bgr[y1:y2, x1:x2]

    # 人物变换：缩放 + 水平翻转 + 平移（内容底边与画布底边对齐）
    flip = rng.random() < 0.5
    s = rng.uniform(0.62, 1.06)
    ph = int(round(src_bgr.shape[0] * s))
    pw = int(round(src_bgr.shape[1] * s))
    person = cv2.resize(src_bgr, (pw, ph), interpolation=cv2.INTER_LANCZOS4)
    am = cv2.resize(a, (pw, ph), interpolation=cv2.INTER_LANCZOS4)
    if flip:
        person = person[:, ::-1]
        am = am[:, ::-1]

    bg = prep_background(rng, bg_bgr, rng.uniform(1.25, 2.1))
    canvas = bg.astype(np.float32)

    # 位置：底边对齐画布底（可略微超出），水平随机偏移
    y0 = H - ph + int(rng.integers(-12, 12))
    x0 = int(W / 2 - pw / 2 + rng.uniform(-0.12, 0.12) * W)

    # 计算有效粘贴区域
    ys, ye = max(0, y0), min(H, y0 + ph)
    xs, xe = max(0, x0), min(W, x0 + pw)
    if ye <= ys or xe <= xs:
        return canvas.astype(np.uint8)
    psub = person[ys - y0:ye - y0, xs - x0:xe - x0]
    asub = am[ys - y0:ye - y0, xs - x0:xe - x0]

    mask_bool = asub > 0.5
    if mask_bool.any():
        psub = harmonize(psub, mask_bool, canvas[..., :].reshape(-1, 3).mean(axis=0),
                         w=rng.uniform(0.15, 0.5))

    # 接触阴影（可选）：人物轮廓模糊后下移，先压暗背景
    if rng.random() < 0.6:
        dh, dw = asub.shape
        sh = cv2.GaussianBlur(asub, (0, 0), rng.uniform(4, 12))
        dx, dy = int(rng.integers(-14, 14)), int(rng.integers(2, 16))
        ys2, ye2 = max(0, ys + dy), min(H, ys + dy + dh)
        xs2, xe2 = max(0, xs + dx), min(W, xs + dx + dw)
        if ye2 > ys2 and xe2 > xs2:
            oy, ox = ys2 - (ys + dy), xs2 - (xs + dx)
            block = sh[oy:oy + (ye2 - ys2), ox:ox + (xe2 - xs2)]
            canvas[ys2:ye2, xs2:xe2] *= (1 - block[..., None] * rng.uniform(0.12, 0.35))

    aw = asub[..., None]
    canvas[ys:ye, xs:xe] = canvas[ys:ye, xs:xe] * (1 - aw) + psub.astype(np.float32) * aw

    # 全局颗粒
    grain = rng.uniform(0.0, 4.0)
    if grain > 0:
        canvas += rng.normal(0, grain, canvas.shape).astype(np.float32)
    return np.clip(canvas, 0, 255).astype(np.uint8)


def fp_h(img):
    return img.shape[0]


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-root", default=r"D:\zimage_persons_1000")
    ap.add_argument("--bg-dir", default=r"D:\zimage_persons_1000_matted\_backgrounds")
    ap.add_argument("--out-root", default=r"D:\zimage_persons_1000_matted")
    ap.add_argument("--out-sub", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--seed", type=int, default=20261013)
    a = ap.parse_args()

    bgs = sorted(glob.glob(os.path.join(a.bg_dir, "*.png")))
    if not bgs:
        raise SystemExit("no backgrounds in " + a.bg_dir)
    bg_cache = {}
    all_srcs = sorted(glob.glob(os.path.join(a.src_root, "group_*", "*.png")))
    srcs = all_srcs[a.offset:(a.offset + a.limit) if a.limit else None]
    out_root = os.path.join(a.out_root, a.out_sub) if a.out_sub else a.out_root
    print("sources=%d backgrounds=%d -> %s" % (len(srcs), len(bgs), out_root))

    base_rng = np.random.default_rng(a.seed)
    perm = np.arange(len(bgs))
    meta = []
    for j, sp in enumerate(srcs):
        i = a.offset + j
        rel = os.path.relpath(sp, a.src_root)
        dst = os.path.join(out_root, rel)
        if os.path.exists(dst) and not a.overwrite:
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        rng = np.random.default_rng((a.seed * 1000003 + i * 9176) % (2 ** 31))
        if i % len(bgs) == 0:
            base_rng.shuffle(perm)
        bgi = int(perm[i % len(bgs)])
        if bgi not in bg_cache:
            bg_cache[bgi] = cv2.imread(bgs[bgi], cv2.IMREAD_COLOR)
        src = cv2.imread(sp, cv2.IMREAD_COLOR)
        if src is None:
            continue
        out = compose_one(rng, src, bg_cache[bgi])
        cv2.imwrite(dst, out)
        meta.append({"file": rel, "bg": os.path.basename(bgs[bgi])})
        if (j + 1) % 25 == 0:
            print("  %d/%d" % (j + 1, len(srcs)), flush=True)
    with open(os.path.join(out_root, "_compose_manifest.jsonl"), "a", encoding="utf-8") as f:
        for m in meta:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    print("DONE %d (this chunk), %d written" % (len(srcs), len(meta)))


if __name__ == "__main__":
    main()
