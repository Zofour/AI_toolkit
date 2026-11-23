# -*- coding: utf-8 -*-
"""诊断：整段 vs 分段算出来的谱图为什么出现水平黑带"""
import os
import sys

import numpy as np

sys.path.insert(0, r"C:\chatbox_temp\ai_toolkit")
import audio_spectrum_gui as g

path = r"C:\Users\yourname\Desktop\db79e3ce4f873bea70d1fbb5d08d03e4.mp4"

print("=== A) 整段 22050 / nfft1024（GUI 全览的算法） ===")
x = g.decode(path, 0, 2566.0, 22050)
print("样本数", x.size, "峰值", float(np.abs(x).max()))
r = g.compute_stft(x, 22050, 1024, "hann")
F = r["freqs"].astype(float)
D = r["spec"]
print("形状", D.shape, "dB 范围", round(float(D.min()), 1), "~", round(float(D.max()), 1))
per_bin = D.mean(axis=0)          # 每列的均值（dB 域，便于看整体）
for tgt in (2000, 2500, 3000, 6000, 7500):
    i = int(np.argmin(np.abs(F - tgt)))
    print(f"  {tgt:5d}Hz → bin {i:4d} 时间平均 {per_bin[i]:7.1f} dB | 最小 {D[:, i].min():7.1f} | 最大 {D[:, i].max():6.1f}")
low = np.where(per_bin < -100)[0]
print("时间平均 < -100dB 的 bin 数:", low.size, "| 频率范围:", F[low].min() if low.size else "-", F[low].max() if low.size else "-")

print("\n=== B) 同样的文件，但每次只算 200 秒再拼 ===")
segs = []
for t in range(0, 2400, 200):
    xx = g.decode(path, t, t + 200, 22050)
    rr = g.compute_stft(xx, 22050, 1024, "hann", dcremove=True)
    segs.append(rr["spec"])
    i = int(np.argmin(np.abs(rr["freqs"] - 2500)))
    print(f"  段 {t:5d}-{t+200:5d}s: 2.5k bin 时间平均 {rr['spec'][:, i].mean():6.1f} dB")
S = np.vstack(segs)
print("拼起来形状", S.shape)

print("\n=== C) 整段但采样率 44100 / nfft 2048 ===")
x44 = g.decode(path, 0, 2566.0, 44100)
r3 = g.compute_stft(x44, 44100, 2048, "hann")
F3 = r3["freqs"].astype(float)
D3 = r3["spec"]
i = int(np.argmin(np.abs(F3 - 2500)))
print("形状", D3.shape, "| 2.5k bin 时间平均", round(float(D3[:, i].mean()), 1), "dB")
pb = D3.mean(axis=0)
print("时间平均 < -100dB 的 bin 数:", int((pb < -100).sum()))

print("\n=== D) 整段 22050 但用 20 秒的小步长（不做长度压缩） ===")
xx = g.decode(path, 0, 200, 22050)
r4 = g.compute_stft(xx, 22050, 1024, "hann")
i = int(np.argmin(np.abs(r4["freqs"] - 2500)))
print("形状", r4["spec"].shape, "| 2.5k bin 时间平均", round(float(r4["spec"][:, i].mean()), 1), "dB")
