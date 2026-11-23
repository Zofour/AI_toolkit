# -*- coding: utf-8 -*-
"""
train_style_lora.py —— 用风格化参考图训练 SD1.5 风格 LoRA（纯 torch 循环，无 accelerate 依赖）

用法：
    python train_style_lora.py --data .\\expanded\\style --out .\\lora\\style_v1 ^
        --base_model runwayml/stable-diffusion-v1-5 --resolution 512 --rank 16 ^
        --max_steps 1200 --batch 1 --grad_accum 4 --lr_unet 1e-4 --lr_te 1e-5

输出：
    lora/style_v1/pytorch_lora_weights.safetensors   <- pipe.load_lora_weights(该目录) 直接可用
    lora/style_v1/checkpoint-XXXX/                   <- 中途快照（挑不过拟合的那一版）
    lora/style_v1/train_log.json

要点：
  * 只有 6 张风格图时，rank 取 8~16，steps 1000~2000，跑完**必须人眼挑快照**，最容易过拟合。
  * 想省显存：--gradient_checkpointing --resolution 512 --batch 1 --grad_accum 8
  * Blackwell(sm_120) 建议 --mixed_precision bf16（fp16 容易梯度下溢，需要 GradScaler）
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

try:                                  # Pillow 版本兼容
    RESAMPLE = Image.Resampling
except AttributeError:                # pragma: no cover
    RESAMPLE = Image

UNET_TARGETS = [
    "to_k", "to_q", "to_v", "to_out.0",
    "proj_in", "proj_out", "ff.net.0.proj", "ff.net.2",
    "conv1", "conv2", "conv_shortcut",
    "downsamplers.0.conv", "upsamplers.0.conv", "time_emb_proj",
]
TE_TARGETS = ["q_proj", "k_proj", "v_proj", "out_proj", "fc1", "fc2"]


# --------------------------------------------------------------------------- 数据
class StyleDataset(Dataset):
    """每张图配一句 caption：优先读同名 .txt，否则用统一模板（风格 LoRA 推荐统一模板）。"""

    def __init__(self, root, res, tokenizer, caption_template, flip=True, jitter=0.15):
        self.paths = sorted(p for p in Path(root).rglob("*") if p.suffix.lower() in IMG_EXT)
        if not self.paths:
            raise SystemExit(f"没有找到图片: {root}")
        self.res = int(res)
        self.tok = tokenizer
        self.flip = flip
        self.jitter = jitter
        self.captions = []
        for p in self.paths:
            txt = p.with_suffix(".txt")
            self.captions.append(txt.read_text(encoding="utf-8").strip()
                                 if txt.exists() else caption_template)
        print(f"[data] {len(self.paths)} 张图，分辨率 {self.res}，caption 示例: {self.captions[0][:90]}")

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        im = Image.open(self.paths[i]).convert("RGB")
        w, h = im.size
        sc = self.res / min(w, h) * random.uniform(1.0, 1.0 + self.jitter)
        nw, nh = max(self.res, int(round(w * sc))), max(self.res, int(round(h * sc)))
        im = im.resize((nw, nh), RESAMPLE.LANCZOS)
        x = random.randint(0, nw - self.res)
        y = random.randint(0, nh - self.res)
        im = im.crop((x, y, x + self.res, y + self.res))
        if self.flip and random.random() < 0.5:
            im = im.transpose(Image.FLIP_LEFT_RIGHT)

        arr = np.asarray(im, dtype=np.float32) / 127.5 - 1.0
        pix = torch.from_numpy(arr).permute(2, 0, 1).contiguous()
        ids = self.tok(self.captions[i], truncation=True, padding="max_length",
                       max_length=self.tok.model_max_length,
                       return_tensors="pt").input_ids[0]
        return {"pixel_values": pix, "input_ids": ids}


# --------------------------------------------------------------------------- 工具
def convert_sd(unet, te, train_te):
    """把 peft 的 state dict 转成 diffusers LoRA 格式"""
    from peft.utils import get_peft_model_state_dict
    try:
        from diffusers.utils import convert_state_dict_to_diffusers
    except ImportError:                                   # 老版本路径
        from diffusers.utils.state_dict_utils import convert_state_dict_to_diffusers

    unet_sd = convert_state_dict_to_diffusers(get_peft_model_state_dict(unet))
    te_sd = convert_state_dict_to_diffusers(get_peft_model_state_dict(te)) if train_te else None
    return unet_sd, te_sd


def normalize_key(k: str) -> str:
    """
    统一 LoRA key 命名。**这步不能省。**

    diffusers 的 save_lora_weights 会同时吐出三套命名：
        <m>.lora_A.weight                  / .lora_B.weight
        <m>.lora.down.weight               / .lora.up.weight               (UNet 注意力)
        <m>.lora_linear_layer.down.weight  / .up.weight                   (TE 注意力)
    而 load_lora_weights 认不全 —— 实测 UNet 的 278 层只加载了 150 层，
    128 层注意力 LoRA 被**静默丢弃**：不报错、不警告，只是没生效。
    """
    return (k.replace(".lora_linear_layer.down.", ".lora_A.")
             .replace(".lora_linear_layer.up.", ".lora_B.")
             .replace(".lora.down.", ".lora_A.")
             .replace(".lora.up.", ".lora_B.")
             .replace(".lora_down.", ".lora_A.")
             .replace(".lora_up.", ".lora_B."))


def save_lora(out_dir: Path, unet_sd, te_sd):
    """直接写 safetensors，不走 save_lora_weights，保证 key 命名统一"""
    from safetensors.torch import save_file

    out_dir.mkdir(parents=True, exist_ok=True)
    merged = {}
    for prefix, sd in (("unet", unet_sd), ("text_encoder", te_sd)):
        for k, v in (sd or {}).items():
            merged[f"{prefix}.{normalize_key(k)}"] = v.detach().float().contiguous()
    p = out_dir / "pytorch_lora_weights.safetensors"
    save_file(merged, str(p), metadata={"format": "pt"})
    return p


def parse():
    ap = argparse.ArgumentParser("训练风格 LoRA")
    ap.add_argument("--data", required=True, help="风格图目录（递归）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--base_model", default="runwayml/stable-diffusion-v1-5")
    ap.add_argument("--resolution", type=int, default=512)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--lora_alpha", type=int, default=None, help="默认 = rank")
    ap.add_argument("--max_steps", type=int, default=1200)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--grad_accum", type=int, default=4)
    ap.add_argument("--lr_unet", type=float, default=1e-4)
    ap.add_argument("--lr_te", type=float, default=1e-5)
    ap.add_argument("--weight_decay", type=float, default=1e-2)
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--lr_scheduler", default="cosine", choices=["linear", "cosine", "constant"])
    ap.add_argument("--train_text_encoder", action="store_true",
                    help="同时训练 text encoder LoRA（风格 LoRA 建议开，显存 +1G）")
    ap.add_argument("--caption", default="k230style, anime illustration, cel shading, clean lineart, flat color, upper body portrait, plain background",
                    help="统一 caption（仅当图片旁边没有同名 .txt 时用这个）。风格词必须与各 .txt 保持一致")
    ap.add_argument("--noise_offset", type=float, default=0.05)
    ap.add_argument("--mixed_precision", default="bf16", choices=["no", "fp16", "bf16"])
    ap.add_argument("--gradient_checkpointing", action="store_true", default=True)
    ap.add_argument("--no_gradient_checkpointing", dest="gradient_checkpointing", action="store_false")
    ap.add_argument("--save_every", type=int, default=300, help="每隔多少步存一个快照")
    ap.add_argument("--log_every", type=int, default=20)
    ap.add_argument("--workers", type=int, default=0, help="Windows 上建议 0")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--preview", action="store_true", help="训练结束后用 LoRA 生成预览图")
    ap.add_argument("--preview_image", default=None, help="预览用输入图（img2img）；不给则用第一张风格图")
    ap.add_argument("--preview_prompt", default=None)
    args = ap.parse_args()
    if args.lora_alpha is None:
        args.lora_alpha = args.rank
    return args


# --------------------------------------------------------------------------- 主流程
def main():
    a = parse()
    torch.manual_seed(a.seed)
    random.seed(a.seed)
    np.random.seed(a.seed)

    from diffusers import AutoencoderKL, DDPMScheduler, UNet2DConditionModel
    from diffusers.optimization import get_scheduler
    from peft import LoraConfig
    from transformers import CLIPTextModel, CLIPTokenizer

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if dev == "cpu":
        print("[warn] 未检测到 CUDA —— LoRA 训练在 CPU 上基本不可用，请先装 CUDA 版 torch")
    dtype = {"no": torch.float32, "fp16": torch.float16, "bf16": torch.bfloat16}[a.mixed_precision]
    if dev == "cpu":
        dtype = torch.float32

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    print(f"[env] device={dev} dtype={dtype} rank={a.rank} alpha={a.lora_alpha} steps={a.max_steps}")

    tokenizer = CLIPTokenizer.from_pretrained(a.base_model, subfolder="tokenizer")
    text_encoder = CLIPTextModel.from_pretrained(a.base_model, subfolder="text_encoder")
    vae = AutoencoderKL.from_pretrained(a.base_model, subfolder="vae")
    unet = UNet2DConditionModel.from_pretrained(a.base_model, subfolder="unet")
    noise_scheduler = DDPMScheduler.from_pretrained(a.base_model, subfolder="scheduler")

    ds = StyleDataset(a.data, a.resolution, tokenizer, a.caption)
    if len(ds) < 4:
        print(f"[warn] 只有 {len(ds)} 张风格图，LoRA 会很容易过拟合，建议 10 张以上")

    # ---- LoRA 注入
    unet.requires_grad_(False)
    unet.add_adapter(LoraConfig(r=a.rank, lora_alpha=a.lora_alpha,
                                init_lora_weights="gaussian", target_modules=UNET_TARGETS))
    text_encoder.requires_grad_(False)
    if a.train_text_encoder:
        text_encoder.add_adapter(LoraConfig(r=a.rank, lora_alpha=a.lora_alpha,
                                            init_lora_weights="gaussian", target_modules=TE_TARGETS))

    vae_dtype = torch.float32 if dtype == torch.float16 else dtype
    vae.to(dev, dtype=vae_dtype).eval()
    unet.to(dev, dtype=dtype)
    text_encoder.to(dev, dtype=dtype)

    if a.gradient_checkpointing:
        unet.enable_gradient_checkpointing()
        if a.train_text_encoder:
            text_encoder.gradient_checkpointing_enable()

    groups = [{"params": [p for p in unet.parameters() if p.requires_grad], "lr": a.lr_unet}]
    if a.train_text_encoder:
        groups.append({"params": [p for p in text_encoder.parameters() if p.requires_grad],
                       "lr": a.lr_te})
    n_train = sum(p.numel() for g in groups for p in g["params"])
    print(f"[model] 可训练参数 {n_train/1e6:.2f} M")
    opt = torch.optim.AdamW(groups, betas=(0.9, 0.999), weight_decay=a.weight_decay, eps=1e-8)
    sched = get_scheduler(a.lr_scheduler, optimizer=opt,
                          num_warmup_steps=a.warmup, num_training_steps=a.max_steps)

    loader = DataLoader(ds, batch_size=a.batch, shuffle=True, drop_last=True,
                        num_workers=a.workers, pin_memory=(dev == "cuda"))
    unet.train()
    text_encoder.train(a.train_text_encoder)

    hist, step, t0 = [], 0, time.time()
    running = 0.0
    opt.zero_grad(set_to_none=True)

    def snapshot(tag):
        unet_sd, te_sd = convert_sd(unet, text_encoder, a.train_text_encoder)
        p = save_lora(out / tag if tag != "final" else out, unet_sd, te_sd)
        print(f"[save] {p}")

    while step < a.max_steps:
        for batch in loader:
            if step >= a.max_steps:
                break
            x = batch["pixel_values"].to(dev, dtype=vae_dtype)
            ids = batch["input_ids"].to(dev)

            with torch.no_grad():
                lat = vae.encode(x).latent_dist.sample() * vae.config.scaling_factor
            lat = lat.to(dtype)

            noise = torch.randn_like(lat)
            if a.noise_offset > 0:
                noise = noise + a.noise_offset * torch.randn(
                    (lat.shape[0], lat.shape[1], 1, 1), device=lat.device, dtype=lat.dtype)

            ts = torch.randint(0, noise_scheduler.config.num_train_timesteps,
                               (lat.shape[0],), device=dev).long()
            noisy = noise_scheduler.add_noise(lat, noise, ts)

            if a.train_text_encoder:
                enc = text_encoder(ids)[0].to(dtype)
            else:
                with torch.no_grad():
                    enc = text_encoder(ids)[0].to(dtype)

            pred = unet(noisy, ts, enc, return_dict=False)[0]
            target = (noise_scheduler.get_velocity(lat, noise, ts)
                      if noise_scheduler.config.prediction_type == "v_prediction" else noise)

            loss = F.mse_loss(pred.float(), target.float())
            (loss / a.grad_accum).backward()
            running += float(loss.detach())

            if (step + 1) % a.grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(
                    [p for g in groups for p in g["params"]], 1.0)
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)

            step += 1
            if step % a.log_every == 0:
                avg = running / a.log_every
                running = 0.0
                spd = (time.time() - t0) / step
                eta = spd * (a.max_steps - step) / 60
                print(f"[{step:>5}/{a.max_steps}] loss={avg:.4f}  {spd:.2f}s/step  ETA {eta:.0f}min")
                hist.append({"step": step, "loss": avg})
            if a.save_every and step % a.save_every == 0:
                snapshot(f"checkpoint-{step}")

    snapshot("final")
    (out / "train_log.json").write_text(json.dumps(
        {"args": vars(a), "history": hist, "trainable_params": n_train},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[done] LoRA -> {out.resolve()}\\pytorch_lora_weights.safetensors")

    if a.preview:
        preview(a, out)


# --------------------------------------------------------------------------- 预览
def preview(a, out: Path):
    print("[preview] 加载 pipeline 生成预览图 ...")
    import gc

    import torch
    prompt = a.preview_prompt or a.caption
    img = a.preview_image
    if img is None:
        imgs = sorted(p for p in Path(a.data).rglob("*") if p.suffix.lower() in IMG_EXT)
        if not imgs:
            print("[preview] 找不到可用输入图，跳过")
            return
        img = str(imgs[0])
    print(f"[preview] 输入 {img}")

    from diffusers import StableDiffusionImg2ImgPipeline

    pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
        a.base_model, torch_dtype=torch.float16,
        safety_checker=None, requires_safety_checker=False).to("cuda")
    pipe.load_lora_weights(str(out))
    try:
        pipe.set_adapters(["default"], adapter_weights=[0.85])
    except Exception:
        pass
    for fn in (lambda: pipe.vae.enable_slicing(), lambda: pipe.enable_vae_slicing()):
        try:
            fn()
            break
        except Exception:
            continue

    from PIL import Image as PILImage
    src = PILImage.open(img).convert("RGB")
    g = torch.Generator(device="cuda").manual_seed(a.seed)
    res = pipe(prompt=prompt, image=src, strength=0.6, guidance_scale=7.0,
               num_inference_steps=30, generator=g).images[0]
    p = out / "preview.jpg"
    res.save(p)
    print(f"[preview] {p}")


if __name__ == "__main__":
    main()
