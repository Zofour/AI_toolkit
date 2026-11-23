# -*- coding: utf-8 -*-
"""验证重分配公式与能量集中度"""
import sys

import numpy as np

sys.path.insert(0, r"C:\chatbox_temp\ai_toolkit")
import audio_spectrum_gui as g

sr = 22050
t = np.arange(0, 4, 1 / sr)

# 1) 纯音 440Hz
x1 = np.sin(2 * np.pi * 440 * t).astype(np.float32)
# 2) 400Hz 滑到 1200Hz 的 chirp + 2kHz 纯音
x2 = (0.5 * np.sin(2 * np.pi * (400 * t + 100 * t ** 2))
      + 0.5 * np.sin(2 * np.pi * 2000 * t)).astype(np.float32)

for name, x in (("440Hz纯音", x1), ("chirp2000", x2)):
    for mode in ("plain", "reass"):
        r = g.compute_stft(x, sr, 1024, "hann", target_cols=1400,
                           dcreass=1 if False else True) if False else None
    # 直接调用底层
    P, F, hop = g._reassigned_power(x.astype(np.float32), sr, 1024, "hann", 256, 4000)
    frames = np.lib.stride_tricks.sliding_window_view(x, 1024)[::256]
    mag = np.abs(np.fft.rfft(frames * np.hanning(1024), axis=1))
    Pp = mag ** 2
    for tag, M in (("普通", Pp), ("重分配", P)):
        e = M / M.sum()
        top = np.sort(e.ravel())[::-1]
        print(f"{name} {tag:4s}: 前0.1%能量占比 {top[:max(1, top.size//1000)].sum()*100:5.1f}% "
              f"| 前1% {top[:top.size//100].sum()*100:5.1f}% | 峰值/均值 {M.max()/M.mean():8.1f}")
    # 重分配的峰值频率位置
    pt, pf = np.unravel_index(np.argmax(P), P.shape)
    print(f"   重分配峰值: t={pt*hop/sr:.2f}s f={F[pf]:.0f}Hz")
    pt, pf = np.unravel_index(np.argmax(Pp), Pp.shape)
    print(f"   普通峰值  : t={pt*256/sr:.2f}s f={F[pf]:.0f}Hz")

# 3) 检查时频估计是否单调合理：在一个已知 chirp 上取几帧，看重心
x = x2.astype(np.float64)
nfft, hop = 1024, 256
w = np.hanning(nfft)
tc = (np.arange(nfft) - (nfft - 1) / 2) / sr
w_t = tc * w
w_d = np.gradient(w) * sr
frames = np.lib.stride_tricks.sliding_window_view(x, nfft)[::hop]
Xh = np.fft.rfft(frames * w, axis=1)
Xt = np.fft.rfft(frames * w_t, axis=1)
Xd = np.fft.rfft(frames * w_d, axis=1)
f_c = np.fft.rfftfreq(nfft, 1 / sr)
with np.errstate(divide="ignore", invalid="ignore"):
    f_est = f_c[None, :] - np.imag(Xd / (Xh + 1e-20)) / (2 * np.pi)
for fi in (50, 200):
    k = int(np.argmax(np.abs(Xh[fi])))
    print(f"帧 {fi} (t={fi*hop/sr:.2f}s): 普通峰值 {f_c[k]:.0f}Hz → 重分配估计 {f_est[fi, k]:.0f}Hz"
          f" (chirp 理论 {400 + 200*(fi*hop/sr):.0f}Hz)")
