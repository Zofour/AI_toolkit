# -*- coding: utf-8 -*-
"""把人像（纯白底棚拍）**保持纯白画布**，仅沿**人物轮廓向外**加"一圈杂背景"
（真实感环境背景的随机残片），模拟人像从真实照片里粗糙抠出、边框没清理干净的样子。
**硬边、不羽化**。用于训练可处理真实抠图的风格化 AI。

- 画布 = 纯白 #FFFFFF，人物保持原位原尺；
- 一圈杂背景：沿轮廓向外的环形带，宽度随位置不规则变化（有些地方 0），
  外边界带块状/锯齿随机感（像套索剪切），硬边（不模糊、不羽化）；
- 残片来自一批真实感环境背景图（随机取窗/缩放/翻转/旋转），每张人像的
  环形状与来源都不同，避免下游过拟合。

用法:
  python person_dirty_bg.py --limit 10 --out-sub _sample
  python person_dirty_bg.py
"""
import argparse
import json
import os
import glob
import numpy as np
import cv2

from person_bg_compose import base_alpha, prep_background, smooth_noise  # noqa

W, H = 1920, 1080


def compose_dirty(rng, src_bgr, bg_bgr):
    a = base_alpha(src_bgr.copy())                # 人物 alpha（软边，用于人物本身）
    pu = (a > 0.5).astype(np.uint8) * 255
    dist_out = cv2.distanceTransform(255 - pu, cv2.DIST_L2, 3)
    dist_in = cv2.distanceTransform(pu, cv2.DIST_L2, 3)
    sd = (dist_out - dist_in).astype(np.float32)  # 负=人物内，正=人物外

    # ---- 一圈杂背景：宽度场（硬边，无羽化） ----
    n_smooth = smooth_noise(rng, H, W, rng.uniform(4.0, 12.0), blocky=False)
    n_block = smooth_noise(rng, H, W, rng.uniform(2.0, 5.0), blocky=True)   # 块状/锯齿
    w = 0.62 * n_smooth + 0.38 * n_block
    thr = rng.uniform(0.0, 0.16)                  # 局部少量留白
    amp = rng.uniform(12.0, 110.0) * (1.0 if rng.random() > 0.2 else rng.uniform(1.5, 2.4))
    wid = np.clip((w - thr) / (1 - thr), 0, None) * amp
    fine = smooth_noise(rng, H, W, rng.uniform(30.0, 90.0), blocky=True) * rng.uniform(1.0, 4.0)
    wid = wid + fine                              # 外边界再抖一点，像剪切毛边（硬像素级）
    band = ((sd <= wid) & (sd > 0)).astype(np.float32)

    # ---- 环境背景（随机窗口，不虚化） ----
    env = prep_background(rng, bg_bgr, rng.uniform(1.2, 2.0),
                          blur_choices=(0.0, 0.0, 0.3), vignette=False)

    # 画布纯白 → 环内填环境 → 人物盖上
    canvas = np.full((H, W, 3), 255.0, np.float32)
    bw = band[..., None]
    canvas = canvas * (1 - bw) + env.astype(np.float32) * bw

    aw = a[..., None]
    canvas = canvas * (1 - aw) + src_bgr.astype(np.float32) * aw

    return np.clip(canvas, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-root", default=r"D:\zimage_persons_1000")
    ap.add_argument("--bg-dir", default=r"D:\zimage_persons_1000_matted\_backgrounds")
    ap.add_argument("--out-root", default=r"D:\zimage_persons_1000_dirtybg")
    ap.add_argument("--out-sub", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--seed", type=int, default=20261013)
    a = ap.parse_args()

    bgs = sorted(glob.glob(os.path.join(a.bg_dir, "*.png")))
    if not bgs:
        raise SystemExit("no backgrounds in " + a.bg_dir)
    cache = {}
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
        if bgi not in cache:
            cache[bgi] = cv2.imread(bgs[bgi], cv2.IMREAD_COLOR)
        src = cv2.imread(sp, cv2.IMREAD_COLOR)
        if src is None:
            continue
        out = compose_dirty(rng, src, cache[bgi])
        cv2.imwrite(dst, out)
        meta.append({"file": rel, "bg": os.path.basename(bgs[bgi])})
        if (j + 1) % 25 == 0:
            print("  %d/%d" % (j + 1, len(srcs)), flush=True)
    with open(os.path.join(out_root, "_manifest.jsonl"), "a", encoding="utf-8") as f:
        for m in meta:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    print("DONE %d (this chunk), %d written" % (len(srcs), len(meta)))


if __name__ == "__main__":
    main()
