# -*- coding: utf-8 -*-
"""对比：普通 STFT / 重分配(reassignment) / 显示端增强(背景减除+CLAHE+gamma)"""
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams

sys.path.insert(0, r"C:\chatbox_temp\ai_toolkit")
import audio_spectrum_gui as g

for _f in ("Microsoft YaHei", "SimHei", "DengXian"):
    if any(x.name == _f for x in font_manager.fontManager.ttflist):
        rcParams["font.sans-serif"] = [_f]
        break
rcParams["axes.unicode_minus"] = False

try:
    import cv2
except Exception:
    cv2 = None


def stft_complex(x, sr, nfft, hop, win):
    n = 1 + (len(x) - nfft) // hop
    idx = np.arange(n)[:, None] * hop + np.arange(nfft)[None, :]
    frames = x[idx]
    return np.fft.rfft(frames * win, axis=1), n


def reassigned(x, sr, nfft=1024):
    """重分配谱图：用 h / t·h / h' 三个窗估计每个时频点的真实重心"""
    hop = nfft // 4
    n0 = (np.arange(nfft) - (nfft - 1) / 2) / sr          # 相对窗中心的时间
    w = np.hanning(nfft)
    w_th = n0 * w                                          # t·h(t)
    w_dh = np.gradient(w) * sr                             # h'(t)

    Xh, nf = stft_complex(x, sr, nfft, hop, w)
    Xth, _ = stft_complex(x, sr, nfft, hop, w_th)
    Xdh, _ = stft_complex(x, sr, nfft, hop, w_dh)

    t_c = (np.arange(nf) * hop + (nfft - 1) / 2) / sr      # 每帧中心时间
    f_c = np.fft.rfftfreq(nfft, 1 / sr)                    # 每个频点中心频率

    eps = 1e-12
    with np.errstate(divide="ignore", invalid="ignore"):
        t_est = t_c[:, None] + np.real(Xth / (Xh + eps))
        f_est = f_c[None, :] - np.imag(Xdh / (Xh + eps)) / (2 * np.pi)

    mag = np.abs(Xh) ** 2
    # 把能量搬到 (t_est, f_est) 格点上
    ti = np.round((t_est - t_c[0]) * sr / hop).astype(np.int64)
    fi = np.round(f_est / (sr / nfft)).astype(np.int64)
    ok = np.isfinite(t_est) & np.isfinite(f_est) & (fi > 0) & (fi < len(f_c)) & (ti >= 0) & (ti < nf)
    ti, fi, m = ti[ok], fi[ok], mag[ok]
    R = np.zeros((nf, len(f_c)), dtype=np.float64)
    np.add.at(R, (ti, fi), m)
    return R, f_c, t_c


def enhance_db(D, bg_kernel=161, clip=1.0, gamma=0.8):
    """显示端增强：先去斑(3×3 median) → 谱白化(每频点减时间中值、截零) → 轻 CLAHE"""
    from scipy.ndimage import median_filter
    D = median_filter(D.astype(np.float32), size=(3, 3))
    bg = np.zeros_like(D)
    k = bg_kernel
    for i in range(D.shape[1]):
        col = D[:, i]
        pad = np.pad(col, k // 2, mode="edge")
        win = np.lib.stride_tricks.sliding_window_view(pad, k)
        bg[:, i] = np.median(win, axis=1)
    Y = np.maximum(D - bg, 0.0)
    hi = np.percentile(Y, 99.5)
    N = np.clip(Y / max(hi, 1e-9), 0, 1)
    U = (N * 255).astype(np.uint8)
    if cv2 is not None:
        U = cv2.createCLAHE(clipLimit=clip, tileGridSize=(16, 16)).apply(U)
    N = U.astype(np.float32) / 255.0
    return N ** gamma


def to_db(M):
    p = M ** 2
    return 10 * np.log10(np.maximum(p, 1e-20) / max(p.max(), 1e-20))


def log_view(D_cols_freq, f, rows=520):
    return g.interp_rows(f, D_cols_freq, np.geomspace(max(f[1], 20), f[-1], rows))


path = r"C:\Users\yourname\Desktop\db79e3ce4f873bea70d1fbb5d08d03e4.mp4"
t0, t1 = 1230.0, 1238.0
sr = 22050
x = g.decode(path, t0, t1, sr).astype(np.float64)
x -= x.mean()
print("样本", x.size, "峰值", round(float(np.abs(x).max()), 3))

D, F, T = reassigned(x, sr, 1024)
Dn = stft_complex(x, sr, 1024, 256, np.hanning(1024))[0]
dBn = to_db(np.abs(Dn))
dBp = to_db(np.sqrt(D))
print("普通", dBn.shape, "重分配", dBp.shape)

En = log_view(dBn, F)
Ep = log_view(dBp, F)
# 重分配的 (t,f) 网格是 (帧, 频点)，log_view 需要 (cols, bins)
En_sh = enhance_db(En)
Ep_sh = enhance_db(Ep)

rows = np.geomspace(max(F[1], 20), F[-1], 520)
fig, axs = plt.subplots(2, 2, figsize=(13, 8.5))
panels = [
    (En, "① 普通 STFT（现在的效果）", -70, 0),
    (Ep, "② 重分配谱图 reassignment（时频点搬到能量重心）", -70, 0),
    (En_sh, "③ 普通 + 谱白化增强", 0, 1),
    (Ep_sh, "④ 重分配 + 谱白化增强", 0, 1),
]
ext = [t0, t1, np.log10(rows[0]), np.log10(rows[-1])]
ticks = [30, 50, 100, 200, 300, 500, 1000, 2000, 4000, 8000]
for ax, (M, ttl, vmin, vmax) in zip(axs.flat, panels):
    im = ax.imshow(M.T, aspect="auto", origin="lower", cmap="magma",
                   extent=ext, vmin=vmin, vmax=vmax, interpolation="nearest")
    ax.set_title(ttl, fontsize=11)
    ax.set_yticks([np.log10(v) for v in ticks if rows[0] <= v <= rows[-1]])
    ax.set_yticklabels([f"{v/1000:g}k" if v >= 1000 else str(v)
                        for v in ticks if rows[0] <= v <= rows[-1]], fontsize=8)
    ax.set_xlabel("时间 (s)", fontsize=9)
    fig.colorbar(im, ax=ax, pad=0.01).ax.tick_params(labelsize=7)
fig.tight_layout()
out = os.path.join(r"C:\chatbox_temp\ai_toolkit", "_sharpen_compare.png")
fig.savefig(out, dpi=130)
print("saved", out)
