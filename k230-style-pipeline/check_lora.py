# -*- coding: utf-8 -*-
"""
check_lora.py —— 判断 LoRA 有没有过拟合

★ 前提：safetensors 文件本身**看不出**过拟合。它只是一堆低秩矩阵 A/B，
  文件大小只跟 rank、层数有关，跟模型"好不好"完全无关。
  能做的只有两件事：

  (1) --stats  把 LoRA 的 ΔW 范数算出来（ΔW = alpha/r * B@A），看尺度是否异常膨胀、
      以及跨 checkpoint 的增长趋势。这是**代理指标**，不精确但能预警。
  (2) --grid   唯一可靠的判断：拿**训练时没见过的人**的照片，按不同 adapter weight 出图，
      人眼看"风格有没有变成在抄训练图"。

用法：
  # 单文件
  python check_lora.py --stats "C:\\chatbox_temp\\work\\lora\\style_v1"

  # 跨 checkpoint 看增长趋势（推荐，能直接看出什么时候开始过拟合）
  python check_lora.py --stats "C:\\chatbox_temp\\work\\lora\\style_v1\\checkpoint-300" ^
                               "C:\\chatbox_temp\\work\\lora\\style_v1\\checkpoint-600" ^
                               "C:\\chatbox_temp\\work\\lora\\style_v1\\checkpoint-900"

  # 出图对比
  python check_lora.py --grid "C:\\chatbox_temp\\work\\lora\\style_v1" ^
      --inputs "C:\\chatbox_temp\\work\\expanded\\photo" --weights 0.6 0.8 1.0 1.2
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import torch


# --------------------------------------------------------------------------- 读取
def find_safetensors(path: Path):
    if path.is_file():
        return [path]
    # 排除 --fix 生成的 .orig 备份，否则会被重复统计/重复修复
    cands = [p for p in path.rglob("*.safetensors") if ".orig." not in p.name]

    def key(p: Path):
        rel = p.relative_to(path)
        depth = len(rel.parts) - 1                  # 0 = 直接放在该目录下
        m = re.search(r"checkpoint-(\d+)", str(rel))
        step = int(m.group(1)) if m else 10 ** 9
        # 中间快照按**步数数值**升序在前；根目录的文件放最后（它是“最终版”）。
        # 坑：之前用字符串排序，checkpoint-1200 会排在 checkpoint-300 前面，
        #     导致 --grid 指向根目录时反而抓到了旧的 checkpoint-1200。
        return (0 if depth else 1, step, str(rel))

    cands.sort(key=key)
    return cands


def pick_lora(root: Path, files):
    """
    出图应该用“最终版”：优先根目录的 pytorch_lora_weights.safetensors。
    注意不能用 files[0] —— find_safetensors 把中间快照排前面。
    """
    direct = root / "pytorch_lora_weights.safetensors"
    if root.is_dir() and direct.exists():
        return direct
    return files[-1] if files else None


AA = "A"
PAIR_TAGS = {
    "A": ("lora_A", "lora_down", "lora.down", "lora_linear_layer.down"),
    "B": ("lora_B", "lora_up", "lora.up", "lora_linear_layer.up"),
}


def normalize_key(k: str) -> str:
    """
    把 LoRA key 统一成 lora_A / lora_B。

    为什么必须做：diffusers 的 save_lora_weights 会同时吐出三套命名
        <m>.lora_A.weight / .lora_B.weight
        <m>.lora.down.weight / .lora.up.weight                  (UNet 注意力)
        <m>.lora_linear_layer.down.weight / .up.weight          (TE 注意力)
    而 load_lora_weights 认不全 —— 实测 UNet 的 278 层只加载了 150 层，
    128 层注意力 LoRA 被**静默丢弃**（不报错，只是没生效）。
    """
    return (k.replace(".lora_linear_layer.down.", ".lora_A.")
             .replace(".lora_linear_layer.up.", ".lora_B.")
             .replace(".lora.down.", ".lora_A.")
             .replace(".lora.up.", ".lora_B.")
             .replace(".lora_down.", ".lora_A.")
             .replace(".lora_up.", ".lora_B."))


def group_ab(sd):
    """配对 A/B（自动兼容三套命名，先用 normalize_key 归一化）"""
    pairs = {}
    for k, v in sd.items():
        if not k.endswith(".weight"):
            continue
        for side, tags in PAIR_TAGS.items():
            hit = next((t for t in tags if k.endswith(f".{t}.weight")), None)
            if hit:
                # 去掉末尾的 ".<tag>.weight"
                pairs.setdefault(k[: -(len(hit) + len(".weight") + 1)], {})[side] = v
                break
    return {k: v for k, v in pairs.items() if "A" in v and "B" in v}


def compose_delta(A: torch.Tensor, B: torch.Tensor) -> torch.Tensor:
    """
    算出 LoRA 对权重的实际修改量 ΔW（未乘 scaling）。
    踩过的坑：PEFT 对 Conv2d 的 A/B 形状取决于 kernel 大小，**不能假设 A 是 1x1**。
    实测本项目：conv1 的 A=(r,in,3,3)、B=(out,r,1,1)，跟直觉正好反过来。
    """
    Af, Bf = A.float(), B.float()
    if A.dim() == 2:                                   # Linear: A(r,in)  B(out,r)
        return Bf @ Af

    o, r, kb1, kb2 = B.shape
    r2, i, ka1, ka2 = A.shape
    one_a = (ka1, ka2) == (1, 1)
    one_b = (kb1, kb2) == (1, 1)
    if one_b and not one_a:                            # B 是 1x1，A 带卷积核
        return torch.einsum("oc,ciuv->oiuv", Bf.reshape(o, r), Af)
    if one_a and not one_b:                            # A 是 1x1，B 带卷积核
        return torch.einsum("ocuv,ci->oiuv", Bf, Af.reshape(r2, i))
    return torch.einsum("oc,ci->oi", Bf.reshape(o, r), Af.reshape(r2, i))[:, :, None, None]


def delta_norm(A: torch.Tensor, B: torch.Tensor, alpha: float):
    """返回 (||ΔW||_F, rank, scaling)，Linear / Conv2d 都支持"""
    r = A.shape[0]
    scaling = alpha / max(1, r)
    W = compose_delta(A, B)
    return float((scaling * W).norm().item()), r, scaling


def block_of(name: str) -> str:
    n = name.replace("lora_unet_", "").replace("unet.", "")
    for tag in ("down_blocks", "mid_block", "up_blocks", "text_model", "text_encoder"):
        if tag in n:
            return tag
    return "other"


def kind_of(name: str) -> str:
    for tag in ("to_q", "to_k", "to_v", "to_out", "proj_in", "proj_out",
                "conv_shortcut", "conv1", "conv2", "ff", "time_emb_proj", "q_proj",
                "k_proj", "v_proj", "out_proj", "fc1", "fc2"):
        if tag in name:
            return tag
    return "other"


def analyze(path: Path):
    from safetensors.torch import load_file
    sd = load_file(str(path))
    pairs = group_ab(sd)
    if not pairs:
        return None

    alphas = {k[:-len(".alpha")]: float(v) for k, v in sd.items() if k.endswith(".alpha")}

    rows, ranks = [], set()
    for base, ab in pairs.items():
        alpha = alphas.get(base, None)
        A, B = ab["A"], ab["B"]
        r_guess = A.shape[0]
        a_val = alpha if alpha is not None else float(r_guess)
        nrm, r, scaling = delta_norm(A, B, a_val)
        ranks.add(r)
        rows.append({"name": base, "norm": nrm, "block": block_of(base),
                     "kind": kind_of(base), "r": r, "scaling": scaling})

    rows.sort(key=lambda d: -d["norm"])
    total = sum(d["norm"] ** 2 for d in rows) ** 0.5
    return {
        "file": str(path),
        "size_mb": path.stat().st_size / 1e6,
        "n_layers": len(rows),
        "ranks": sorted(ranks),
        "total_norm": total,
        "max_norm": rows[0]["norm"],
        "top": rows[:12],
        "rows": rows,
        "has_text_encoder": any(d["block"].startswith("text") for d in rows),
    }


# --------------------------------------------------------------------------- stats 模式
def cmd_fix(paths):
    """把现有 LoRA 文件里的别名命名统一成 lora_A / lora_B，否则注意力层会被静默丢弃。"""
    from safetensors.torch import load_file, save_file

    n_file = n_key = 0
    for p in paths:
        for f in find_safetensors(Path(p)):
            sd = load_file(str(f))
            changed = sum(1 for k in sd if normalize_key(k) != k)
            if changed == 0:
                print(f"[skip] {f}  已是标准命名")
                continue
            fixed = {normalize_key(k): v for k, v in sd.items()}
            bak = f.with_name(f.stem + ".orig.safetensors")
            if not bak.exists():
                save_file(sd, str(bak))
            save_file(fixed, str(f))
            n_file += 1
            n_key += changed
            print(f"[fix]  {f}\n       改名 {changed} 个 key，原件备份为 {bak.name}")
    print(f"\n[done] 修复 {n_file} 个文件 / {n_key} 个 key")
    if n_file:
        print("      现在用 check_lora.py --stats 复查，层数应该翻倍（UNet 278 层）")


def normalized_or_original(path: Path, out_dir: Path) -> Path:
    """
    加载前自动规范化 key。
    直接用 save_lora_weights 存出来的文件，load_lora_weights 会**静默丢掉**所有注意力层，
    这里自动改名后再交给它，避免“忘了跑 --fix” 导致白测一轮。
    """
    from safetensors.torch import load_file, save_file

    sd = load_file(str(path))
    n_bad = sum(1 for k in sd if normalize_key(k) != k)
    if not n_bad:
        return path
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "_lora_normalized.safetensors"
    save_file({normalize_key(k): v for k, v in sd.items()}, str(dst))
    print(f"[warn] {path.name} 有 {n_bad} 个 key 用了别名命名（直接用会丢掉全部注意力层）")
    print(f"       已自动规范化 -> {dst}")
    return dst


def cmd_stats(paths, top_k, with_json, out_json):
    reports = []
    for p in paths:
        for f in find_safetensors(Path(p)):
            rep = analyze(f)
            if rep is None:
                print(f"[warn] {f} 里没找到 LoRA 权重（lora_A/lora_B）")
                continue
            reports.append(rep)

    if not reports:
        raise SystemExit("没有可分析的 LoRA 文件")

    for i, rep in enumerate(reports):
        print(f"\n{'='*72}")
        print(f"[{i+1}] {rep['file']}")
        print(f"    文件 {rep['size_mb']:.1f} MB | {rep['n_layers']} 层 | rank {rep['ranks']} "
              f"| 含 text encoder: {rep['has_text_encoder']}")
        print(f"    ΔW 总范数 {rep['total_norm']:.4f} | 最大单层 {rep['max_norm']:.4f}")
        block_med = {}
        for d in rep["rows"]:
            block_med.setdefault(d["block"], []).append(d["norm"])
        block_med = {b: sorted(v)[len(v) // 2] for b, v in block_med.items()}

        # 分块汇总：比逐层列表更能看出“风格学在哪”
        tot2 = max(rep["total_norm"] ** 2, 1e-12)
        print("    分块分布（风格应该靠下，集中在 up_blocks=解码器；集中在 encoder 一般不对劲）:")
        agg = {}
        for d in rep["rows"]:
            agg.setdefault(d["block"], []).append(d["norm"])
        for b, ns in sorted(agg.items(), key=lambda kv: -sum(x * x for x in kv[1])):
            t = sum(x * x for x in ns) ** 0.5
            print(f"      {b:<14}{len(ns):>4} 层   ΔW 合范数 {t:>8.4f}   能量占比 {100*t*t/tot2:>5.1f}%")

        print(f"    {'层':<58}{'ΔW范数':>10}")
        for d in rep["top"][:top_k]:
            bm = block_med.get(d["block"], rep["max_norm"])
            flag = "  <<< 比同块中位数高 3 倍以上" if d["norm"] > 3 * bm else ""
            print(f"    {d['name'][:56]:<58}{d['norm']:>10.4f}{flag}")

    if len(reports) > 1:
        print(f"\n{'='*72}")
        print("跨 checkpoint 趋势（ΔW 总范数随时间暴涨 = 典型过拟合信号）")
        base = reports[0]["total_norm"]
        print(f"  {'文件':<52}{'总范数':>10}{'相对首项':>10}")
        for rep in reports:
            print(f"  {Path(rep['file']).parent.name + '/' + Path(rep['file']).name:<52}"
                  f"{rep['total_norm']:>10.4f}{rep['total_norm']/max(base,1e-9):>9.2f}x")
        growth = reports[-1]["total_norm"] / max(base, 1e-9)
        print(f"\n  范数增长 {growth:.2f}x")
        if growth > 2.5:
            print("  权重在持续膨胀。注意：正常训练范数也会涨，不能单凭这个定罪，"
                  "\n  只能说明“越来越离不开 LoRA”，出图时更容易出现 copy 训练图的迹象。")
        else:
            print("  属于正常范围。")
        print("  真正判据仍是「换一个训练集里没有的人，输出还跟不跟随输入」-> --grid")

    if out_json:
        Path(out_json).write_text(json.dumps(
            [{k: v for k, v in r.items() if k != "rows"} for r in reports],
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[out] {out_json}")


# --------------------------------------------------------------------------- grid 模式
def cmd_grid(args):
    import cv2
    import numpy as np
    from PIL import Image
    from diffusers import StableDiffusionImg2ImgPipeline
    from expand_canvas import imread_u, imwrite_u

    lora = Path(args.grid)
    sd_files = find_safetensors(lora)
    if not sd_files:
        raise SystemExit(f"{lora} 下没有 safetensors（要给到包含 pytorch_lora_weights.safetensors 的目录）")
    sd_pick = pick_lora(lora, sd_files)
    if sd_pick.parent != lora:
        print(f"[grid] 该目录下没有直接的 pytorch_lora_weights.safetensors，"
              f"改用 {sd_pick.parent.name}")

    inputs = sorted(p for p in Path(args.inputs).rglob("*")
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"})
    if not inputs:
        raise SystemExit(f"{args.inputs} 下没有图片")
    if args.n and args.n > 0:
        if len(inputs) > args.n:
            print(f"[grid] 找到 {len(inputs)} 张输入图，--n {args.n} 只跑前 {args.n} 张（要全跑加 --n 0）")
        inputs = inputs[:args.n]
    else:
        print(f"[grid] 输入图 {len(inputs)} 张（--n 0 = 全部）")
    print("[grid] 本次使用: " + ", ".join(p.name for p in inputs))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sd_path = normalized_or_original(sd_pick, out)

    pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
        args.base_model, torch_dtype=torch.float16,
        safety_checker=None, requires_safety_checker=False).to("cuda")

    pipe.load_lora_weights(str(sd_path))

    from peft.tuners.lora import LoraLayer
    n_unet = sum(1 for m in pipe.unet.modules() if isinstance(m, LoraLayer))
    n_te = sum(1 for m in pipe.text_encoder.modules() if isinstance(m, LoraLayer))
    print(f"[grid] LoRA      : {sd_path}")
    print(f"[grid] 注入层数  : UNet {n_unet} / TE {n_te}    (rank16 全量目标模块应约 278 / 72)")
    if 0 < n_unet < 200:
        print("[warn] UNet 注入层数偏少，注意力层很可能没加载上 -> 出图会没风格。"
              "先跑: python check_lora.py --fix <lora目录>")
    print(f"[grid] strength  : {args.strength}   weights: {args.weights}")
    print(f"[grid] prompt    : {args.prompt}")
    # diffusers 0.40 起 load_lora_weights 注入的 adapter 名是 'default_0' 而不是 'default'，
    # 写死会 ValueError，所以动态取。
    adapters = []
    for obj in (getattr(pipe, "unet", None), getattr(pipe, "text_encoder", None)):
        cfg = getattr(obj, "peft_config", None)
        if cfg:
            adapters = list(cfg.keys())
            break
    print(f"[grid] adapter   : {adapters}")
    # diffusers 0.40 起 slicing 移到子模块上，新旧写法都试一遍
    for fn in (lambda: pipe.vae.enable_slicing(), lambda: pipe.enable_vae_slicing()):
        try:
            fn()
            break
        except Exception:
            continue

    for n, ip in enumerate(inputs):
        bgr = imread_u(ip)
        if bgr is None:
            continue
        h, w = bgr.shape[:2]
        sc = args.side / max(h, w)
        nw = max(64, int(round(w * sc)) // 8 * 8)
        nh = max(64, int(round(h * sc)) // 8 * 8)
        bgr = cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA)
        pil = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

        cols = [bgr.copy()]
        for wt in args.weights:
            if adapters:
                pipe.set_adapters(adapters, adapter_weights=[float(wt)] * len(adapters))
            g = torch.Generator(device="cuda").manual_seed(args.seed + n)
            img = pipe(prompt=args.prompt, negative_prompt=args.negative, image=pil,
                       strength=args.strength, guidance_scale=args.guidance,
                       num_inference_steps=args.steps, generator=g).images[0]
            cols.append(cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR))
            print(f"[grid] {ip.name}  weight={wt}")

        strip = np.hstack(cols)
        dst = out / f"grid_{ip.stem}.png"
        imwrite_u(dst, strip)
        print(f"[out] {dst}   最左=原始输入，之后依次 weight={args.weights}")

    print("\n怎么看过拟合：")
    print("  1. 换一个训练集里没有的人：输出应该跟着输入变。不同输入出来几乎一样 => 在背训练图。")
    print("  2. weight 拉高后出现训练集里的具体元素（某件衣服 / 某个发型 / 某个背景图案）=> 过拟合。")
    print("  3. weight=0.6~0.8 通常最佳；1.2 以上常常开始糊 + 抄。")
    print("  4. 如果 weight 从 0.6 到 1.2 画面几乎不变，说明这个 LoRA 根本没学到东西（训不足）。")


# --------------------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser("检查 LoRA 过拟合")
    ap.add_argument("--stats", nargs="+", default=None, metavar="PATH",
                    help="分析权重范数（可给多个 checkpoint 看趋势）")
    ap.add_argument("--fix", nargs="+", default=None, metavar="PATH",
                    help="修复存盘命名（把 .lora.down/.up 等统一成 lora_A/B），会先备份")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--json", dest="out_json", default=None)
    ap.add_argument("--grid", default=None, metavar="LORA_PATH", help="出图对比")
    ap.add_argument("--inputs", default=None, help="grid 模式的输入图目录")
    ap.add_argument("--weights", nargs="+", type=float, default=[0.5, 0.65, 0.8, 1.0],
                    help="LoRA 权重。实测有效区间 0.55~0.8，>=1.0 会开始改写性别/人脸")
    ap.add_argument("--n", type=int, default=4, help="grid 模式最多用几张输入；0 = 全部")
    ap.add_argument("--side", type=int, default=768, help="grid 输入长边")
    ap.add_argument("--base_model", default="runwayml/stable-diffusion-v1-5")
    ap.add_argument("--prompt", default="k230style, anime illustration, cel shading, clean lineart, upper body portrait, plain background")
    ap.add_argument("--negative", default="photo, realistic, 3d render, blurry, lowres, watermark, signature, text, logo, extra fingers, bad anatomy")
    ap.add_argument("--strength", type=float, default=0.70,
                    help="img2img 强度。实测 0.58 风格出不来，0.85 会改写身份，0.68~0.72 最佳")
    ap.add_argument("--steps", type=int, default=28)
    ap.add_argument("--guidance", type=float, default=7.0)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--out", default="./lora_grid")
    args = ap.parse_args()

    if args.fix:
        cmd_fix(args.fix)
    elif args.stats:
        cmd_stats(args.stats, args.top, True, args.out_json)
    elif args.grid:
        if not args.inputs:
            raise SystemExit("--grid 需要同时给 --inputs")
        cmd_grid(args)
    else:
        ap.print_help()
        print("\n至少给一个 --stats 或 --grid")


if __name__ == "__main__":
    main()
