# -*- coding: utf-8 -*-
"""
gen_m1.py —— M1 批量造蒸馏数据：真实照片 → (input, target) 训练对

    input   = 按 student 部署几何裁剪/缩放后的真实照片           （student 的输入）
    target  = teacher 风格化结果，只在人物 mask 内替换，mask 外保持 = input
              ^ 这一行同时教会 student 两件事：mask 内风格化、mask 外一根毛都不许动

用法：
    python gen_m1.py --src .\\expanded\\photo --out .\\m1 ^
        --lora .\\lora\\style_v1 --control softedge --hw 768 576 --seg auto
    # 只想先验证几何对不对、不跑模型：
    python gen_m1.py --src .\\expanded\\photo --out .\\m1 --dry

输出：
    out/input/000001.png     out/target/000001.png     out/mask/000001.png
    out/qc/000001.jpg        三联图（input | teacher 原始输出 | target）
    out/report.json          每张的结构一致性 / 风格统计，用于筛样本
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
import zlib
from pathlib import Path

import cv2
import numpy as np

from expand_canvas import auto_matte, imread_u, imwrite_u

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
_EXT_STRIP = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff", "raw"}

# 实际“戴着”眼镜的动作；
# 而 "holding a pair of sunglasses down at the side" 是拿在手上 = 没戴
_GLASSES_WORN_RE = re.compile(
    r"(adjust|adjusting|push|pushes|pushing|nudge|nudging|touching)[^.]{0,30}glasses", re.I)


def glasses_state(row: dict):
    """
    判断这张图人物**是否戴着**眼镜，返回 (worn, 描述)。

    为什么需要：manifest 的 accessory 与 pose 会互相矛盾。实测
      p0070_M_19  accessory="thin-rimmed round glasses"  -> 真戴着
      p0013_M_18  accessory="no accessories" 但
                  pose="one hand adjusting the temple of the glasses" -> 其实也戴着（漏标）
      p0015_M_18  pose="holding a pair of sunglasses down at the side" -> 拿在手上，没戴
    而“戴眼镜时眼睛崩”恰恰就是这里说不清造成的。
    """
    acc = (row.get("accessory") or "").strip()
    pose = (row.get("pose") or "").strip()
    if "glasses" in acc.lower():
        return True, acc
    if _GLASSES_WORN_RE.search(pose):
        return True, "wearing glasses"
    return False, "no glasses"


def core_name(name: str) -> str:
    """
    去掉重复的图片扩展名，得到用于配对的核心名。
    本项目的源图是 p0039_M_21.png，备份是 p0039_M_21.png.raw.png，
    两者必须归一到同一个名字才能和 manifest 对上。
    """
    while True:
        stem, dot, ext = name.rpartition(".")
        if dot and ext.lower() in _EXT_STRIP:
            name = stem
        else:
            return name

CN_MODELS = {
    "softedge": "lllyasviel/control_v11p_sd15_softedge",
    "canny": "lllyasviel/control_v11p_sd15_canny",
    "depth": "lllyasviel/control_v11f1p_sd15_depth",
    "lineart": "lllyasviel/control_v11p_sd15_lineart",
}


def load_manifest(path: Path, style_prefix: str, max_chars: int = 280):
    """
    从 manifest.csv 造**逐图内容 prompt**，返回 {文件名stem: prompt}。

    为什么要这个：只用一个固定 prompt 时，模型会用训练集的先验去填没说的东西
    （实测：输入女性被改写成男性、黑上衣被换成素材里的格纹衬衫）。
    把每张图自己的性别/发型/衣服/配饰写进 prompt，内容就不用靠猜了。

    风格词放最前面，这样即使超长被 CLIP 截断，风格也不会丢。
    """
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    out = {}
    for r in rows:
        f = (r.get("file") or "").replace("\\", "/")
        if not f:
            continue
        parts = []
        g = (r.get("gender") or "").strip()
        age = (r.get("age") or "").strip()
        head = " ".join(x for x in (age, g) if x)
        if head:
            parts.append(head)
        for k in ("hair", "outfit", "accessory"):
            v = (r.get(k) or "").strip()
            if v and v.lower() != "no accessories":
                parts.append(v)
        # 显式声明眼镜状态：戴着→写明，没戴→写 "no glasses"
        # （不写清楚，模型会拿训练集先验去猜，这就是“凭空加眼镜 / 戴眼镜时眼睛崩”的根因）
        worn, gdesc = glasses_state(r)
        if worn:
            if "glasses" not in ", ".join(parts).lower():
                parts.append(gdesc)
        else:
            parts.append("no glasses")
        body = ", ".join(parts)
        p = f"{style_prefix}, {body}" if body else style_prefix
        out[core_name(Path(f).name)] = p[:max_chars]
    n_worn = sum(1 for r in rows if glasses_state(r)[0])
    print(f"[manifest] {len(out)} 条逐图 prompt，其中 {n_worn} 张明确标注戴着眼镜")
    return out


def set_lora_scale(pipe, scale: float):
    """
    坑：diffusers 0.40 里 load_lora_weights 注入的 adapter 名是 'default_0'，
    写死 'default' 会抛 ValueError 并被 try/except 吞掉 ——
    后果是 --lora_scale **静默失效**，实际一直用 1.0。这里动态取名。
    """
    names = []
    for obj in (getattr(pipe, "unet", None), getattr(pipe, "text_encoder", None)):
        cfg = getattr(obj, "peft_config", None)
        if cfg:
            names = list(cfg.keys())
            break
    if not names:
        print("[warn] 找不到 LoRA adapter 名，lora_scale 可能没生效")
        return
    pipe.set_adapters(names, adapter_weights=[float(scale)] * len(names))


def enable_mem_savers(pipe):
    """
    省显存的小开关。
    注意：diffusers 0.40 起把 slicing 从 pipeline 移到了子模块上：
        pipe.enable_vae_slicing()   -> 已删除（会报 AttributeError）
        pipe.vae.enable_slicing()   -> 新写法
    这里新旧写法都试一遍，全失败也不影响功能，只是多吃点显存。
    """
    for fn in (lambda: pipe.vae.enable_slicing(),
               lambda: pipe.enable_vae_slicing()):
        try:
            fn()
            break
        except Exception:
            continue
    for fn in (lambda: pipe.enable_attention_slicing(),
               lambda: pipe.unet.set_attention_slice("auto")):
        try:
            fn()
            break
        except Exception:
            continue


# --------------------------------------------------------------------------- 几何
def bbox_from_mask(mask01: np.ndarray, expand: float, aspect: float, min_area: float = 0.02):
    """mask01: float (H,W) 1=人物。返回 ((x0,y0,x1,y1), 原始bbo宽高比)（box 已按目标长宽比规整，可能越界）"""
    m = (mask01 > 0.5).astype(np.uint8)
    if m.sum() < min_area * m.size:
        return None, None
    ys, xs = np.where(m > 0)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    raw_aspect = (x1 - x0) / max(1.0, float(y1 - y0))
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    w, h = (x1 - x0) * (1 + 2 * expand), (y1 - y0) * (1 + 2 * expand)
    if w / h < aspect:
        w = h * aspect
    else:
        h = w / aspect
    return ((int(round(cx - w / 2)), int(round(cy - h / 2)),
             int(round(cx + w / 2)), int(round(cy + h / 2))), raw_aspect)


def crop_clamp(img: np.ndarray, mask: np.ndarray, box):
    """按 box 裁剪并夹紧到图像内（不补边，避免大片边缘复制拉丝）"""
    H, W = img.shape[:2]
    x0, y0, x1, y1 = box
    x0, x1 = max(0, min(W, x0)), max(0, min(W, x1))
    y0, y1 = max(0, min(H, y0)), max(0, min(H, y1))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None, None
    return img[y0:y1, x0:x1].copy(), mask[y0:y1, x0:x1].copy()


def fit_hw(img: np.ndarray, hw, fill=None):
    """等比缩放+居中补边到 (H,W)。
    图像补边优先用 fill（背景色），否则用边缘复制；mask 一律补 0。
    注：不用 BORDER_REPLICATE —— 大块补边会把衣服拉成竖条纹。
    """
    H, W = hw
    h, w = img.shape[:2]
    s = min(W / w, H / h)
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR
    r = cv2.resize(img, (nw, nh), interpolation=interp)
    pad_l, pad_t = (W - nw) // 2, (H - nh) // 2
    pad_r, pad_b = W - nw - pad_l, H - nh - pad_t
    rect = (pad_l, pad_t, pad_l + nw, pad_t + nh)
    if img.ndim == 3:
        if fill is not None:
            out = cv2.copyMakeBorder(r, pad_t, pad_b, pad_l, pad_r,
                                     cv2.BORDER_CONSTANT, value=fill)
        else:
            out = cv2.copyMakeBorder(r, pad_t, pad_b, pad_l, pad_r, cv2.BORDER_REPLICATE)
        return out, rect
    return (cv2.copyMakeBorder(r, pad_t, pad_b, pad_l, pad_r,
                               cv2.BORDER_CONSTANT, value=0), rect)


# --------------------------------------------------------------------------- 质检
def ssim_gray(a: np.ndarray, b: np.ndarray, sigma: float = 1.5) -> float:
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a = cv2.GaussianBlur(a, (0, 0), sigma)
    mu_b = cv2.GaussianBlur(b, (0, 0), sigma)
    saa = cv2.GaussianBlur(a * a, (0, 0), sigma) - mu_a * mu_a
    sbb = cv2.GaussianBlur(b * b, (0, 0), sigma) - mu_b * mu_b
    sab = cv2.GaussianBlur(a * b, (0, 0), sigma) - mu_a * mu_b
    s = ((2 * mu_a * mu_b + C1) * (2 * sab + C2)) / \
        ((mu_a ** 2 + mu_b ** 2 + C1) * (saa + sbb + C2))
    return float(np.nanmean(s))


# --------------------------------------------------------------------------- 分割
class Segmenter:
    def __init__(self, kind: str, tol: float = 30.0, open_k: int = 3):
        self.kind, self.tol, self.open_k = kind, tol, open_k
        self._sess = None

    def __call__(self, bgr: np.ndarray) -> np.ndarray:
        if self.kind == "none":
            return np.ones(bgr.shape[:2], np.float32)
        if self.kind == "auto":                     # 无依赖，边框色同质背景最准
            return auto_matte(bgr, self.tol, self.open_k)
        if self.kind == "rembg":
            from rembg import new_session, remove
            if self._sess is None:
                self._sess = new_session("u2net_human_seg")
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            m = np.array(remove(rgb, session=self._sess, only_mask=True))
            return (m.astype(np.float32) / 255.0)
        raise SystemExit(f"未知分割方式: {self.kind}")


# --------------------------------------------------------------------------- 增广
def augment(bgr: np.ndarray, mask: np.ndarray, rng: random.Random, i: int):
    """同一张图造出多样化的输入（几何 + 光照），teacher 会跟着变"""
    H, W = bgr.shape[:2]
    if i == 0:
        return bgr, mask
    out, msk = bgr.copy(), mask.copy()
    if rng.random() < 0.5:
        out = out[:, ::-1].copy()
        msk = msk[:, ::-1].copy()
    if rng.random() < 0.7:
        s = rng.uniform(0.92, 1.12)
        M = cv2.getRotationMatrix2D((W / 2, H / 2), 0, s)
        M[0, 2] += rng.uniform(-0.04, 0.04) * W
        M[1, 2] += rng.uniform(-0.04, 0.04) * H
        out = cv2.warpAffine(out, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        msk = cv2.warpAffine(msk, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    if rng.random() < 0.6:
        out = np.clip(out.astype(np.float32) * rng.uniform(0.88, 1.12)
                      + rng.uniform(-12, 12), 0, 255).astype(np.uint8)
    if rng.random() < 0.4:
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * rng.uniform(0.85, 1.18), 0, 255)
        hsv[..., 0] = (hsv[..., 0] + rng.uniform(-6, 6)) % 180
        out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    return out, msk


# --------------------------------------------------------------------------- teacher
def build_cond_fn(kind: str):
    if kind == "none":
        return None
    if kind == "canny":
        from controlnet_aux import CannyDetector
        return CannyDetector()
    from controlnet_aux import HEDdetector, LineartDetector, MidasDetector
    if kind == "softedge":
        return HEDdetector.from_pretrained("lllyasviel/Annotators")
    if kind == "depth":
        return MidasDetector.from_pretrained("lllyasviel/Annotators")
    if kind == "lineart":
        return LineartDetector.from_pretrained("lllyasviel/Annotators")
    raise SystemExit(f"未知 control: {kind}")


class Teacher:
    def __init__(self, a):
        import torch
        from diffusers import (ControlNetModel, StableDiffusionControlNetImg2ImgPipeline,
                               UniPCMultistepScheduler)

        self.torch = torch
        self.a = a
        cn = (ControlNetModel.from_pretrained(a.cn_model, torch_dtype=torch.float16)
              if a.control != "none" else None)
        pipe = StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
            a.base_model, controlnet=cn, torch_dtype=torch.float16,
            safety_checker=None, requires_safety_checker=False)
        pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
        if a.lora:
            pipe.load_lora_weights(a.lora)
            set_lora_scale(pipe, a.lora_scale)
        self.pipe = pipe.to(a.device)
        enable_mem_savers(self.pipe)

    def __call__(self, bgr: np.ndarray, seed: int, prompt: str | None = None):
        from PIL import Image

        torch = self.torch
        a = self.a
        H, W = a.hw
        gH, gW = a.gen_hw
        src = cv2.resize(bgr, (gW, gH), interpolation=cv2.INTER_AREA if gW < bgr.shape[1] else cv2.INTER_LINEAR)
        pil = Image.fromarray(cv2.cvtColor(src, cv2.COLOR_BGR2RGB))

        kwargs = {}
        if a.control != "none":
            # cond_blur>0 时先高斯模糊再提边缘：把「深色衣物上的密集纹理」变成稀疏细线，
            # 否则引导图在深色区域是一大片黑，等于把原图的明暗/颜色也锁死了
            cb = int(getattr(a, "cond_blur", 0) or 0)
            if cb > 0:
                k = cb if cb % 2 == 1 else cb + 1
                pil_c = Image.fromarray(cv2.cvtColor(cv2.GaussianBlur(src, (k, k), 0),
                                                     cv2.COLOR_BGR2RGB))
            else:
                pil_c = pil
            cond = self.cond_fn(pil_c)
            if cond.size != pil.size:
                cond = cond.resize(pil.size)
            kwargs["control_image"] = cond
            kwargs["controlnet_conditioning_scale"] = a.cn_scale

        # 初始图模式：photo=直接用照片（默认）；gray=灰度化（去掉原图颜色）；
        # line=用 ControlNet 的线稿当初始图（等于「只给线稿，让它配色」）
        init = pil
        mode = getattr(a, "init_mode", "photo")
        if mode == "gray":
            init = Image.fromarray(cv2.cvtColor(cv2.cvtColor(src, cv2.COLOR_BGR2GRAY),
                                              cv2.COLOR_GRAY2RGB))
        elif mode == "line" and "control_image" in kwargs:
            c = kwargs["control_image"]
            init = c.convert("RGB") if c.mode != "RGB" else c

        g = torch.Generator(device=a.device).manual_seed(int(seed))
        out = self.pipe(prompt=(prompt or a.prompt), negative_prompt=a.negative, image=init,
                        strength=a.strength, num_inference_steps=a.steps,
                        guidance_scale=a.cfg, generator=g, **kwargs).images[0]
        res = np.array(out)[:, :, ::-1].copy()
        if res.shape[:2] != (H, W):
            res = cv2.resize(res, (W, H), interpolation=cv2.INTER_LANCZOS4)
        return res


# --------------------------------------------------------------------------- 主流程
def parse():
    ap = argparse.ArgumentParser("M1 批量造蒸馏数据")
    ap.add_argument("--src", required=True, help="真实照片目录（递归）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--hw", type=int, nargs=2, default=[768, 768],
                    help="student 输入高 宽（需为 32 的倍数）。默认 768x768（方形，贴合半身像素材）；"
                         "纯站姿竖构图可改 768x512；16:9 半身抓拍可改 832x448")
    ap.add_argument("--gen_hw", type=int, nargs=2, default=None,
                    help="teacher 生成尺寸，默认=hw；SD1.5 出伪影就调小，如 704 384")
    ap.add_argument("--seg", default="auto", choices=["auto", "rembg", "none"])
    ap.add_argument("--tol", type=float, default=30.0, help="seg=auto 的背景色容差")
    ap.add_argument("--open-k", type=int, default=3)
    ap.add_argument("--expand", type=float, default=0.15, help="人物 bbox 外扩比例")
    ap.add_argument("--feather", type=float, default=0.02, help="mask 羽化（占短边比例）")
    ap.add_argument("--aug_n", type=int, default=1, help="每张源图生成几个变体")
    ap.add_argument("--min-area", type=float, default=0.02, help="人物面积占比低于此值跳过")

    ap.add_argument("--base_model", default="runwayml/stable-diffusion-v1-5")
    ap.add_argument("--lora", default=None, help="train_style_lora.py 输出的目录")
    ap.add_argument("--lora_scale", type=float, default=0.65,
                    help="LoRA 权重。实测 0.55~0.8 安全；>=0.85 会把人物改写成训练集的平均脸（实测会变性别）")
    ap.add_argument("--control", default="softedge", choices=["none", "canny", "softedge", "depth", "lineart"])
    ap.add_argument("--init_mode", default="photo", choices=["photo", "gray", "line"],
                    help="img2img 初始图：photo=照片(默认)；gray=灰度化(去掉原图颜色，颜色交给 LoRA 重绘)；line=用 ControlNet 线稿当初始图")
    ap.add_argument("--cond_blur", type=int, default=0,
                    help="提边缘前先高斯模糊的核大小（奇数），越大引导图越稀疏；把深色区域的密集纹理去掉，避免颜色被原图锁死")
    ap.add_argument("--cn_model", default=None, help="默认按 --control 自动选")
    ap.add_argument("--cn_scale", type=float, default=0.80)
    ap.add_argument("--prompt", default="k230style, anime illustration, cel shading, clean lineart, upper body portrait, plain background")
    ap.add_argument("--manifest", default=None,
                    help="manifest.csv 路径。会用里边的 gender/age/hair/outfit/accessory 拼出**逐图 prompt**，"
                         "大幅减少内容泄漏（性别/衣服被老师先验改写）。强烈建议开")
    ap.add_argument("--prompt_max_chars", type=int, default=280, help="逐图 prompt 截断长度（CLIP 上限 77 token）")
    ap.add_argument("--resume", action="store_true",
                    help="断点续跑：target/ 里已存在的对直接跳过（跑 1000 张必开）")
    ap.add_argument("--negative", default="photo, realistic, 3d render, blurry, lowres, extra fingers, bad anatomy, watermark, signature, text, logo")
    ap.add_argument("--strength", type=float, default=0.68,
                    help="img2img 强度。实测 0.58 太低（风格出不来），0.85 会改写身份，0.68 起步")
    ap.add_argument("--steps", type=int, default=28)
    ap.add_argument("--cfg", type=float, default=7.0)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--min_ssim", type=float, default=0.35, help="结构一致性低于此值丢弃")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry", action="store_true", help="只做分割+裁剪，不跑 teacher（快速验证几何）")
    ap.add_argument("--qc", action="store_true", default=True)
    ap.add_argument("--no_qc", dest="qc", action="store_false")
    a = ap.parse_args()
    if a.gen_hw is None:
        # SD1.5 原生 512，直接按 768 这类尺寸生成会出现重复人头/多余肢体的经典伪影。
        # 面积超过 512^2 的 1.6 倍时，自动降分辨率生成、再放大回目标尺寸。
        H, W = a.hw
        limit = 1.6 * 512 * 512
        if H * W > limit:
            s = (limit / (H * W)) ** 0.5
            gh = max(128, int(H * s) // 8 * 8)
            gw = max(128, int(W * s) // 8 * 8)
            a.gen_hw = [gh, gw]
            print(f"[auto] 输入 {H}x{W} 对 SD1.5(原生512) 偏大，teacher 生成尺寸自动降为 "
                  f"{gh}x{gw} 后再放大，避免重复伪影；要强制请显式传 --gen_hw {H} {W}")
        else:
            a.gen_hw = list(a.hw)
    if a.cn_model is None:
        a.cn_model = CN_MODELS.get(a.control, CN_MODELS["softedge"])
    return a


def _keep_file(p: Path, src: Path, out: Path) -> bool:
    if not p.is_file() or p.suffix.lower() not in IMG_EXT:
        return False
    if out.resolve() in p.resolve().parents:
        return False
    # 跳过以 _ 开头的备份目录（本项目里有 _raw_backup/，且排序时排到最前面，很容易误跑）
    try:
        if any(part.startswith("_") for part in p.relative_to(src).parts[:-1]):
            return False
    except ValueError:
        pass
    return True


def main():
    a = parse()
    H, W = a.hw
    aspect = W / H

    src, out = Path(a.src), Path(a.out)
    if not src.exists():
        raise SystemExit(f"源目录不存在: {src}")
    for sub in ("input", "target", "mask", "qc"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    files_all = sorted(p for p in src.rglob("*") if _keep_file(p, src, out))
    files = files_all[:a.limit] if a.limit else files_all
    if a.limit and len(files_all) > a.limit:
        print(f"[info] 源目录共 {len(files_all)} 张，--limit {a.limit} 只跑前 {a.limit} 张"
              f"（要全跑请传 --limit 0）")
    show = files if len(files) <= 8 else files[:5]
    print("[info] 本次将处理:" + ("" if len(files) <= 8 else f"（共 {len(files)} 张，只列前 5）"))
    for p in show:
        print(f"        {p.name}")
    print(f"[info] 源图 {len(files)} 张 | 输入 {H}x{W} | teacher 生成 {a.gen_hw[0]}x{a.gen_hw[1]} | "
          f"control={a.control} | seg={a.seg} | aug_n={a.aug_n}")

    seg = Segmenter(a.seg, a.tol, a.open_k)
    teacher = None
    if not a.dry:
        print("[info] 加载 teacher（首次会下载权重，SD1.5+ControlNet 约 5GB）...")
        teacher = Teacher(a)
        if a.control != "none":
            teacher.cond_fn = build_cond_fn(a.control)

    # ---- 逐图内容 prompt（治内容泄漏：性别/衣服/配饰被老师先验改写）
    prompts = {}
    if a.manifest:
        mp = Path(a.manifest)
        if not mp.exists():
            raise SystemExit(f"manifest 不存在: {mp}")
        prompts = load_manifest(mp, a.prompt, a.prompt_max_chars)
        hit = sum(1 for f in files if core_name(f.name) in prompts)
        print(f"[manifest] 读到 {len(prompts)} 条逐图 prompt，匹配上 {hit}/{len(files)} 张源图")
        if hit == 0:
            raise SystemExit("manifest 的 file 列和源图名字完全对不上，检查一下")
        names = {core_name(f.name) for f in files}
        k0 = next(k for k in prompts if k in names)
        print(f"[manifest] 示例 [{k0}]: {prompts[k0][:140]}")

    rng = random.Random(a.seed)
    report, n_done, n_skip, n_resume, t0 = [], 0, 0, 0, time.time()
    ratios, bbox_aspects, warned_ratio = [], [], False
    total_est = len(files) * max(1, a.aug_n)

    for f in files:
        bgr = imread_u(f)
        if bgr is None:
            print(f"[warn] 读图失败 {f.name}")
            continue
        mask_full = seg(bgr)
        if mask_full is None:
            n_skip += 1
            continue
        box, raw_aspect = bbox_from_mask(mask_full, a.expand, aspect, a.min_area)
        if box is None:
            n_skip += 1
            continue
        bbox_aspects.append(raw_aspect)

        crop, mcrop = crop_clamp(bgr, mask_full, box)
        if crop is None:
            n_skip += 1
            continue
        sel = mcrop < 0.5
        fill = None
        if sel.sum() > 64:
            fill = tuple(float(v) for v in np.median(crop[sel], axis=0))
        crop, _ = fit_hw(crop, (H, W), fill=fill)
        mcrop, _ = fit_hw(mcrop, (H, W))
        mcrop = np.where(mcrop > 0.5, 1.0, 0.0).astype(np.float32)

        cn = core_name(f.name)
        base_prompt = prompts.get(cn, a.prompt)

        for k in range(max(1, a.aug_n)):
            name = cn if a.aug_n <= 1 else f"{cn}_a{k}"
            if a.resume and (out / "target" / f"{name}.png").exists():
                n_resume += 1
                continue

            x_bgr, x_msk = augment(crop, mcrop, rng, k)
            kk = max(3, int(a.feather * min(H, W)) | 1)
            m_soft = cv2.GaussianBlur(x_msk, (kk, kk), 0)

            x_u8 = np.clip(x_bgr, 0, 255).astype(np.uint8)
            # 种子由文件名派生，保证断点续跑时同一张图结果可复现
            seed = a.seed + zlib.crc32(name.encode("utf-8")) % 100000

            if a.dry:
                t_u8 = x_u8
                metrics = {}
            else:
                t_raw = teacher(x_bgr, seed, base_prompt)
                # 只在 mask 内取 teacher 结果，mask 外保持输入原样
                m3 = m_soft[..., None]
                t_u8 = np.clip(t_raw.astype(np.float32) * m3
                               + x_u8.astype(np.float32) * (1 - m3), 0, 255).astype(np.uint8)
                gx = cv2.cvtColor(x_u8, cv2.COLOR_BGR2GRAY)
                gt = cv2.cvtColor(t_u8, cv2.COLOR_BGR2GRAY)
                inside = m_soft > 0.5
                ssim_in = ssim_gray(np.where(inside, gx, 0), np.where(inside, gt, 0)) if inside.any() else 0.0
                hsv_t = cv2.cvtColor(t_u8, cv2.COLOR_BGR2HSV)
                metrics = {
                    "ssim": round(float(ssim_in), 4),
                    "sat": round(float(hsv_t[..., 1][inside].mean()), 2) if inside.any() else 0.0,
                    "val": round(float(hsv_t[..., 2][inside].mean()), 2) if inside.any() else 0.0,
                    "person_ratio": round(float(inside.mean()), 4),
                }
                if ssim_in < a.min_ssim:
                    n_skip += 1
                    if a.qc:
                        prev = np.hstack([x_u8, t_raw, t_u8])
                        imwrite_u(out / "qc" / f"DROP_{name}.jpg", prev)
                    print(f"[skip] {f.name} 结构一致性过低 ssim={ssim_in:.3f}")
                    continue
                ratios.append(metrics["person_ratio"])
                if not warned_ratio and metrics["person_ratio"] > 0.85:
                    warned_ratio = True
                    print(f"[warn] {f.name} 人物占比 {metrics['person_ratio']:.0%}（几乎是全图），"
                          f"极可能是分割失败（背景被当成人物）。若是真实照片请改用 --seg rembg")
                if a.qc:
                    prev = np.hstack([x_u8, t_raw, t_u8])
                    prev = cv2.resize(prev, (1620, int(1620 * prev.shape[0] / prev.shape[1])),
                                      interpolation=cv2.INTER_AREA)
                    imwrite_u(out / "qc" / f"{name}.jpg", prev)

            imwrite_u(out / "input" / f"{name}.png", x_u8)
            imwrite_u(out / "target" / f"{name}.png", t_u8)
            imwrite_u(out / "mask" / f"{name}.png",
                      (np.clip(m_soft, 0, 1) * 255).astype(np.uint8))
            report.append({"idx": name, "source": f.name, "aug": k, **metrics})
            n_done += 1

            if n_done % 10 == 0:
                el = time.time() - t0
                per = el / max(1, n_done)
                left = max(0, total_est - n_done - n_resume)
                print(f"[progress] {n_done}/{total_est} 对 | 跳过 {n_skip} | 续跑跳过 {n_resume} | "
                      f"{per:.1f} s/对 | 已用 {el/60:.1f} min | 剩余约 {per*left/60:.0f} min",
                      flush=True)

    # ---- 人物 bbox 长宽比统计 -> 用来选定 --hw（静态 shape 必须定死）
    if bbox_aspects:
        arr = np.array(bbox_aspects, dtype=np.float32)
        print(f"[geom] 人物 bbox 长宽比 W/H: 中位数 {np.median(arr):.3f}  "
              f"10%~90% [{np.percentile(arr,10):.3f}, {np.percentile(arr,90):.3f}]  "
              f"| 当前 --hw {H}x{W} => {W/H:.3f}")
        med = float(np.median(arr))
        if med > 0:
            ideal_h = int(round(H))
            ideal_w = max(32, int(round(ideal_h * med / 32)) * 32)
            if abs(W / H - med) > 0.12:
                print(f"[geom] 建议：目标长宽比与素材差异较大，可改用 --hw {ideal_h} {ideal_w}"
                      f"（更贴合人物，减少白边浪费）")

    # ---- 风格离群检测（同一风格的数据，饱和度/明度不该有大分叉）
    if report and not a.dry:
        sat = np.array([r["sat"] for r in report], dtype=np.float32)
        val = np.array([r["val"] for r in report], dtype=np.float32)
        for key, arr in (("sat", sat), ("val", val)):
            mu, sd = float(arr.mean()), float(arr.std() + 1e-6)
            for r in report:
                if abs(r[key] - mu) > 2.5 * sd:
                    r["style_outlier"] = True
        n_out = sum(1 for r in report if r.get("style_outlier"))
        print(f"[qc] sat {sat.mean():.1f}±{sat.std():.1f}  val {val.mean():.1f}±{val.std():.1f}  "
              f"风格离群 {n_out} 张（已在 report.json 标出 style_outlier）")
        ssims = np.array([r["ssim"] for r in report], dtype=np.float32)
        print(f"[qc] 结构一致性 ssim 均值 {ssims.mean():.3f}  最低 {ssims.min():.3f}")

    (out / "report.json").write_text(json.dumps(
        {"args": vars(a), "count": len(report), "skipped": n_skip,
         "resumed": n_resume, "items": report},
        ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[done] 新生成 {len(report)} 对（跳过 {n_skip}，续跑跳过 {n_resume}）-> {out.resolve()}")
    print("       input/ target/ mask/ 可直接喂给 train_distill.py；report.json 用于筛样本")


if __name__ == "__main__":
    main()
