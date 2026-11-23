# -*- coding: utf-8 -*-
"""
音频频谱图生成器（波形 + 平均频谱 + 语谱图 三联图）
依赖：ffmpeg(PATH) + numpy + matplotlib（本机已具备，无需 librosa/soundfile）

用法示例：
  python audio_spectrum.py D:\\audio\\test.mp3
  python audio_spectrum.py test.wav -o D:\\1.png --fmax 8000 --logfreq
  python audio_spectrum.py test.m4a --start 12.5 --dur 3     # 只分析某一段
  python audio_spectrum.py test.wav --mode wave|spec|spectro
"""
import argparse
import os
import subprocess
import sys

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams

# ---------- 中文显示 ----------
for _f in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DengXian"):
    if any(f.name == _f for f in font_manager.fontManager.ttflist):
        rcParams["font.sans-serif"] = [_f]
        break
rcParams["axes.unicode_minus"] = False
rcParams["figure.facecolor"] = "white"


def decode(path, sr):
    """用 ffmpeg 解码成单声道 f32 PCM（任何格式都吃）"""
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1",
           "-ar", str(sr), "-f", "f32le", "-"]
    # Windows 下由 pythonw/GUI 父进程调用时，不加这个会弹出黑色控制台窗口
    flags = 0x08000000 if os.name == "nt" else 0
    p = subprocess.run(cmd, capture_output=True, creationflags=flags)
    if p.returncode != 0:
        sys.exit("ffmpeg 解码失败：\n" + p.stderr.decode("utf-8", "ignore")[:800])
    x = np.frombuffer(p.stdout, dtype="<f4").astype(np.float64)
    if x.size == 0:
        sys.exit("解码得到 0 个采样点，检查输入文件是否有效音频。")
    return x


def stft_mag(x, n_fft, hop):
    """返回 (帧 x 频点) 的幅度谱，汉宁窗"""
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x)))
    win = np.hanning(n_fft)
    n = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n)[:, None] * hop + np.arange(n_fft)[None, :]
    frames = x[idx] * win
    return np.abs(np.fft.rfft(frames, axis=1))


def fmt_hz(v, _):
    if v <= 0:
        return ""
    return f"{v/1000:g}k" if v >= 1000 else f"{v:g}"


def main():
    ap = argparse.ArgumentParser(description="生成音频频谱图 PNG")
    ap.add_argument("input", help="音频/视频文件路径")
    ap.add_argument("-o", "--out", help="输出 PNG（默认与输入同目录同名）")
    ap.add_argument("--mode", default="all", choices=["all", "wave", "spec", "spectro"],
                    help="all=三联图（默认）；wave=只波形；spec=只平均频谱；spectro=只语谱图")
    ap.add_argument("--sr", type=int, default=22050, help="分析采样率（默认 22050）")
    ap.add_argument("--nfft", type=int, default=0, help="FFT 点数（默认自动：约 46ms）")
    ap.add_argument("--fmax", type=float, default=0, help="频率上限 Hz（默认 Nyquist）")
    ap.add_argument("--fmin", type=float, default=0, help="频率下限 Hz（默认 0）")
    ap.add_argument("--logfreq", action="store_true", help="频谱横轴/语谱图纵轴用对数刻度")
    ap.add_argument("--start", type=float, default=0, help="起点 秒")
    ap.add_argument("--dur", type=float, default=0, help="时长 秒（0=到结尾）")
    ap.add_argument("--dpi", type=int, default=150)
    args = ap.parse_args()

    path = os.path.abspath(args.input)
    if not os.path.isfile(path):
        sys.exit(f"找不到文件：{path}")
    out = args.out or os.path.splitext(path)[0] + "_spectrum.png"

    x = decode(path, args.sr)
    if args.start or args.dur:
        a = int(args.start * args.sr)
        b = len(x) if not args.dur else a + int(args.dur * args.sr)
        x = x[a:b]
        if x.size == 0:
            sys.exit("截取区间为空，检查 --start / --dur。")

    n_fft = args.nfft or max(256, 2 ** int(np.round(np.log2(args.sr * 0.046))))
    hop = max(1, n_fft // 4)
    mag = stft_mag(x, n_fft, hop)
    freqs = np.fft.rfftfreq(n_fft, 1 / args.sr)

    # 频率范围裁剪
    fmax = args.fmax or args.sr / 2
    keep = (freqs >= args.fmin) & (freqs <= fmax) & (freqs > 0)
    f = freqs[keep]
    M = mag[:, keep]

    # 幅度归一化到 dB（相对全局最大，0 dB = 最强）
    eps = 1e-12
    ref = M.max() or eps
    dB = 20 * np.log10(np.maximum(M, eps) / ref)

    # 平均频谱（对帧取能量平均，能量域平均才不被静音帧拉低）
    avg = 20 * np.log10(np.maximum(np.sqrt((M ** 2).mean(axis=0)), eps) / ref)
    peak_i = int(np.argmax(avg))
    peak_hz = f[peak_i]

    t = np.arange(x.size) / args.sr

    # 语谱图降采样列数，保证出图快
    max_cols = 1200
    if dB.shape[0] > max_cols:
        step = int(np.ceil(dB.shape[0] / max_cols))
        k = dB.shape[0] // step * step
        dBs = dB[:k].reshape(-1, step, dB.shape[1]).mean(axis=1)
        ts = (np.arange(dBs.shape[0]) * step + step / 2) * hop / args.sr
    else:
        dBs = dB
        ts = (np.arange(dB.shape[0]) + 0.5) * hop / args.sr

    mode = args.mode
    panels = ["wave", "spec", "spectro"] if mode == "all" else [mode]
    n = len(panels)
    fig, axes = plt.subplots(n, 1, figsize=(11, 2.6 * n + 0.6), squeeze=False)
    axes = axes[:, 0]
    ax_i = 0

    if "wave" in panels:
        ax = axes[ax_i]; ax_i += 1
        ax.plot(t, x, lw=0.5, color="#2b6cb0")
        ax.set_xlim(0, max(t[-1], 1e-6))
        ax.set_xlabel("时间 (s)"); ax.set_ylabel("幅度")
        ax.set_title(f"波形   {os.path.basename(path)}   时长 {x.size/args.sr:.2f}s")
        ax.grid(alpha=0.25)

    if "spec" in panels:
        ax = axes[ax_i]; ax_i += 1
        ax.plot(f, avg, lw=0.9, color="#c05621")
        ax.axvline(peak_hz, color="#e53e3e", ls="--", lw=0.9)
        ax.annotate(f"主峰 {peak_hz:.0f} Hz", xy=(peak_hz, avg[peak_i]),
                    xytext=(6, 4), textcoords="offset points", color="#e53e3e", fontsize=9)
        if args.logfreq:
            ax.set_xscale("log")
            ticks = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
            ax.set_xticks([v for v in ticks if f[0] <= v <= f[-1]])
            ax.xaxis.set_major_formatter(plt.FuncFormatter(fmt_hz))
            ax.minorticks_off()
        ax.set_xlim(max(f[0], 1), f[-1])
        ax.set_ylim(max(avg.min() - 6, -100), 3)
        ax.set_xlabel("频率 (Hz)" + ("，对数刻度" if args.logfreq else ""))
        ax.set_ylabel("幅度 (dB)")
        ax.set_title("平均频谱")
        ax.grid(alpha=0.25, which="both")

    if "spectro" in panels:
        ax = axes[ax_i]
        pc = ax.pcolormesh(ts, f, dBs.T, shading="gouraud", cmap="magma",
                           vmin=max(dB.max() - 70, -90), vmax=0, rasterized=True)
        if args.logfreq:
            ax.set_yscale("log")
            ticks = [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
            ax.set_yticks([v for v in ticks if f[0] <= v <= f[-1]])
            ax.yaxis.set_major_formatter(plt.FuncFormatter(fmt_hz))
            ax.minorticks_off()
        else:
            ax.yaxis.set_major_formatter(plt.FuncFormatter(fmt_hz))
        ax.set_ylim(max(f[0], 1), f[-1])
        ax.set_xlim(0, max(ts[-1], 1e-6))
        ax.set_xlabel("时间 (s)"); ax.set_ylabel("频率" + (" (对数)" if args.logfreq else ""))
        ax.set_title("语谱图（颜色=强度 dB）")
        cb = fig.colorbar(pc, ax=ax, pad=0.01)
        cb.set_label("dB")

    fig.tight_layout()
    fig.savefig(out, dpi=args.dpi, bbox_inches="tight")
    plt.close(fig)

    # 控制台给前几个峰值，方便判断音高/共振峰
    order = np.argsort(avg)[::-1]
    tops, used = [], []
    for i in order:
        if all(abs(f[i] - u) > 30 for u in used):
            tops.append((f[i], avg[i])); used.append(f[i])
        if len(tops) >= 5:
            break
    print(f"时长 {x.size/args.sr:.2f}s | 采样率 {args.sr} | nfft {n_fft} | 主峰 {peak_hz:.0f} Hz")
    print("主要频率峰：" + "  ".join(f"{hz:.0f}Hz({d:.1f}dB)" for hz, d in tops))
    print("图已保存：" + out)


if __name__ == "__main__":
    main()
