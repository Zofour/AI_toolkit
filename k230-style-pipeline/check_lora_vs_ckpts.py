# -*- coding: utf-8 -*-
"""跨 SD1.5 底模的兼容性核验（纯键名/形状比对，不加载权重、不推理、不看图）

做法：把 kohya LoRA 的键还原成模块路径，再去每个底模的 state_dict 键里找对应模块，
统计命中率。命中 = ComfyUI 加载时不会出现 "lora key not loaded"。
"""
import json
import struct

import torch
from safetensors.torch import load_file

LORA = r"D:\Comfy-Desktop\ComfyUI-Shared\models\loras\abcd_style.safetensors"
W = r"C:\Users\yourname\Desktop\else\SD-WEBUI-AKI-V5.0\sd-webui-aki-v4.10\models\Stable-diffusion"
CKPTS = [
    ("cosfMix-v2", W + r"\cosfMix-v2.safetensors"),
    ("Ekmix-gen3", W + r"\Ekmix-gen3.ckpt"),
    ("HD-20-non-ema-fp32", W + r"\HD-20-non-ema-fp32.safetensors"),
    ("dreamlike-diffusion-1.0", W + r"\dreamlike-diffusion-1.0.safetensors"),
    ("anything-v5", W + r"\sd1.5\anything-v5.safetensors"),
]


def model_keys(path):
    if path.lower().endswith(".safetensors"):
        with open(path, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            h = json.loads(f.read(n))
        return [k for k in h if k != "__metadata__"], h
    sd = torch.load(path, map_location="meta", weights_only=True, mmap=True)
    return [k for k in sd if isinstance(k, str)], None


# LoRA 键 -> 模块路径
lora = load_file(LORA)
unet_mods, te_mods = set(), set()
for k in lora:
    if not (k.endswith(".lora_down.weight") or k.endswith(".lora_up.weight")):
        continue
    base = k.rsplit(".lora_", 1)[0]
    if base.startswith("lora_unet_"):
        unet_mods.add(base[len("lora_unet_"):])
    elif base.startswith("lora_te1_"):
        te_mods.add(base[len("lora_te1_"):])
print("LoRA 模块数：UNet %d / CLIP %d" % (len(unet_mods), len(te_mods)))

for name, fp in CKPTS:
    try:
        keys, hdr = model_keys(fp)
    except Exception as e:
        print("%-24s 读取失败 %s" % (name, repr(e)[:60]))
        continue
    norm = set()
    for k in keys:
        p = k
        for pre in ("model.diffusion_model.", "diffusion_model.", "model.", ""):
            if p.startswith(pre):
                p = p[len(pre):]
                break
        for suf in (".weight", ".bias", ".alpha"):
            if p.endswith(suf):
                p = p[:-len(suf)]
                break
        norm.add(p)
    ok_u = sum(1 for m in unet_mods if m in norm)
    ok_t = sum(1 for m in te_mods if ("text_model." + m if not m.startswith("text_model") else m) in norm
               or m in norm)
    # 交叉注意力宽度（判断是否 SD1.5）
    dim = ""
    if hdr:
        for k, v in hdr.items():
            if k.endswith("attn2.to_k.weight") and isinstance(v, dict):
                dim = "attn2.to_k=%s" % v.get("shape")
                break
    verdict = "✔ 全命中" if (ok_u == len(unet_mods) and ok_t == len(te_mods)) else "⚠ 有缺"
    print("%-24s UNet %3d/%-3d  CLIP %2d/%-2d  %-9s %s" %
          (name, ok_u, len(unet_mods), ok_t, len(te_mods), verdict, dim))
