# -*- coding: utf-8 -*-
"""
train_distill.py —— 把 teacher 造出来的 (input, target) 蒸馏成 K230 可跑的前馈学生网络

设计约束（全部来自 K230 / nncase 白名单，改网络前先读这里）：
  * 只用 Conv2d / BatchNorm2d / LeakyReLU / Add / Concat / Resize / Sigmoid
  * 绝对不用 InstanceNorm / GroupNorm / ConvTranspose / GridSample / GELU
  * 上采样 = F.interpolate(nearest) + Conv
  * 倒残差末端线性（不接激活）
  * BN 在导出前折叠进 Conv，所以训练时随便用
  * 输入 3 通道（不接 mask）。板端 AI2D 只能处理单源 uint8，4 通道要跑两次 AI2D 再拼，慢且易错。
    "只改人物"这件事由 target 本身教（mask 外 target == input）

用法：
    python train_distill.py --pairs C:\\chatbox_temp\\work\\m1 --out .\\work\\student ^
        --hw 768 608 --epochs 60 --batch 4 --workers 4

快测：
    python train_distill.py --pairs ... --out .\\dbg --hw 192 160 --epochs 2 --limit 24 --workers 0
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset


# =========================================================================== IO
def _imread_rgb(path) -> np.ndarray:
    """支持中文路径；返回 RGB uint8"""
    data = np.fromfile(str(path), dtype=np.uint8)
    im = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if im is None:
        raise IOError(f"读图失败: {path}")
    return cv2.cvtColor(im, cv2.COLOR_BGR2RGB)


def imwrite_u(path, bgr):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if ok:
        buf.tofile(str(path))


# =========================================================================== 网络
class InvertedResidual(nn.Module):
    """MobileNetV2 倒残差。末端线性（linear bottleneck），这对暗部色调和 KPU 都友好。"""

    def __init__(self, ci, co, stride=1, expand=2):
        super().__init__()
        mid = ci * expand
        self.skip = (stride == 1 and ci == co)
        layers = []
        if expand != 1:
            layers += [nn.Conv2d(ci, mid, 1, bias=False),
                       nn.BatchNorm2d(mid), nn.LeakyReLU(0.1, inplace=True)]
        layers += [nn.Conv2d(mid, mid, 3, stride, 1, groups=mid, bias=False),
                   nn.BatchNorm2d(mid), nn.LeakyReLU(0.1, inplace=True),
                   nn.Conv2d(mid, co, 1, bias=False),
                   nn.BatchNorm2d(co)]
        self.conv = nn.Sequential(*layers)

    def forward(self, x):
        y = self.conv(x)
        return x + y if self.skip else y


class Up(nn.Module):
    """Resize(nearest) + Conv。绝不用 ConvTranspose。"""

    def __init__(self, ci, co):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(ci, co, 3, 1, 1, bias=False),
            nn.BatchNorm2d(co), nn.LeakyReLU(0.1, inplace=True))

    def forward(self, x):
        return self.conv(F.interpolate(x, scale_factor=2, mode="nearest"))


class StudentNet(nn.Module):
    """
    3 通道进、3 通道出。输入 H,W 必须能被 32 整除（5 次下采样）。
    编码器 1/2 → 1/32，解码器 5 次上采样回原尺寸，4 级 skip。
    """

    def __init__(self, base=32, chs=(32, 64, 96, 160, 320), in_skip=False):
        super().__init__()
        self.in_skip = bool(in_skip)   # ★ 把原图以 1/1 直接接进 head，增量可内容自适应
        c1, c2, c3, c4, c5 = chs
        f = max(1, base // 32)                       # base=32 时为 1
        c1, c2, c3, c4, c5 = [c * f for c in chs]

        self.stem = nn.Sequential(                    # 1/2
            nn.Conv2d(3, c1, 3, 2, 1, bias=False),
            nn.BatchNorm2d(c1), nn.LeakyReLU(0.1, inplace=True))
        self.enc1 = nn.Sequential(InvertedResidual(c1, c1), InvertedResidual(c1, c1))          # 1/2
        self.enc2 = nn.Sequential(InvertedResidual(c1, c2, 2), InvertedResidual(c2, c2))       # 1/4
        self.enc3 = nn.Sequential(InvertedResidual(c2, c3, 2),                                   # 1/8
                                  InvertedResidual(c3, c3), InvertedResidual(c3, c3))
        self.enc4 = nn.Sequential(InvertedResidual(c3, c4, 2),                                   # 1/16
                                  InvertedResidual(c4, c4), InvertedResidual(c4, c4))
        self.enc5 = nn.Sequential(InvertedResidual(c4, c5, 2),                                   # 1/32
                                  InvertedResidual(c5, c5), InvertedResidual(c5, c5))

        self.up1 = Up(c5, c4)      # 1/16
        self.up2 = Up(c4 + c4, c3)  # 1/8  (concat skip4)
        self.up3 = Up(c3 + c3, c2)  # 1/4  (concat skip3)
        self.up4 = Up(c2 + c2, c1)  # 1/2  (concat skip2)
        self.up5 = Up(c1 + c1, c1)  # 1/1  (concat skip1)

        self.head = nn.Sequential(
            nn.Conv2d(c1 + (3 if self.in_skip else 0), c1, 3, 1, 1, bias=False),
            nn.BatchNorm2d(c1), nn.LeakyReLU(0.1, inplace=True),
            nn.Conv2d(c1, 3, 3, 1, 1))
        nn.init.zeros_(self.head[-1].bias)

    def forward(self, x):
        s1 = self.enc1(self.stem(x))         # 1/2
        s2 = self.enc2(s1)                   # 1/4
        s3 = self.enc3(s2)                   # 1/8
        s4 = self.enc4(s3)                   # 1/16
        b = self.enc5(s4)                    # 1/32

        d = self.up1(b)                      # 1/16
        d = self.up2(torch.cat([d, s4], 1))  # 1/8
        d = self.up3(torch.cat([d, s3], 1))  # 1/4
        d = self.up4(torch.cat([d, s2], 1))  # 1/2
        d = self.up5(torch.cat([d, s1], 1))  # 1/1
        if self.in_skip:
            d = torch.cat([d, x], 1)         # ★ 1/1 输入 skip：head 直接拿到全分辨率原图
        out = torch.tanh(self.head(d))
        if getattr(self, "residual", False):          # 残差学习：out = 输入 + 增量
            out = torch.clamp(x + out, -1.0, 1.0)     # clamp 保证 [-1,1]，量化/导出都安全
        return out


# =========================================================================== 感知损失
class VGG19Feat(nn.Module):
    """
    取 4 层：relu1_2 / relu2_2 / relu3_3 / relu4_4。

    为什么必须带上早期层：原来只取 relu3_3/relu4_4，而感知损失又在 320px 下算，
    于是 relu4_4 只有 10x8 的特征图 —— **线稿这种像素级高频信息在损失里完全不可见**，
    学生只能学成“平滑照片”。加上 relu1_2（全尺寸下 384x304）才能监督到线条。
    代价：显存和耗时上升（早期层特征图很大），用 perc_size 控制。
    """

    def __init__(self, layers=(3, 8, 15, 26)):   # relu1_2, relu2_2, relu3_3, relu4_4
        super().__init__()
        import torchvision

        vgg = torchvision.models.vgg19(weights=torchvision.models.VGG19_Weights.IMAGENET1K_V1)
        feats = list(vgg.features.children())
        self.blocks = nn.ModuleList()
        prev = 0
        for l in layers:
            self.blocks.append(nn.Sequential(*feats[prev:l + 1]))
            prev = l + 1
        for p in self.parameters():
            p.requires_grad_(False)
        self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))
        self.n = len(layers)

    def forward(self, x):                       # x ∈ [-1,1]
        x = (x + 1) / 2
        x = (x - self.mean) / self.std
        outs = []
        for b in self.blocks:
            x = b(x)
            outs.append(x)
        return outs


def strong_edge_frac(t, thr=1.0):
    """
    “强边缘像素占比”，用来量化描边/线稿。

    为什么不用 Sobel 均值：实测老师的边缘能量**均值**和原照片几乎一样
    （18.5 vs 18.2）——因为均值被大量细小梯度主导，分辨不出线稿。
    线稿是“少数像素 + 极强梯度”，所以要看高百分位/阈值以上的比例。
    t 在 [-1,1]，thr=1.0 大致对应 255 尺度下的 128，只统计真正的描边。
    """
    return (sobel_mag(t) > thr).float().mean()


def sobel_mag(t):
    """
    梯度幅值图（对亮度通道算 Sobel）。用于**显式的线稿/边缘损失**。
    线稿本质上是强边缘，L1 像素损失对它的梯度会被大面积的平坦区域淹没，
    单独拉一条边缘损失是最直接的监督。
    """
    kx = torch.tensor([[-1., 0., 1.], [-2., 0., 2.], [-1., 0., 1.]],
                      dtype=t.dtype, device=t.device).view(1, 1, 3, 3)
    ky = kx.transpose(-1, -2)
    g = t.mean(1, keepdim=True)
    g = F.pad(g, (1, 1, 1, 1), mode="replicate")
    gx = F.conv2d(g, kx)
    gy = F.conv2d(g, ky)
    return torch.sqrt(gx * gx + gy * gy + 1e-6)


def gram(f, m=None):
    b, c, h, w = f.shape
    if m is not None:
        f = f * m
    f = f.reshape(b, c, h * w)
    return f @ f.transpose(1, 2) / (c * h * w)


def wl1(a, b, m):
    """按 mask 加权的 L1（m: (B,1,h,w)）"""
    c = a.shape[1]
    return (torch.abs(a - b) * m).sum() / (m.sum() * c + 1e-6)


def mask_at(m, feat):
    return F.interpolate(m, size=feat.shape[-2:], mode="area")


# =========================================================================== 数据
class PairDataset(Dataset):
    def __init__(self, root, hw, names=None, flip=True, allow_resize=False):
        self.root = Path(root)
        self.hw = tuple(hw)
        self.allow_resize = allow_resize
        all_names = sorted(p.stem for p in (self.root / "target").glob("*.png"))
        self.names = [n for n in all_names if (names is None or n in names)]
        self.flip = flip
        if not self.names:
            raise SystemExit(f"{root} 下没有可用样本")

    def __len__(self):
        return len(self.names)

    def __getitem__(self, i):
        n = self.names[i]
        H, W = self.hw
        x = _imread_rgb(self.root / "input" / f"{n}.png")
        y = _imread_rgb(self.root / "target" / f"{n}.png")
        m = cv2.imdecode(np.fromfile(str(self.root / "mask" / f"{n}.png"), np.uint8),
                         cv2.IMREAD_GRAYSCALE)
        if x.shape[:2] != (H, W):
            ar_src = x.shape[1] / x.shape[0]
            ar_dst = W / H
            if not self.allow_resize and abs(ar_src - ar_dst) / max(ar_src, ar_dst) > 0.03:
                raise SystemExit(
                    f"\n[致命] 数据形状与 --hw 不匹配，且长宽比差很多：\n"
                    f"        源图 {x.shape[1]}x{x.shape[0]} (宽x高, 比例 {ar_src:.3f})\n"
                    f"        目标 {W}x{H}       (宽x高, 比例 {ar_dst:.3f})\n"
                    f"  直接 resize 会把人物**压扁变形**，而且训练不会报错、loss 照样降，"
                    f"你拿到的是一个系统性变形的模型。\n"
                    f"  正确做法：用 gen_m1.py 按新尺寸重新生成数据（约 2~3 小时）；\n"
                    f"  只做纯尺度缩放（比如快速测试 --hw 192 160）请显式加 --allow_resize\n")
            x = cv2.resize(x, (W, H), interpolation=cv2.INTER_AREA)
            y = cv2.resize(y, (W, H), interpolation=cv2.INTER_AREA)
            m = cv2.resize(m, (W, H), interpolation=cv2.INTER_AREA)
        if self.flip and np.random.rand() < 0.5:
            x, y, m = x[:, ::-1], y[:, ::-1], m[:, ::-1]

        to_t = lambda a: torch.from_numpy(np.ascontiguousarray(
            a.astype(np.float32).transpose(2, 0, 1) / 127.5 - 1.0))
        t = lambda a: torch.from_numpy(np.ascontiguousarray(a.astype(np.float32) / 255.0))
        return to_t(x), to_t(y), t(m).unsqueeze(0)


# =========================================================================== BN 折叠（导出用）
def fuse_bn(model):
    from torch.nn.utils.fusion import fuse_conv_bn_eval

    def walk(mod):
        for name, child in mod.named_children():
            if isinstance(child, nn.Sequential):
                kids, out, i = list(child.named_children()), [], 0
                while i < len(kids):
                    n, k = kids[i]
                    if (isinstance(k, nn.Conv2d) and i + 1 < len(kids)
                            and isinstance(kids[i + 1][1], nn.BatchNorm2d)):
                        out.append((n, fuse_conv_bn_eval(k, kids[i + 1][1])))
                        i += 2
                    else:
                        out.append((n, k))
                        i += 1
                setattr(mod, name, nn.Sequential(OrderedDict(out)))
                walk(getattr(mod, name))
            else:
                walk(child)
    m = model.eval()
    with torch.no_grad():
        walk(m)
    return m


# =========================================================================== 训练
def parse():
    ap = argparse.ArgumentParser("蒸馏训练 KPU 友好学生网络")
    ap.add_argument("--pairs", required=True, help="gen_m1.py 的输出目录（含 input/target/mask）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--hw", type=int, nargs=2, default=[768, 608], help="高 宽，必须能被 32 整除")
    ap.add_argument("--base", type=int, default=32, help="网络宽度基准")
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--grad_accum", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--workers", type=int, default=4, help="Windows 上若报错就改 0")
    ap.add_argument("--amp", default="bf16", choices=["no", "fp16", "bf16"])
    ap.add_argument("--limit", type=int, default=0, help="只用前 N 对（调试）")
    ap.add_argument("--allow_resize", action="store_true",
                    help="允许在长宽比不一致时直接缩放数据（会压扁人物）。默认禁止并报错；"
                         "只在 --hw 192 160 这类快速测试时加")
    ap.add_argument("--val_frac", type=float, default=0.05)
    ap.add_argument("--drop_outliers", action="store_true", default=True,
                    help="丢掉 report.json 标出的风格离群样本")
    ap.add_argument("--keep_outliers", dest="drop_outliers", action="store_false")
    ap.add_argument("--w_pix", type=float, default=1.0)
    ap.add_argument("--w_perc", type=float, default=1.0, help="VGG 特征对 teacher 的 L1")
    ap.add_argument("--w_content", type=float, default=0.1,
                    help="VGG relu4_4 对输入的 L1（结构锚）。调太高会把学生锁在“照片”上，出不来线稿")
    ap.add_argument("--w_line", type=float, default=2.0,
                    help="★ 全分辨率 Sobel 梯度幅值 L1，直接监督线稿/边缘。线稿风格的命门")
    ap.add_argument("--w_style", type=float, default=2.0, help="Gram 对数据集均值 Gram")
    ap.add_argument("--perc_size", type=int, default=512,
                    help="感知/风格损失的分辨率（长边）。0=不降。太小会让线稿在损失里消失，"
                         "512 是速度与效果的折中")
    ap.add_argument("--w_adv", type=float, default=0.0, help="对抗项；有配对 teacher 时一般不需要，开了容易出伪影")
    ap.add_argument("--adv_start", type=int, default=2000, help="多少步后才开始对抗")
    ap.add_argument("--bg_weight", type=float, default=0.2, help="mask 外区域的损失权重")
    ap.add_argument("--log_every", type=int, default=20)
    ap.add_argument("--sample_every", type=int, default=500)
    ap.add_argument("--save_every", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--init", default=None,
                    help="从已有 student.pth 续训（微调）；权重形状不兼容时自动跳过不匹配的层")
    ap.add_argument("--residual", action="store_true",
                    help="残差学习：out = 输入 + 网络增量（风格化任务里通常显著提锐，量化导出也安全）")
    ap.add_argument("--in_skip", action="store_true",
                    help="★ 把输入以 1/1 skip 接进 head（全分辨率、内容自适应的增量，显著提锐）")
    a = ap.parse_args()
    H, W = a.hw
    if H % 32 or W % 32:
        raise SystemExit(f"--hw {H} {W} 必须都能被 32 整除（输入要下采样 5 次）")
    return a


class PatchD(nn.Module):
    def __init__(self, ndf=48, n_layers=3):
        super().__init__()
        L = [nn.Conv2d(3, ndf, 4, 2, 1), nn.LeakyReLU(0.2, True)]
        m = 1
        for i in range(1, n_layers):
            pm, m = m, min(2 ** i, 8)
            L += [nn.Conv2d(ndf * pm, ndf * m, 4, 2, 1, bias=False),
                  nn.InstanceNorm2d(ndf * m, affine=True), nn.LeakyReLU(0.2, True)]
        # ★ m 必须沿用循环里最后一次的值（=min(2**(n_layers-1),8)=4）。
        #   之前这里又写了一遍 m = min(2**n_layers, 8) 把它重新算成 8，
        #   于是中间层变成 384 而上一层只输出 192，一启用判别器就崩。
        L += [nn.Conv2d(ndf * m, ndf * m, 4, 1, 1, bias=False),
              nn.InstanceNorm2d(ndf * m, affine=True), nn.LeakyReLU(0.2, True),
              nn.Conv2d(ndf * m, 1, 4, 1, 1)]
        self.net = nn.Sequential(*L)         # 注意：判别器不上板，用 InstanceNorm 无所谓

    def forward(self, x):
        return self.net(x)


def main():
    a = parse()
    torch.manual_seed(a.seed)
    np.random.seed(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = {"no": torch.float32, "fp16": torch.float16, "bf16": torch.bfloat16}[a.amp]
    if dev == "cpu":
        dtype = torch.float32
    out = Path(a.out)
    (out / "samples").mkdir(parents=True, exist_ok=True)
    print(f"[env] device={dev} dtype={dtype} 输入 {a.hw[0]}x{a.hw[1]} base={a.base}")

    # ---- 选样本
    root = Path(a.pairs)
    names = sorted(p.stem for p in (root / "target").glob("*.png"))
    if a.limit:
        names = names[:a.limit]
    rp = root / "report.json"
    if a.drop_outliers and rp.exists():
        rep = json.loads(rp.read_text(encoding="utf-8"))
        bad = {x["idx"] for x in rep["items"] if x.get("style_outlier")}
        before = len(names)
        names = [n for n in names if n not in bad]
        print(f"[data] 丢掉风格离群 {before - len(names)} 张")
    n_val = max(1, int(len(names) * a.val_frac))
    rng = np.random.RandomState(a.seed)
    idx = rng.permutation(len(names))
    val_names = [names[i] for i in idx[:n_val]]
    tr_names = [names[i] for i in idx[n_val:]]
    print(f"[data] 训练 {len(tr_names)} / 验证 {len(val_names)}")

    ds_tr = PairDataset(root, a.hw, tr_names, allow_resize=a.allow_resize)
    ds_va = PairDataset(root, a.hw, val_names, flip=False, allow_resize=a.allow_resize)
    dl_tr = DataLoader(ds_tr, batch_size=a.batch, shuffle=True, drop_last=True,
                       num_workers=a.workers, pin_memory=(dev == "cuda"),
                       persistent_workers=(a.workers > 0))
    dl_va = DataLoader(ds_va, batch_size=2, shuffle=False, num_workers=0)

    # ---- 模型
    net = StudentNet(base=a.base, in_skip=bool(getattr(a, "in_skip", False))).to(dev, dtype=dtype)
    if a.init:
        sd = torch.load(a.init, map_location="cpu")
        if isinstance(sd, dict) and "model" in sd and isinstance(sd["model"], dict):
            sd = sd["model"]
        cur = net.state_dict()
        fit = {k: v for k, v in sd.items() if k in cur and cur[k].shape == v.shape}
        skip = len(sd) - len(fit)
        net.load_state_dict(fit, strict=False)
        print(f"[init] 从 {a.init} 载入 {len(fit)} 层（跳过 {skip} 层形状不匹配）")
    if getattr(net, "in_skip", False):
        print("[model] 已启用 1/1 输入 skip（head 直接看到原图）")
    net.residual = bool(getattr(a, "residual", False))
    if net.residual:
        print("[model] 残差学习已开启：out = 输入 + 网络输出")
    n_par = sum(p.numel() for p in net.parameters())
    print(f"[model] StudentNet 参数量 {n_par/1e6:.2f} M")

    vgg = VGG19Feat().to(dev, dtype=dtype).eval()
    disc = PatchD().to(dev, dtype=dtype) if a.w_adv > 0 else None

    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, betas=(0.9, 0.99), weight_decay=1e-4)
    opt_d = torch.optim.AdamW(disc.parameters(), lr=a.lr, betas=(0.5, 0.999)) if disc else None

    steps_per_epoch = max(1, len(dl_tr) // a.grad_accum)
    total_steps = steps_per_epoch * a.epochs
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=total_steps, eta_min=a.lr * 0.05)
    print(f"[train] {steps_per_epoch} step/epoch × {a.epochs} epoch = {total_steps} step；"
          f"batch {a.batch} × accum {a.grad_accum} = 有效 {a.batch*a.grad_accum}")

    # ---- 感知/风格损失的低分辨率尺寸（必须在用到 rz 之前定义）
    H_, W_ = a.hw
    if a.perc_size and max(H_, W_) > a.perc_size:
        sc = a.perc_size / max(H_, W_)
        ph = max(16, int(round(H_ * sc / 16)) * 16)
        pw = max(16, int(round(W_ * sc / 16)) * 16)
    else:
        ph, pw = H_, W_

    def rz(t):
        return t if (ph, pw) == (H_, W_) else F.interpolate(t, size=(ph, pw), mode="area")
    print(f"[perc] 感知损失分辨率 {ph}x{pw}")

    # ---- 风格目标：teacher 的均值 Gram
    style_target = None
    if a.w_style > 0:
        with torch.no_grad():
            acc, cnt = None, 0
            for y, _, _ in [ds_va[i] for i in range(len(ds_va))]:
                f = vgg(rz(y.unsqueeze(0).to(dev, dtype=dtype)))[-1]
                g = gram(f)[0]
                acc = g if acc is None else acc + g
                cnt += 1
            style_target = (acc / cnt).detach()
        print(f"[style] 用 {cnt} 张验证图算出均值 Gram，shape {tuple(style_target.shape)}")

    def run_vgg(t):
        return vgg(t.to(dtype=dtype))


    step = 0
    t0 = time.time()
    log_acc = {}
    net.train()

    for ep in range(a.epochs):
        for bi, (x, y, m) in enumerate(dl_tr):
            x = x.to(dev, dtype=dtype)
            y = y.to(dev, dtype=dtype)
            m = m.to(dev, dtype=dtype)
            mw = a.bg_weight + (1 - a.bg_weight) * m          # mask 内 1，mask 外 0.2

            # ---------- 判别器 ----------
            if disc is not None and step >= a.adv_start:
                with torch.no_grad():
                    fake = net(x)
                d_real = disc(y)
                d_fake = disc(fake.detach())
                loss_d = 0.5 * (F.mse_loss(d_real, torch.ones_like(d_real))
                                + F.mse_loss(d_fake, torch.zeros_like(d_fake)))
                opt_d.zero_grad(set_to_none=True)
                loss_d.backward()
                opt_d.step()

            # ---------- 生成器 ----------
            fake = net(x)
            losses = {}
            losses["pix"] = wl1(fake, y, mw)

            fs = run_vgg(rz(fake))
            with torch.no_grad():
                ft = run_vgg(rz(y))
                fi = run_vgg(rz(x))
            losses["perc"] = sum(wl1(fs[i], ft[i], mask_at(m, fs[i])) for i in range(len(fs))) / len(fs)
            # 内容锚用最深那层（语义），风格 Gram 也用最深那层
            losses["content"] = wl1(fs[-1], fi[-1], mask_at(m, fs[-1]))
            # ★ 显式线稿/边缘损失：全分辨率下直接监督梯度幅值。
            #   没有这一条，线稿只能指望 VGG 深层特征隐式学到，实测学不出来。
            sm_f, sm_y = sobel_mag(fake), sobel_mag(y)
            losses["line"] = wl1(sm_f, sm_y, m)
            # 诊断探针：学生/老师的**描边像素占比**之比（向 1.0 靠 = 描边在长出来）。
            #   用均值是错的（老师均值和照片几乎一样），必须看强边缘占比。
            with torch.no_grad():
                f_f = (sm_f.detach().float() > 1.0).float().mean()
                f_y = (sm_y.detach().float() > 1.0).float().mean()
                losses["edgeR"] = f_f / (f_y + 1e-8)
            if style_target is not None:
                gf = gram(fs[-1], mask_at(m, fs[-1]))[0]
                losses["style"] = F.l1_loss(gf, style_target)
            if disc is not None and step >= a.adv_start:
                losses["adv"] = F.mse_loss(disc(fake), torch.ones_like(disc(fake)))

            loss = (a.w_pix * losses["pix"] + a.w_perc * losses["perc"]
                    + a.w_content * losses["content"]
                    + a.w_line * losses["line"]
                    + (a.w_style * losses.get("style", 0.0) if a.w_style > 0 else 0.0)
                    + (a.w_adv * losses.get("adv", 0.0) if a.w_adv > 0 else 0.0))

            (loss / a.grad_accum).backward()
            for k, v in losses.items():
                log_acc[k] = log_acc.get(k, 0.0) + float(v.detach())   # detach 避免 warning + GPU 同步

            if (bi + 1) % a.grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                opt.step()
                opt.zero_grad(set_to_none=True)
                sched.step()
                step += 1

                if step % a.log_every == 0:
                    el = time.time() - t0
                    per = el / step
                    msgs = " ".join(f"{k}={v/a.log_every:.4f}" for k, v in sorted(log_acc.items()))
                    print(f"[{step:>6}/{total_steps}] ep{ep+1:<3} lr={sched.get_last_lr()[0]:.2e} "
                          f"{msgs} | {per:.2f}s/step | 剩 {per*(total_steps-step)/60:.0f}min", flush=True)
                    log_acc = {}

                if step % a.sample_every == 0:
                    save_samples(net, ds_va, out / "samples" / f"step_{step:06d}.jpg", dev, dtype)

                if step % a.save_every == 0:
                    torch.save(net.state_dict(), out / "student.pth")
                    print(f"[save] {out/'student.pth'}")

        torch.save(net.state_dict(), out / "student.pth")

    # ---- 收尾
    torch.save(net.state_dict(), out / "student.pth")
    save_samples(net, ds_va, out / "samples" / "final.jpg", dev, dtype)
    fused = fuse_bn(net)
    torch.save(fused.state_dict(), out / "student_fused.pth")
    # 记录模型配置：export_onnx.py 会读它决定要不要按残差模型导出（避免"漏开关"事故）
    (out / "model_info.json").write_text(json.dumps({
        "residual": bool(getattr(a, "residual", False)),
        "in_skip": bool(getattr(a, "in_skip", False)),
        "base": int(a.base),
        "hw": [int(a.hw[0]), int(a.hw[1])],
        "loss": {"w_pix": a.w_pix, "w_line": a.w_line, "w_adv": a.w_adv, "adv_start": a.adv_start},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[save] %s/model_info.json 已写入（residual=%s）"
          % (out, bool(getattr(a, "residual", False))))

    # 验证折叠是否无损
    with torch.no_grad():
        x = torch.randn(1, 3, a.hw[0], a.hw[1], device=dev, dtype=dtype) * 0.5
        d = (net.eval()(x).float() - fused.to(dev, dtype=dtype)(x).float()).abs().max().item()
    print(f"[fold] BN 折叠前后最大差异 {d:.2e}（应 < 1e-2）")

    (out / "train_log.json").write_text(json.dumps(
        {"args": vars(a), "params": n_par, "steps": step}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(f"\n[done] -> {out.resolve()}")
    print("       下一步（Windows）: python export_onnx.py ...  生成 ONNX + ORT 对齐")
    print("       再由 WSL 里的 compile_kmodel.py 编译成 .kmodel")


def save_samples(net, ds, path, dev, dtype):
    net.eval()
    rows = []
    with torch.no_grad():
        for i in range(min(4, len(ds))):
            x, y, _ = ds[i]
            p = net(x.unsqueeze(0).to(dev, dtype=dtype))[0].float().cpu()
            to_bgr = lambda t: ((t.clamp(-1, 1).permute(1, 2, 0).numpy() + 1) * 127.5).astype(np.uint8)[:, :, ::-1]
            a, b, c = to_bgr(x), to_bgr(p), to_bgr(y)
            sep = np.full((a.shape[0], 6, 3), 255, np.uint8)
            rows.append(np.hstack([a, sep, b, sep, c]))
    sep = np.full((6, rows[0].shape[1], 3), 255, np.uint8)
    grid = rows[0]
    for r in rows[1:]:
        grid = np.vstack([grid, sep, r])
    imwrite_u(path, grid)
    print(f"[sample] {path}  (左=输入 中=student 右=teacher)")
    net.train()


if __name__ == "__main__":
    main()
