# -*- coding: utf-8 -*-
"""
K230 流水线成品 -> 装饰卡片（贴纸布四周 + 底部校徽校名）
================================================================
两种用途：
  A) PC 出图：把「白底风格化人像 white_N.jpg + 背景 bgXXX.jpg」重排成 3:4 竖版卡片
  B) 给板子做装饰层：把「贴纸 + 底部校徽校名」烘焙成 RGBA8888 的 deco_<bg>.bin
     （RGB = 装饰已按该背景预合成好的颜色；A = 0/255 硬遮罩）
     板端只需 `comp = (ov & m) | (comp & ~m)` 一次位运算即可贴上去 —— 快且省内存。

用法
----
  # A) PC 出图（可调人像缩放/位置）
  python stickers_card.py --in <目录含 white_1.jpg / bg*.jpg> --bg bg104.jpg --out card.jpg
  python stickers_card.py --in <目录>                       # 批量所有 bg*.jpg
  python stickers_card.py --in <目录> --bg result_1.jpg --direct   # 只装饰成品图，不动人

  # B) 生成板端装饰层（每个背景一个 bin，放 /sdcard/deco/）
  python stickers_card.py --in <目录> --overlay --outdir <目录>     # 批量所有 bg*.jpg

  # 参数：--scale 人像高/画布高(0.80) --bottom 人像底边(1.03) --dx 水平偏移 --band pill|full|none
依赖: numpy, opencv-python, Pillow
"""
import os, sys, argparse
import numpy as np
import cv2
from PIL import Image

D = os.path.dirname(os.path.abspath(__file__))
W, H = 608, 768
ASSETS = r"C:\Users\yourname\Desktop\AI生成装饰素材_20261016"
BLUE = np.array([22, 74, 160], np.float32)

J = os.path.join
A = lambda *p: J(ASSETS, *p)
P_CHE = lambda i: A("01_樱花枝条_透明4张", "樱花枝条_0%d.png" % i)
P_STAR = lambda i: A("02_漫画装饰_透明20张", "star", "星星闪光_0%d.png" % i)
P_CLOUD = lambda i: A("02_漫画装饰_透明20张", "cloud", "紫色云朵_0%d.png" % i)
P_BADGE = lambda: A("03_北京化工大学校徽", "北京化工大学_校徽_蓝色_透明.png")
P_NAME = lambda: A("03_北京化工大学校徽", "北京化工大学_校名标准字_白色_透明.png")

_ALPHA = None      # 非 None 时进入「出装饰层」模式：颜色直接覆盖，alpha 单独累计


# ------------------------------------------------------------------ 贴图
def rgba(path):
    return np.asarray(Image.open(path).convert("RGBA"))


def strip_white(rgba_img, sat_thr=0.11, mx_thr=203, a_min=0.18):
    """清理贴纸素材：
    ① 去掉「白色贴纸描边/白雾」（低饱和+高亮度的像素）；
    ② 去掉很淡的 alpha 残渣（AI 生成/抠图留下的方形淡底）——
       不清掉的话，板端硬遮罩会把它当「覆盖」，在人像上挖出一块方形。"""
    a = np.asarray(rgba_img).astype(np.float32)
    rgb, al = a[:, :, :3], a[:, :, 3] / 255.0
    mx, mn = rgb.max(2), rgb.min(2)
    sat = (mx - mn) / np.maximum(mx, 1e-6)
    white = np.clip((sat_thr - sat) / sat_thr, 0, 1) * (mx > mx_thr)
    al = np.clip(al * (1.0 - white), 0, 1)
    al = np.clip((al - a_min) / (1.0 - a_min), 0, 1)
    out = a.copy()
    out[:, :, 3] = al * 255
    return out.astype(np.uint8)


def paste(canvas, img, **kw):
    """RGBA 贴到 (H,W,3) float32 画布。
    定位 x0/y0(左上角) 或 cx/cy(中心)；尺寸 w/h(像素) 或 scale；可选 rot/flip/op/
    blend/tint；outline=(r,g,b,r_px[,glow_r,glow_a]) 白元素加描边+柔辉光。"""
    img = np.asarray(img)
    if kw.get("flip"):
        img = img[:, ::-1]
    h0, w0 = img.shape[:2]
    tw, th = kw.get("w"), kw.get("h")
    if kw.get("scale") is not None:
        tw, th = int(round(w0 * kw["scale"])), int(round(h0 * kw["scale"]))
    if tw is not None and th is None:
        th = int(round(tw * h0 / w0))
    if th is not None and tw is None:
        tw = int(round(th * w0 / h0))
    if tw is None:
        tw, th = w0, h0
    pil = Image.fromarray(img).resize((max(1, int(tw)), max(1, int(th))), Image.LANCZOS)
    if kw.get("rot", 0):
        pil = pil.rotate(kw["rot"], resample=Image.BICUBIC, expand=True)
    img = np.asarray(pil)
    h, w = img.shape[:2]
    rgb = img[:, :, :3].astype(np.float32)
    if kw.get("tint") is not None:
        rgb = np.clip(rgb * np.array(kw["tint"], np.float32) / 255.0, 0, 255)
    al = img[:, :, 3].astype(np.float32) / 255.0 * kw.get("op", 1.0)
    x0 = int(kw["x0"]) if kw.get("x0") is not None else int(round(kw.get("cx", W / 2) - w / 2))
    y0 = int(kw["y0"]) if kw.get("y0") is not None else int(round(kw.get("cy", H / 2) - h / 2))
    X0, Y0, X1, Y1 = max(0, x0), max(0, y0), min(W, x0 + w), min(H, y0 + h)
    if X1 <= X0 or Y1 <= Y0:
        return None
    sx, sy = X0 - x0, Y0 - y0
    sub_a = al[sy:sy + (Y1 - Y0), sx:sx + (X1 - X0)][:, :, None]

    ol = kw.get("outline")
    if ol:                                  # 先描边/辉光，再贴内容
        col = np.array(ol[:3], np.float32)
        hard = (al > 0.35).astype(np.uint8)
        flat = np.broadcast_to(col, (Y1 - Y0, X1 - X0, 3))
        if len(ol) > 4 and ol[4] > 0:
            gr, ga = int(ol[4]), (ol[5] if len(ol) > 5 else 0.35)
            g = cv2.GaussianBlur(cv2.dilate(hard, cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (gr * 2 + 1,) * 2)).astype(np.float32), (0, 0), gr * 0.45)
            g = np.clip(g * ga - al, 0, 1)[sy:sy + (Y1 - Y0), sx:sx + (X1 - X0)][:, :, None]
            _blit(canvas, Y0, Y1, X0, X1, flat, g)
        r = int(ol[3])
        d = cv2.dilate(hard, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r * 2 + 1,) * 2)).astype(np.float32)
        if len(ol) > 4 and ol[4] > 0:           # 柔描边（带辉光）：好看但边上是淡区
            d = cv2.GaussianBlur(d, (0, 0), r * 0.4)
            ring = np.clip(d - al, 0, 1)
        else:                                   # 硬描边：板上不会因淡区挖洞
            ring = np.clip(d - hard, 0, 1)
        ring = (ring * kw.get("ol_op", 0.95))[sy:sy + (Y1 - Y0), sx:sx + (X1 - X0)][:, :, None]
        _blit(canvas, Y0, Y1, X0, X1, flat, ring)

    sub = rgb[sy:sy + (Y1 - Y0), sx:sx + (X1 - X0)]
    _blit(canvas, Y0, Y1, X0, X1, sub, sub_a)
    return (X0, Y0, X1, Y1)


def _blit(canvas, Y0, Y1, X0, X1, sub, sa):
    """把一块 (sub, sa) 按 over 合成进 canvas；出装饰层模式时额外并行累计 alpha。
    注意：颜色必须按 sa 加权混合（不能直接替色彩），否则低 alpha 的白色边缘
    会盖掉描边/辉光颜色，板上就会渲出白块。"""
    if sa is None:
        canvas[Y0:Y1, X0:X1] = sub
        if _ALPHA is not None:
            _ALPHA[Y0:Y1, X0:X1] = 1.0
        return
    reg = canvas[Y0:Y1, X0:X1]
    canvas[Y0:Y1, X0:X1] = reg * (1 - sa) + sub * sa
    if _ALPHA is not None:
        a2 = sa[:, :, 0] if sa.ndim == 3 else sa
        cur = _ALPHA[Y0:Y1, X0:X1]
        _ALPHA[Y0:Y1, X0:X1] = a2 + cur * (1.0 - a2)


# ------------------------------------------------------------------ 人像层
def person_layer(white_path, para, dbg=False):
    """白底人像 -> (rgb, alpha)：抠人 + 平滑轮廓 + 色阶拉伸/CLAHE/饱和（去灰白雾）"""
    bgr = cv2.imread(white_path)
    mn = bgr.min(axis=2).astype(np.float32)
    m = (mn < para["m_thr"]).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    if n > 1:
        m = (lab == 1 + int(np.argmax(stats[1:, 4]))).astype(np.uint8)
    ff = m.copy()
    cv2.floodFill(ff, np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8), (0, 0), 1)
    m = (m | (1 - ff)).astype(np.uint8)
    m = cv2.erode(m, np.ones((3, 3), np.uint8), iterations=para["m_erode"])
    m = (cv2.GaussianBlur(m.astype(np.float32), (0, 0), para["m_smooth"]) > 0.5).astype(np.uint8)

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32)
    lo, hi = para["lev"]
    x = np.clip((rgb - lo) * 255.0 / max(1.0, hi - lo), 0, 255) / 255.0
    x = np.power(x, para["gamma"]) * para["lift"]
    x = np.clip(x, 0, 1)
    g = x.mean(axis=2, keepdims=True)
    x = np.clip(g + (x - g) * para["sat"], 0, 1)
    rgb = x * 255.0
    if para.get("clahe", 0):
        li = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2LAB)
        li[:, :, 0] = cv2.createCLAHE(clipLimit=para["clahe"], tileGridSize=(8, 8)).apply(li[:, :, 0])
        rgb = cv2.cvtColor(li, cv2.COLOR_LAB2RGB).astype(np.float32)
    al = cv2.GaussianBlur(m.astype(np.float32), (0, 0), para["m_soft"])
    if dbg:
        vis = rgb * al[:, :, None] + np.array([40, 40, 55]) * (1 - al[:, :, None])
        cv2.imwrite(J(para["out"], "dbg_person.jpg"), cv2.cvtColor(vis.astype(np.uint8), cv2.COLOR_RGB2BGR))
    ys, xs = np.where(al > 0.5)
    rgb = rgb[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return rgb, al[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


# ------------------------------------------------------------------ 版式
def default_para():
    return dict(
        direct=False,
        p_h=0.80, p_cx=0.50, p_bottom=1.03,
        m_thr=248, m_erode=6, m_smooth=9, m_soft=0.9,
        lev=(25, 215), gamma=0.85, lift=1.0, sat=1.25, clahe=2.0,
        p_outline=4, p_outline_a=0.95,
        # 底部：校名放大 + 左侧校徽
        band=True, band_style="pill", band_w=0.50, band_h=0.090, band_a=1.0,
        band_y=0.952, logo_h=0.62, name_h=0.50, band_gap=0.018,
        deco=[])


def layout(para):
    """四角点缀（照参考卡：人与背景为主，贴纸压在角/边）"""
    OL = (34, 52, 130, 3)              # 描边色/宽（硬描边，无柔辉光）
    para["deco"] = [
        dict(src=P_CHE(2), x0f=0.695, y0f=-0.045, wf=0.30, op=0.98, outline=OL, dw=True),      # 右上樱花枝
        dict(src=P_CLOUD(2), x0f=0.855, y0f=0.315, wf=0.175, rot=-10, op=0.85),                # 右侧紫云
        dict(src=P_CHE(1), x0f=-0.055, y0f=0.795, wf=0.175, op=0.95, outline=OL, dw=True),     # 左下小枝
        dict(src=P_CHE(4), x0f=-0.045, y0f=-0.02, wf=0.15, rot=14, op=0.90, outline=OL, dw=True),  # 左上小枝
        dict(src=P_STAR(1), x0f=0.075, y0f=0.115, wf=0.095, op=0.95, outline=OL),
        dict(src=P_STAR(3), x0f=0.845, y0f=0.475, wf=0.065, op=0.90, outline=OL),
        dict(src=P_STAR(4), x0f=0.10, y0f=0.60, wf=0.06, op=0.90, outline=OL),
    ]
    return para


# ------------------------------------------------------------------ 合成
def _band(canvas, para):
    """底部校徽(左) + 校名(放大)。返回 alpha 图（出装饰层时用）或 None。"""
    bh = int(H * para["band_h"])
    pill = para["band_style"] == "pill"
    if pill:
        bw = int(W * para["band_w"])
        y0, x0 = int(H * para["band_y"] - bh / 2), (W - bw) // 2
        m = np.zeros((H, W), np.float32)
        r = bh // 2
        cyy = y0 + r
        m[y0:y0 + bh, x0 + r:x0 + bw - r] = 1.0                 # 中间矩形
        cv2.circle(m, (x0 + r, cyy), r, 1.0, -1)                # 两端半圆
        cv2.circle(m, (x0 + bw - r, cyy), r, 1.0, -1)
        m = cv2.GaussianBlur(m, (0, 0), max(1.5, bh * 0.030)) * para["band_a"]
        a = m[:, :, None]
        canvas[:] = canvas * (1 - a) + 255.0 * a
        if _ALPHA is not None:
            _ALPHA[:] = np.clip(m + _ALPHA * (1 - m), 0, 1)
        cy = y0 + bh // 2
    else:
        y0 = H - bh
        m = np.zeros((H, W), np.float32)
        m[y0:H] = para["band_a"]
        a = m[:, :, None]
        canvas[:] = canvas * (1 - a) + 255.0 * a
        if _ALPHA is not None:
            _ALPHA[:] = np.clip(m + _ALPHA * (1 - m), 0, 1)
        cy = y0 + bh // 2

    badge, nm = rgba(P_BADGE()), rgba(P_NAME())
    nm = np.concatenate([np.clip(nm[:, :, :3] * BLUE / 255.0, 0, 255).astype(np.uint8), nm[:, :, 3:]], axis=2)
    lh = max(10, int(bh * para["logo_h"]))            # 校徽高
    bwc = max(1, int(badge.shape[1] * lh / badge.shape[0]))
    nh = max(8, int(bh * para["name_h"]))             # 校名高
    nwc = max(1, int(nm.shape[1] * nh / nm.shape[0]))
    gap = int(W * para["band_gap"])
    xx = (W - (bwc + gap + nwc)) // 2
    paste(canvas, badge, x0=xx, cy=cy, h=lh, w=bwc)
    paste(canvas, nm, x0=xx + bwc + gap, cy=cy, h=nh, w=nwc)
    return (xx, cy, bwc, gap, nwc, lh, nh)


def build(base_path, person_path, para, dbg=False, overlay=False):
    global _ALPHA
    bg = np.asarray(Image.open(base_path).convert("RGB").resize((W, H), Image.LANCZOS)).astype(np.float32)
    if overlay:
        _ALPHA = np.zeros((H, W), np.float32)
        canvas = np.zeros((H, W, 3), np.float32)
    else:
        _ALPHA = None
        canvas = bg.copy()

        if not para["direct"]:
            rgb, al = person_layer(person_path, para, dbg)
            ph, pw = rgb.shape[:2]
            nh = int(H * para["p_h"])
            nw = max(1, int(pw * nh / ph))
            it = cv2.INTER_AREA if nh < ph else cv2.INTER_CUBIC
            rgb_s = cv2.resize(rgb, (nw, nh), interpolation=it)
            al_s = cv2.resize(al, (nw, nh), interpolation=it)
            px, py = int(W * para["p_cx"] - nw / 2), int(H * para["p_bottom"] - nh)
            X0, Y0, X1, Y1 = max(0, px), max(0, py), min(W, px + nw), min(H, py + nh)
            big = np.zeros((H, W), np.float32)
            big[Y0:Y1, X0:X1] = al_s[Y0 - py:Y1 - py, X0 - px:X1 - px]
            if para["p_outline"] > 0:                       # 白色贴纸描边
                k = int(para["p_outline"]) * 2 + 1
                ring = cv2.dilate((big > 0.15).astype(np.uint8),
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))).astype(np.float32)
                ring = cv2.GaussianBlur(ring, (0, 0), para["p_outline"] * 0.35) * para["p_outline_a"]
                ring = np.clip(ring - big, 0, 1)[:, :, None]
                canvas = canvas * (1 - ring) + 255.0 * ring
            sa = big[Y0:Y1, X0:X1][:, :, None]
            reg = canvas[Y0:Y1, X0:X1]
            canvas[Y0:Y1, X0:X1] = reg * (1 - sa) + rgb_s[Y0 - py:Y1 - py, X0 - px:X1 - px] * sa

    for d in para["deco"]:                              # 四角贴纸
        kw = {k: v for k, v in d.items() if k not in ("src", "dw")}
        if "x0f" in kw: kw["x0"] = int(round(W * kw.pop("x0f")))
        if "y0f" in kw: kw["y0"] = int(round(H * kw.pop("y0f")))
        if "wf" in kw: kw["w"] = max(1, int(round(W * kw.pop("wf"))))
        img = rgba(d["src"])
        if d.get("dw"):
            img = strip_white(img)
        paste(canvas, img, **kw)

    if para["band"]:                                    # 底部校徽校名
        _band(canvas, para)

    if overlay:                                         # 装饰层：颜色不预乘 + 软 alpha
        a = _ALPHA[:, :, None]
        rgb_out = np.where(a > 0.004, canvas / np.maximum(a, 1e-6), 0.0)
        msk = np.clip(_ALPHA * 255.0 + 0.5, 0, 255).astype(np.uint8)
        out = np.concatenate([np.clip(rgb_out, 0, 255).astype(np.uint8), msk[:, :, None]], axis=2)
        _ALPHA = None
        return out                                      # (H,W,4) uint8
    return np.clip(canvas, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------ CLI
def main():
    global ASSETS
    ap = argparse.ArgumentParser(description="K230 流水线成品 -> 装饰卡片 / 板端装饰层")
    ap.add_argument("--in", dest="indir", default=r"C:\chatbox_temp\work\k230_out")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--assets", default=ASSETS)
    ap.add_argument("--person", default="white_1.jpg")
    ap.add_argument("--bg", default=None)
    ap.add_argument("--name", default=None)
    ap.add_argument("--scale", type=float)
    ap.add_argument("--bottom", type=float)
    ap.add_argument("--dx", type=float)
    ap.add_argument("--band", choices=["pill", "full", "none"])
    ap.add_argument("--direct", action="store_true")
    ap.add_argument("--overlay", action="store_true", help="生成板端装饰层 deco_<bg>.bin (RGBA8888)")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()

    ASSETS = a.assets
    IN = a.indir
    OUT = a.outdir or (J(IN, "deco") if a.overlay else J(IN, "cards"))
    os.makedirs(OUT, exist_ok=True)
    para = layout(default_para())
    para["out"] = OUT
    para["direct"] = a.direct
    if a.scale is not None: para["p_h"] = a.scale
    if a.bottom is not None: para["p_bottom"] = a.bottom
    if a.dx is not None: para["p_cx"] = 0.5 + a.dx
    if a.band == "full": para["band_style"] = "full"
    if a.band == "none": para["band"] = False

    if a.bg:
        bases = [a.bg if os.path.isabs(a.bg) else J(IN, a.bg)]
    else:
        bases = [J(IN, n) for n in sorted(os.listdir(IN))
                 if n.lower().startswith("bg") and n.lower().endswith((".jpg", ".png"))]
    if not bases:
        print("没找到输入图（--bg）"); return 2
    for b in bases:
        if not os.path.isfile(b):
            print("找不到", b); continue
        o = build(b, J(IN, a.person), para, dbg=a.debug, overlay=a.overlay)
        stem = os.path.splitext(os.path.basename(b))[0]
        if a.overlay:
            p = J(OUT, a.name or ("deco_" + stem + ".bin"))
            open(p, "wb").write(o.tobytes())
        else:
            p = J(OUT, a.name or ("card_" + stem + ".jpg"))
            Image.fromarray(o).save(p, quality=95)
        print("saved", p, os.path.getsize(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
