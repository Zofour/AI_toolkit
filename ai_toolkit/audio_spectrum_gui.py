# -*- coding: utf-8 -*-
"""
音频频谱查看器（交互式）
- 滚轮缩放（时间轴；按住 Shift 滚轮缩放频率轴）
- 左键拖动平移，双击回到全览
- 顶部工具栏：采样率、FFT 点数、窗函数、色图、对数频率、动态范围、播放、导出 PNG
- 右侧联动「平均频谱」，底部状态栏实时读数（时间 / 频率 / 强度）
- 大数据按可见范围流式计算，几十小时的视频也秒开（ffmpeg 解码 + numpy STFT）

用法：
  python audio_spectrum_gui.py                     # 打开后选文件
  python audio_spectrum_gui.py "D:\\a.mp4"
  python audio_spectrum_gui.py "D:\\a.mp4" --sr 8000 --nfft 2048 --logfreq
快捷键：空格 播放/停止   F 全览   Ctrl+S 保存 PNG   Ctrl+O 打开
"""
import argparse
import os
import subprocess
import sys
import time

import numpy as np
import matplotlib

if "--selftest" in sys.argv:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager, rcParams
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

from PyQt5 import QtCore, QtGui, QtWidgets

try:
    import sounddevice as sd
except Exception:
    sd = None

try:
    import cv2
    _HAS_CV2 = True
except Exception:
    cv2 = None
    _HAS_CV2 = False

from scipy.ndimage import uniform_filter1d, median_filter, gaussian_filter

# ---------------- 字体 ----------------
for _f in ("Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DengXian"):
    if any(f.name == _f for f in font_manager.fontManager.ttflist):
        rcParams["font.sans-serif"] = [_f]
        break
rcParams["axes.unicode_minus"] = False

DEFAULT_SR = 22050
# Windows: 由 pythonw（无控制台）启动 ffmpeg/ffprobe 时，系统会给它们新建一个黑色控制台窗口，
# 每次拖动/放大重算都会闪一下 → 一律加 CREATE_NO_WINDOW
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SR_CHOICES = [4000, 8000, 11025, 16000, 22050, 32000, 44100, 48000]
NFFT_CHOICES = [128, 256, 512, 1024, 2048, 4096, 8192]
WINS = {"汉宁 hann": "hann", "汉明 hamming": "hamming", "布莱克曼 blackman": "blackman",
        "巴特利特 bartlett": "bartlett", "矩形 boxcar": "boxcar"}
CMAPS = ["magma", "inferno", "viridis", "plasma", "turbo", "gray", "hot"]


# ---------------- 底层：解码 / STFT ----------------
def probe_duration(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    try:
        return float(p.stdout.strip().splitlines()[0])
    except Exception:
        return 0.0


def decode(path, t0, t1, sr):
    """ffmpeg 精确截取 [t0,t1) 并重采样成单声道 f32。返回 float32 数组。"""
    t1 = max(t1, t0 + 0.002)
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t0:.4f}", "-t", f"{t1 - t0:.4f}",
           "-i", path, "-vn", "-ac", "1", "-ar", str(int(sr)), "-f", "f32le", "-"]
    p = subprocess.run(cmd, capture_output=True, creationflags=CREATE_NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "ignore")[:400])
    return np.frombuffer(p.stdout, dtype="<f4").astype(np.float32)


def _win(name, n):
    if name == "hann":
        return np.hanning(n)
    if name == "hamming":
        return np.hamming(n)
    if name == "blackman":
        return np.blackman(n)
    if name == "bartlett":
        return np.bartlett(n)
    return np.ones(n)


def compute_stft(x, sr, nfft, win, target_cols=1400, dcremove=True,
                 reassign=False, hpss="off"):
    """
    返回 dict(freqs, spec(dB, 列=时间 × 频点), avg(dB), t0, t1)
    reassign=True → 重分配谱图（时频点搬到能量重心，脊线变细）
    hpss="off"/"harm"/"perc" → 谐波/打击分离后只看其中一层
    """
    nfft = int(min(max(nfft, 64), 32768))
    x = np.asarray(x, dtype=np.float32)
    if dcremove and x.size:
        x = x - np.float32(x.mean())
    if x.size < nfft:
        x = np.pad(x, (0, nfft - x.size))
    win_arr = _win(win, nfft).astype(np.float32)
    n = x.size
    hop = max(1, nfft // 4)
    n_frames = 1 + (n - nfft) // hop
    if n_frames > 3000:                      # 太长 → 加大步长（不做 75% 重叠）
        hop = max(hop, int(np.ceil((n - nfft) / 2999.0)))
        n_frames = 1 + (n - nfft) // hop

    if reassign:
        P, freqs, hop = _reassigned_power(x, sr, nfft, win, hop, max_frames=4000)
        n_frames = P.shape[0]
    else:
        frames = np.lib.stride_tricks.sliding_window_view(x, nfft)[::hop][:n_frames]
        mag = np.abs(np.fft.rfft(frames * win_arr, axis=1)).astype(np.float32)
        freqs = np.fft.rfftfreq(nfft, 1.0 / sr)
        P = mag.astype(np.float64) ** 2

    if hpss in ("harm", "perc"):
        P = _hpss_mask(P, hpss)

    # 列池化
    if P.shape[0] > target_cols:
        step = int(np.ceil(P.shape[0] / target_cols))
        k = (P.shape[0] // step) * step
        P = P[:k].reshape(-1, step, P.shape[1]).mean(axis=1)
        hop = hop * step
        n_frames = P.shape[0]

    eps = 1e-20
    ref = P.max() if P.max() > 0 else eps
    spec_db = 10 * np.log10(np.maximum(P, eps) / ref)
    avg_db = 10 * np.log10(np.maximum(P.mean(axis=0), eps) / ref)

    t0 = 0.0
    t1 = P.shape[0] * hop / sr
    return {"freqs": freqs.astype(np.float32), "spec": spec_db.astype(np.float32),
            "avg": avg_db.astype(np.float32), "t0": t0, "t1": t1}


def _hpss_mask(P, mode, k_t=31, k_f=31):
    """谐波-打击分离（中值滤波软掩模）：沿时间平滑保留水平线，沿频率平滑保留竖线"""
    H = median_filter(P, size=(k_t, 1), mode="nearest")   # 沿时间平滑 → 谐波估计
    Q = median_filter(P, size=(1, k_f), mode="nearest")   # 沿频率平滑 → 打击估计
    m = (H ** 2) / (H ** 2 + Q ** 2 + 1e-20)
    return P * m if mode == "harm" else P * (1.0 - m)


def _reassigned_power(x, sr, nfft, win, hop_min, max_frames=4000):
    """重分配：用 h / t·h / h' 三个窗估计每个时频点的真实重心，把能量搬过去"""
    n = x.size
    hop = max(hop_min, int(np.ceil(max(n - nfft, 1) / max_frames)))
    n_frames = 1 + max(0, (n - nfft)) // hop
    if n_frames < 2:
        n_frames = 2

    w = _win(win, nfft).astype(np.float32)
    tc = (np.arange(nfft) - (nfft - 1) / 2.0) / sr
    w_t = (tc * w).astype(np.float32)
    w_d = (np.gradient(w) * sr).astype(np.float32)

    idx = np.arange(n_frames)[:, None] * hop + np.arange(nfft)[None, :]
    frames = x[idx]
    Xh = np.fft.rfft(frames * w, axis=1)
    Xt = np.fft.rfft(frames * w_t, axis=1)
    Xd = np.fft.rfft(frames * w_d, axis=1)

    f_c = np.fft.rfftfreq(nfft, 1.0 / sr)
    eps = 1e-20
    with np.errstate(divide="ignore", invalid="ignore"):
        t_est = (np.arange(n_frames)[:, None] * hop + (nfft - 1) / 2.0) / sr \
                + np.real(Xt / (Xh + eps))
        f_est = f_c[None, :] - np.imag(Xd / (Xh + eps)) / (2 * np.pi)

    mag2 = (np.abs(Xh) ** 2).astype(np.float64)
    # 只搬有意义的点：弱频点的相位估计不可靠（会飞到兆赫级），一律丢掉
    thr = mag2.max() * 1e-6 if mag2.size else 0.0
    df = f_est - f_c[None, :]
    bin_hz = sr / nfft
    good = (np.isfinite(t_est) & np.isfinite(f_est) & (mag2 > thr)
            & (np.abs(df) < 4 * bin_hz))
    ti = np.rint(t_est[good] * sr / hop).astype(np.int64)
    fi = np.rint(f_est[good] / bin_hz).astype(np.int64)      # Hz → bin：f*nfft/sr
    inside = (ti >= 0) & (ti < n_frames) & (fi > 0) & (fi < len(f_c))

    R = np.zeros((n_frames, len(f_c)), dtype=np.float64)
    np.add.at(R, (ti[inside], fi[inside]), mag2[good][inside])
    # 像素级去散斑（平滑太大就把锐化抹掉了，这里只做最轻的）
    if R.any():
        R = gaussian_filter(R, sigma=(0.35, 0.25))
    return R, f_c, hop


def display_intensity(dB, dbrange=70.0, denoise=True, whiten=True, clahe=True,
                      bg=161, clip=1.0, gamma=0.8):
    """把 dB 矩阵变成 0~1 的显示强度：去斑 → 谱白化 → CLAHE → gamma"""
    M = np.asarray(dB, dtype=np.float32)
    if denoise:
        M = median_filter(M, size=(3, 3), mode="nearest")
    if whiten:
        base = uniform_filter1d(M, size=min(bg, max(5, M.shape[0] // 2)),
                               axis=0, mode="nearest")
        M = np.maximum(M - base, 0.0)
        hi = float(np.percentile(M, 99.5)) or 1.0
        M = np.clip(M / hi, 0.0, 1.0)
    else:
        M = np.clip((M + dbrange) / dbrange, 0.0, 1.0)
    if clahe and _HAS_CV2:
        U = (M * 255).astype(np.uint8)
        U = cv2.createCLAHE(clipLimit=float(clip), tileGridSize=(16, 16)).apply(U)
        M = U.astype(np.float32) / 255.0
    return np.clip(M, 0, 1) ** float(gamma)


def interp_rows(F, D, targets):
    """把 (cols × bins) 沿频率轴线性插值到 targets"""
    if len(F) < 2:
        return np.repeat(D[:, :1], len(targets), axis=1)
    idx = np.clip(np.searchsorted(F, targets) - 1, 0, len(F) - 2)
    w = (np.asarray(targets) - F[idx]) / np.maximum(F[idx + 1] - F[idx], 1e-9)
    return D[:, idx] * (1 - w) + D[:, idx + 1] * w


def fmt_hz(v):
    v = float(v)
    if v >= 1000:
        s = f"{v / 1000:g}"
        return s + "k"
    return f"{v:g}"


NICE = [10, 20, 30, 50, 70, 100, 150, 200, 300, 500, 700, 1000, 1500, 2000, 3000,
        4000, 5000, 7000, 8000, 10000, 15000, 20000]


def nice_ticks(lo, hi):
    return [v for v in NICE if lo * 0.999 <= v <= hi * 1.001]


def thin_ticks(lo, hi, max_n=9):
    """线性频率轴：刻度太密就抽稀，否则 20Hz~11kHz 的标签全挤在底部重叠"""
    ticks = nice_ticks(lo, hi)
    if len(ticks) <= max_n:
        return ticks
    span = max(hi - lo, 1e-9)
    for step in (100, 200, 250, 500, 1000, 2000, 2500, 5000):
        cand = [v for v in ticks if v % step == 0]
        if 3 <= len(cand) <= max_n:
            return cand
    k = int(np.ceil(len(ticks) / max_n))
    return ticks[::k]


# ---------------- 后台计算线程 ----------------
class Worker(QtCore.QThread):
    done = QtCore.pyqtSignal(int, object)

    def __init__(self, token, path, t0, t1, sr, nfft, win, cols=1400, dc=True,
                 reassign=False, hpss="off"):
        super().__init__()
        self.token, self.path, self.t0, self.t1 = token, path, t0, t1
        self.sr, self.nfft, self.win, self.cols, self.dc = sr, nfft, win, cols, dc
        self.reassign, self.hpss = reassign, hpss

    def run(self):
        try:
            x = decode(self.path, self.t0, self.t1, self.sr)
            res = compute_stft(x, self.sr, self.nfft, self.win, self.cols,
                               self.dc, self.reassign, self.hpss)
            res["abs_t0"] = self.t0
            res["abs_t1"] = self.t0 + res["t1"]
            res["sr"] = self.sr
            res["n"] = int(x.size)
            res["flags"] = (self.reassign, self.hpss)
            self.done.emit(self.token, res)
        except Exception as e:  # noqa
            self.done.emit(self.token, {"error": str(e)})


# ---------------- 主窗口 ----------------
class Viewer(QtWidgets.QMainWindow):
    def __init__(self, path=None, sr=DEFAULT_SR, nfft=1024, logfreq=False, init_view=None):
        super().__init__()
        self.setWindowTitle("音频频谱查看器")
        self.resize(1280, 780)

        self.path = None
        self.dur = 0.0
        self._init_view = init_view
        self.sr = int(sr)
        self.nfft = int(nfft)
        self.win = "hann"
        self.cmap = "magma"
        self.logfreq = bool(logfreq)
        self.dbrange = 70
        self.token = 0
        self.cache = None
        self.im = None
        self.cb = None
        self._workers = []
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._recompute)

        self._play_t0 = 0.0
        self._play_when = 0.0
        self._cursor = None
        self._ptimer = QtCore.QTimer(self)
        self._ptimer.setInterval(40)
        self._ptimer.timeout.connect(self._tick_play)

        self._drag = None
        self._last_click = (0.0, 0.0, 0.0)
        self.compare_t = None
        self._divider = None
        self._div_drag = False
        self._cbl = None
        self.setAcceptDrops(True)
        self._build_ui()
        self.statusBar().showMessage("就绪：Ctrl+O 打开文件")
        if path:
            QtCore.QTimer.singleShot(50, lambda: self.open_path(path))

    # ---------- UI ----------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        v = QtWidgets.QVBoxLayout(central)
        v.setContentsMargins(6, 6, 6, 4)
        v.setSpacing(4)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(6)
        v.addLayout(bar)

        def btn(text, slot, tip=""):
            b = QtWidgets.QPushButton(text)
            b.setFixedHeight(26)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bar.addWidget(b)
            return b

        btn("打开…", self.on_open, "Ctrl+O").setShortcut("Ctrl+O")
        btn("全览", self.fit_all, "F：显示整个文件").setShortcut("F")
        btn("导出 PNG", self.export_png, "Ctrl+S：按当前视图导出图片").setShortcut("Ctrl+S")
        self.btn_play = btn("▶ 播放", self.toggle_play, "空格：播放/停止可视区（最长 60 秒）")
        self.btn_play.setShortcut("Space")

        bar.addSpacing(10)
        bar.addWidget(QtWidgets.QLabel("采样率"))
        self.cb_sr = QtWidgets.QComboBox()
        self.cb_sr.addItems([str(s) for s in SR_CHOICES])
        self.cb_sr.setCurrentText(str(self.sr))
        self.cb_sr.setEditable(True)
        self.cb_sr.setFixedWidth(80)
        self.cb_sr.currentTextChanged.connect(self.on_sr)
        bar.addWidget(self.cb_sr)

        bar.addWidget(QtWidgets.QLabel("FFT"))
        self.cb_nfft = QtWidgets.QComboBox()
        self.cb_nfft.addItems([str(n) for n in NFFT_CHOICES])
        self.cb_nfft.setCurrentText(str(self.nfft))
        self.cb_nfft.setFixedWidth(80)
        self.cb_nfft.currentTextChanged.connect(self.on_nfft)
        bar.addWidget(self.cb_nfft)

        self.cb_win = QtWidgets.QComboBox()
        self.cb_win.addItems(list(WINS.keys()))
        self.cb_win.setFixedWidth(140)
        self.cb_win.currentTextChanged.connect(self.on_win)
        bar.addWidget(self.cb_win)

        self.cb_cmap = QtWidgets.QComboBox()
        self.cb_cmap.addItems(CMAPS)
        self.cb_cmap.setFixedWidth(90)
        self.cb_cmap.currentTextChanged.connect(self.on_cmap)
        bar.addWidget(self.cb_cmap)

        self.chk_log = QtWidgets.QCheckBox("对数频率")
        self.chk_log.setChecked(self.logfreq)
        self.chk_log.stateChanged.connect(self.on_log)
        bar.addWidget(self.chk_log)

        self.chk_dc = QtWidgets.QCheckBox("去直流")
        self.chk_dc.setChecked(True)
        self.chk_dc.setToolTip("减去均值，去掉 0 Hz 附近的直流偏置亮带")
        self.chk_dc.stateChanged.connect(lambda _s: self._recompute())
        bar.addWidget(self.chk_dc)

        bar.addWidget(QtWidgets.QLabel("范围"))
        self.sp_db = QtWidgets.QSpinBox()
        self.sp_db.setRange(20, 110)
        self.sp_db.setValue(self.dbrange)
        self.sp_db.setSuffix(" dB")
        self.sp_db.setFixedWidth(78)
        self.sp_db.valueChanged.connect(self.on_db)
        bar.addWidget(self.sp_db)
        bar.addStretch(1)

        # ---- 第二行：频谱增强 ----
        bar2 = QtWidgets.QHBoxLayout()
        bar2.setSpacing(8)
        v.addLayout(bar2)
        title = QtWidgets.QLabel("增强")
        title.setStyleSheet("color:#555;")
        bar2.addWidget(title)

        self.chk_reassign = QtWidgets.QCheckBox("重分配")
        self.chk_reassign.setToolTip(
            "reassignment：把每个时频点的能量搬到它真实的时频重心，{}\n".format("谐波脊线变细、瞬态变集中")
            + "代价：后台重算变慢约 2~3 倍（只算当前可见区）")
        self.chk_reassign.stateChanged.connect(lambda _s: self._recompute())
        bar2.addWidget(self.chk_reassign)

        self.cb_hpss = QtWidgets.QComboBox()
        self.cb_hpss.addItems(["原始", "只留谐波", "只留打击"])
        self.cb_hpss.setFixedWidth(96)
        self.cb_hpss.setToolTip("HPSS：中值滤波分离持续音（水平线）与瞬态（竖线）")
        self.cb_hpss.currentIndexChanged.connect(lambda _i: self._recompute())
        bar2.addWidget(self.cb_hpss)

        bar2.addSpacing(12)
        self.chk_denoise = QtWidgets.QCheckBox("去斑")
        self.chk_denoise.setChecked(False)
        self.chk_denoise.setToolTip("3×3 中值滤波，抹掉椒盐噪点")
        self.chk_denoise.stateChanged.connect(lambda _s: self.render())
        bar2.addWidget(self.chk_denoise)

        self.chk_white = QtWidgets.QCheckBox("谱白化")
        self.chk_white.setChecked(False)
        self.chk_white.setToolTip("每个频点减掉它自己的时间均值背景 → 宽带底噪被压平，窄带成分跳出来")
        self.chk_white.stateChanged.connect(lambda _s: self.render())
        bar2.addWidget(self.chk_white)

        self.chk_clahe = QtWidgets.QCheckBox("CLAHE")
        self.chk_clahe.setChecked(False)
        self.chk_clahe.setToolTip("局部直方图均衡（16×16 tile，clip=1.0）；噪点大的素材别开")
        self.chk_clahe.stateChanged.connect(lambda _s: self.render())
        bar2.addWidget(self.chk_clahe)

        bar2.addWidget(QtWidgets.QLabel("gamma"))
        self.sp_gamma = QtWidgets.QDoubleSpinBox()
        self.sp_gamma.setRange(0.4, 1.6)
        self.sp_gamma.setSingleStep(0.1)
        self.sp_gamma.setValue(0.8)
        self.sp_gamma.setFixedWidth(64)
        self.sp_gamma.setToolTip("<1 提亮弱成分，>1 压暗背景")
        self.sp_gamma.valueChanged.connect(lambda _v: self.render())
        bar2.addWidget(self.sp_gamma)

        bar2.addSpacing(12)
        self.chk_cmp = QtWidgets.QCheckBox("对比线")
        self.chk_cmp.setToolTip("左半原图 / 右半增强，白色虚线可左右拖动")
        self.chk_cmp.stateChanged.connect(lambda _s: self.render())
        bar2.addWidget(self.chk_cmp)
        bar2.addStretch(1)

        # 画布
        try:
            ratio = float(QtWidgets.QApplication.primaryScreen().devicePixelRatio())
        except Exception:
            ratio = 1.0
        self._resizing = False
        self.fig = Figure(figsize=(13.2, 7.2), dpi=100)
        self.canvas = FigureCanvas(self.fig)
        v.addWidget(self.canvas, 1)
        gs = self.fig.add_gridspec(1, 3, width_ratios=[34, 1.5, 7],
                                   left=0.07, right=0.975, top=0.93, bottom=0.09,
                                   wspace=0.12)
        self.ax = self.fig.add_subplot(gs[0, 0])
        self.cax = self.fig.add_subplot(gs[0, 1])
        self.axS = self.fig.add_subplot(gs[0, 2], sharey=self.ax)
        self.ax.set_xlabel("时间 (s)")
        self.ax.set_ylabel("频率")
        self.axS.set_xlabel("平均频谱 (dB)", fontsize=8)
        for a in (self.ax, self.axS):
            a.tick_params(labelsize=8)
        self.axS.tick_params(labelleft=False)   # 共享轴，别重复画刻度
        self.axS.set_ylim(0, 1)
        self._hint = self.ax.text(
            0.5, 0.5, "Ctrl+O 打开文件\n或把音频/视频拖进窗口\n\n滚轮缩放时间轴｜Shift+滚轮缩放频率轴\n拖动平移｜双击全览",
            transform=self.ax.transAxes, ha="center", va="center",
            fontsize=13, color="#666666", linespacing=1.6)
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.ax.set_xlim(0, 1)
        self.ax.set_ylim(0, 1)
        self.ax.tick_params(labelbottom=False, labelleft=False)

        self.canvas.mpl_connect("scroll_event", self.on_scroll)
        self.canvas.mpl_connect("button_press_event", self.on_press)
        self.canvas.mpl_connect("motion_notify_event", self.on_motion)
        self.canvas.mpl_connect("button_release_event", self.on_release)

    # ---------- 拖放 ----------
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        for u in ev.mimeData().urls():
            p = u.toLocalFile()
            if p and os.path.isfile(p):
                self.open_path(p)
                break

    # ---------- 打开文件 ----------
    def on_open(self):
        f, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择音频/视频", "",
            "媒体文件 (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.opus *.mp4 *.mkv *.mov *.avi *.webm *.ts *.wma);;所有文件 (*.*)")
        if f:
            self.open_path(f)

    def open_path(self, path):
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            self.statusBar().showMessage("找不到文件: " + path)
            return
        d = probe_duration(path)
        if d <= 0:
            self.statusBar().showMessage("没有读到音频时长，可能没有音轨: " + os.path.basename(path))
            return
        self.path, self.dur = path, d
        self.cache = None
        self.setWindowTitle(f"音频频谱查看器 — {os.path.basename(path)}  [{d:.1f}s]")
        if self._init_view:
            a, b = self._init_view
            self.view = (max(0.0, a), min(d, max(b, a + 0.01)))
            self._init_view = None
        else:
            self.view = (0.0, d)
        self.fview = (0.0, min(self.sr / 2.0, 8000.0))
        self.statusBar().showMessage(f"已载入 {os.path.basename(path)}｜时长 {d:.2f}s｜正在计算…")
        self._recompute()

    def fit_all(self):
        if not self.path:
            return
        self.view = (0.0, self.dur)
        self._recompute()

    # ---------- 参数回调 ----------
    def on_sr(self, txt):
        try:
            sr = int(float(txt))
        except ValueError:
            return
        if sr < 1000 or sr > 384000:
            return
        if sr == self.sr:
            return
        self.sr = sr
        self.fview = (self.fview[0], min(self.fview[1], sr / 2.0))
        self._recompute()

    def on_nfft(self, txt):
        try:
            n = int(txt)
        except ValueError:
            return
        if n != self.nfft:
            self.nfft = n
            self._recompute()

    def on_win(self, txt):
        self.win = WINS.get(txt, "hann")
        self._recompute()

    def on_cmap(self, txt):
        self.cmap = txt
        if self.im is not None:
            self.im.set_cmap(txt)
            self.canvas.draw_idle()

    def on_log(self, _state):
        self.logfreq = self.chk_log.isChecked()
        self._recompute()

    def on_db(self, v):
        self.dbrange = int(v)
        if self.im is not None:
            self.im.set_clim(-self.dbrange, 0)
            self.axS.set_xlim(-self.dbrange - 3, 3)
            self.canvas.draw_idle()

    # ---------- 计算 ----------
    def _recompute(self):
        if not self.path or self.dur <= 0:
            return
        t0, t1 = self.view
        if t1 - t0 < 0.004:
            return
        self.token += 1
        hpss = {0: "off", 1: "harm", 2: "perc"}.get(self.cb_hpss.currentIndex(), "off")
        w = Worker(self.token, self.path, t0, t1, self.sr, self.nfft, self.win,
                   dc=self.chk_dc.isChecked(),
                   reassign=self.chk_reassign.isChecked(), hpss=hpss)
        w.done.connect(self._on_done)
        w.finished.connect(lambda: self._clean_workers())
        self._workers.append(w)
        w.start()
        self.statusBar().showMessage("计算中…")

    def _clean_workers(self):
        self._workers = [w for w in self._workers if w.isRunning()]

    def _on_done(self, token, res):
        if token != self.token:
            return
        if "error" in res:
            self.statusBar().showMessage("解码失败：" + res["error"][:200])
            return
        self.cache = res
        self.render()
        self.statusBar().showMessage(
            f"{os.path.basename(self.path)}｜视图 {self.view[0]:.2f}–{self.view[1]:.2f}s"
            f"｜sr {self.sr}｜FFT {self.nfft}｜{res['spec'].shape[0]} 列")

    # ---------- 绘制 ----------
    def render(self):
        c = self.cache
        if c is None:
            return
        t0, t1 = self.view
        F = c["freqs"].astype(np.float64)
        D = c["spec"]

        # 视图落在已算范围内 → 直接按列切片，立刻变清晰
        if (c["abs_t0"] - 1e-6 <= t0 and t1 <= c["abs_t1"] + 1e-6
                and (t1 - t0) < (c["abs_t1"] - c["abs_t0"]) * 0.99):
            ncols = D.shape[0]
            ct = np.linspace(c["abs_t0"], c["abs_t1"], ncols)
            sel = (ct >= t0) & (ct <= t1)
            if sel.sum() >= 2:
                D = D[sel]

        # 频率范围
        f0, f1 = self.fview
        f0 = max(f0, F[1] if len(F) > 1 else 1.0)
        f1 = min(max(f1, f0 * 1.05), F[-1])
        m = (F >= f0) & (F <= f1)
        if m.sum() < 2:
            m = np.ones_like(F, dtype=bool)
        Fs, Ds = F[m], D[:, m]
        A = c["avg"][m].astype(np.float64)

        if self.logfreq:
            rows = np.geomspace(max(Fs[0], 1.0), Fs[-1], 520)
            Dd = interp_rows(Fs, Ds, rows)
            ylo, yhi = np.log10(max(Fs[0], 1.0)), np.log10(Fs[-1])
            ay = np.log10(np.maximum(Fs, 1.0))
            self._yticks = [np.log10(v) for v in nice_ticks(Fs[0], Fs[-1])]
        else:
            Dd = Ds
            ylo, yhi = Fs[0], Fs[-1]
            ay = Fs
            self._yticks = thin_ticks(Fs[0], Fs[-1])

        # imshow 第一维是行(Y=频率)，我们的数组是 (列=时间, 频点) → 必须转置
        Dd = np.asarray(Dd)

        # —— 显示端增强：去斑 / 谱白化 / CLAHE / gamma，可选对比线 ——
        den = self.chk_denoise.isChecked()
        wh = self.chk_white.isChecked()
        cl = self.chk_clahe.isChecked()
        enh_on = den or wh or cl
        if enh_on:
            disp = display_intensity(Dd, self.dbrange, den, wh, cl,
                                     gamma=self.sp_gamma.value())
            if self.chk_cmp.isChecked():
                raw = np.clip((Dd + self.dbrange) / self.dbrange, 0.0, 1.0)
                n = Dd.shape[0]
                if self.compare_t is None or not (t0 < self.compare_t < t1):
                    self.compare_t = (t0 + t1) / 2.0
                cut = int(np.searchsorted(np.linspace(t0, t1, n), self.compare_t))
                cut = min(max(cut, 1), n - 1)
                disp = np.array(disp, copy=True)
                disp[:cut, :] = raw[:cut, :]     # 左侧保留原图
            Dd, vmin, vmax, cbl = disp, 0.0, 1.0, "增强强度"
        else:
            vmin, vmax, cbl = -self.dbrange, 0.0, "dB"

        Dd = Dd.T

        if self.chk_cmp.isChecked() and enh_on:
            if self.compare_t is None or not (t0 < self.compare_t < t1):
                self.compare_t = (t0 + t1) / 2.0
            if getattr(self, "_divider", None) is None:
                self._divider = self.ax.axvline(
                    self.compare_t, color="#ffffff", lw=1.3,
                    ls=(0, (4, 3)), alpha=0.95, zorder=5)
                self._divider.set_visible(True)
            else:
                self._divider.set_xdata([self.compare_t, self.compare_t])
                self._divider.set_visible(True)
        elif getattr(self, "_divider", None) is not None:
            self._divider.set_visible(False)

        self.ax.set_xlim(t0, t1)
        self.ax.set_ylim(ylo, yhi)
        if getattr(self, "_hint", None) is not None:
            try:
                self._hint.remove()
            except Exception:
                pass
            self._hint = None
            self.ax.tick_params(labelbottom=True, labelleft=True)
            self.ax.xaxis.set_major_locator(MaxNLocator(nbins=10, steps=[1, 2, 5, 10]))

        if self.im is None:
            self.im = self.ax.imshow(Dd, aspect="auto", origin="lower",
                                     interpolation="nearest", cmap=self.cmap,
                                     extent=[t0, t1, ylo, yhi],
                                     vmin=vmin, vmax=vmax)
            self.cb = self.fig.colorbar(self.im, cax=self.cax)
            self.cb.set_label(cbl, fontsize=8, labelpad=6)
            self.cb.ax.tick_params(labelsize=7, pad=1.5, length=2)
        else:
            self.im.set_data(Dd)
            self.im.set_extent([t0, t1, ylo, yhi])
            self.im.set_cmap(self.cmap)
            self.im.set_clim(vmin, vmax)
        if self.cb is not None and getattr(self, "_cbl", None) != cbl:
            self.cb.set_label(cbl, fontsize=8, labelpad=6)
            self._cbl = cbl

        self.axS.clear()
        self.axS.plot(A, ay, lw=0.9, color="#c05621")
        self.axS.set_xlim(-self.dbrange - 3, 3)
        self.axS.tick_params(labelsize=8)
        self.axS.set_xlabel("平均频谱 (dB)", fontsize=8)
        self.axS.grid(alpha=0.25, lw=0.5)
        # 刻度必须在 axS.clear() 之后设，否则共享轴会被重置回默认格式
        self.ax.yaxis.set_major_formatter(FuncFormatter(self._yfmt))
        self.ax.set_yticks(self._yticks)
        self.ax.set_ylabel("频率 (Hz)" + ("，对数" if self.logfreq else ""))
        self.ax.set_title(
            f"{os.path.basename(self.path)}   sr={self.sr}  FFT={self.nfft}  win={self.win}"
            + ("   重分配" if self.chk_reassign.isChecked() else "")
            + ("  HPSS=" + ("谐波" if self.cb_hpss.currentIndex() == 1 else "打击")
               if self.cb_hpss.currentIndex() > 0 else "")
            + ("   增强" if enh_on else ""),
            fontsize=9)
        self.canvas.draw_idle()

    # ---------- 交互 ----------
    def _yfmt(self, v, _pos=None):
        try:
            f = 10 ** v if self.logfreq else v
        except Exception:
            return ""
        return fmt_hz(f)

    def resizeEvent(self, ev):
        """高分屏：只把 figure 的 dpi 跟着设备像素比走，尺寸不变，文字不模糊"""
        super().resizeEvent(ev)
        if self._resizing:
            return
        self._resizing = True
        try:
            ratio = float(self.devicePixelRatioF() or 1.0)
            if abs(self.fig.dpi - 100.0 * ratio) > 1e-6:
                self.fig.set_dpi(100.0 * ratio)
                self.canvas.draw_idle()
        except Exception:
            pass
        finally:
            self._resizing = False

    def _data_freq(self, ev):
        if ev.ydata is None:
            return None
        return 10 ** ev.ydata if self.logfreq else ev.ydata

    def on_scroll(self, ev):
        if self.cache is None or ev.inaxes not in (self.ax, self.axS):
            return
        if ev.xdata is None:
            return
        factor = 1 / 1.35 if ev.button == "up" else 1.35   # 上滚=放大
        shift = ev.key in ("shift", "shift+control", "control+shift")
        if shift:
            ylo, yhi = self.ax.get_ylim()
            anchor = ev.ydata if ev.ydata is not None else (ylo + yhi) / 2
            nlo = anchor - (anchor - ylo) * factor
            nhi = anchor + (yhi - anchor) * factor
            if self.logfreq:
                flo, fhi = 10 ** nlo, 10 ** nhi
                if fhi - flo < 20:
                    return
            self.ax.set_ylim(nlo, nhi)
            if self.logfreq:
                self.fview = (10 ** self.ax.get_ylim()[0], 10 ** self.ax.get_ylim()[1])
            else:
                self.fview = tuple(self.ax.get_ylim())
            self.canvas.draw_idle()
            return
        t0, t1 = self.ax.get_xlim()
        anchor = min(max(ev.xdata, t0), t1)
        n0 = anchor - (anchor - t0) * factor
        n1 = anchor + (t1 - anchor) * factor
        n0 = max(n0, 0.0)
        n1 = min(n1, self.dur)
        if n1 - n0 < 0.002:
            return
        self.view = (n0, n1)
        self.ax.set_xlim(n0, n1)
        self.canvas.draw_idle()
        self._timer.start()

    def on_press(self, ev):
        # 双双击自己判：只信任“400ms 内、位置几乎没动”的第二次按下。
        # 不能用 ev.dblclick —— 它由系统合成事件驱动，拖拽的第一次按下有可能被当成双击，
        # 一拖就跳回全览。
        now = time.time()
        if ev.button == 1 and ev.inaxes in (self.ax, self.axS) and ev.x is not None:
            pt, px, py = self._last_click
            if (now - pt < 0.4 and abs(ev.x - px) < 8 and abs(ev.y - py) < 8):
                self._last_click = (0.0, 0.0, 0.0)
                self.fit_all()
                return
            self._last_click = (now, ev.x, ev.y)
        elif ev.button == 1:
            self._last_click = (0.0, 0.0, 0.0)
        if ev.button != 1 or ev.inaxes not in (self.ax, self.axS):
            return
        # 按住对比线时拖分隔线，不平移
        if (self.chk_cmp.isChecked() and self.compare_t is not None
                and ev.xdata is not None):
            span = max(self.view[1] - self.view[0], 1e-9)
            if abs(ev.xdata - self.compare_t) < span * 0.012:
                self._div_drag = True
                return
        self._drag = {"x": ev.x, "y": ev.y,
                      "xl": self.ax.get_xlim(), "yl": self.ax.get_ylim(),
                      "t0": self.view}

    def on_motion(self, ev):
        if self._div_drag and ev.xdata is not None:
            t0, t1 = self.ax.get_xlim()
            self.compare_t = float(min(max(ev.xdata, t0), t1))
            if self._divider is not None:
                self._divider.set_xdata([self.compare_t, self.compare_t])
            self.render()
            return
        if self.cache is not None and ev.inaxes in (self.ax, self.axS):
            f = self._data_freq(ev)
            if f and ev.xdata is not None:
                self.statusBar().showMessage(
                    f"t = {ev.xdata:.3f} s ｜ f = {f:.0f} Hz ｜ 滚轮缩放时间轴，Shift+滚轮缩放频率轴，拖动平移，双击全览")
        if self._drag is None or ev.x is None:
            return
        dx = ev.x - self._drag["x"]
        dy = ev.y - self._drag["y"]
        if abs(dx) < 3 and abs(dy) < 3:
            return
        ax = self.ax
        x0, x1 = self._drag["xl"]
        p0 = ax.transData.transform((x0, 0))[0]
        p1 = ax.transData.transform((x1, 0))[0]
        if abs(p1 - p0) < 1:
            return
        dt = -(dx / (p1 - p0)) * (x1 - x0)
        n0, n1 = x0 + dt, x1 + dt
        span = x1 - x0
        if n0 < 0:
            n0, n1 = 0, span
        if n1 > self.dur:
            n0, n1 = self.dur - span, self.dur
        self.ax.set_xlim(n0, n1)
        self.view = (n0, n1)

        ylo, yhi = self._drag["yl"]
        q0 = ax.transData.transform((0, ylo))[1]
        q1 = ax.transData.transform((0, yhi))[1]
        if abs(q1 - q0) > 1 and dy:
            dyy = -(dy / (q1 - q0)) * (yhi - ylo)
            self.ax.set_ylim(ylo + dyy, yhi + dyy)
            if self.logfreq:
                self.fview = (10 ** self.ax.get_ylim()[0], 10 ** self.ax.get_ylim()[1])
            else:
                self.fview = tuple(self.ax.get_ylim())
        self.canvas.draw_idle()

    def on_release(self, ev):
        if self._div_drag:
            self._div_drag = False
            return
        if self._drag is None:
            return
        moved = abs(ev.x - self._drag["x"]) > 3 or abs(ev.y - self._drag["y"]) > 3
        t_changed = self._drag["t0"] != self.view
        self._drag = None
        if moved and t_changed:
            self._timer.start()          # 拖完再算，避免狂刷 ffmpeg

    # ---------- 播放 ----------
    def toggle_play(self):
        if sd is None:
            self.statusBar().showMessage("没装 sounddevice，无法播放")
            return
        if self._ptimer.isActive():
            self.stop_play()
            return
        if not self.path:
            return
        t0, t1 = self.view
        t1 = min(t1, t0 + 60.0)
        try:
            x = decode(self.path, t0, t1, self.sr).astype(np.float32)
        except Exception as e:
            self.statusBar().showMessage("播放失败：" + str(e)[:150])
            return
        peak = float(np.max(np.abs(x))) or 1.0
        sd.play(x / max(peak, 1e-9) * 0.9, self.sr)
        self._play_t0 = t0
        self._play_when = time.time()
        self._ptimer.start()
        self.btn_play.setText("■ 停止")
        if self.view[1] - self.view[0] > 60:
            self.statusBar().showMessage("视图超过 60 秒，只播放前 60 秒")

    def stop_play(self):
        if sd is not None:
            sd.stop()
        self._ptimer.stop()
        if self._cursor is not None:
            try:
                self._cursor.remove()
            except Exception:
                pass
            self._cursor = None
        self.btn_play.setText("▶ 播放")
        self.canvas.draw_idle()

    def _tick_play(self):
        t = self._play_t0 + (time.time() - self._play_when)
        if t > self.view[1] or t > self._play_t0 + 60.0:
            self.stop_play()
            return
        if self._cursor is None:
            self._cursor = self.ax.axvline(t, color="#00e5ff", lw=1.2)
        else:
            self._cursor.set_xdata([t, t])
        self.canvas.draw_idle()

    # ---------- 导出 ----------
    def export_png(self):
        if not self.path:
            return
        base = os.path.splitext(os.path.basename(self.path))[0]
        sug = os.path.join(os.path.dirname(self.path),
                           f"{base}_{self.view[0]:.1f}-{self.view[1]:.1f}s.png")
        f, _ = QtWidgets.QFileDialog.getSaveFileName(self, "导出图片", sug, "PNG (*.png)")
        if not f:
            return
        try:
            self.fig.savefig(f, dpi=220)
            self.statusBar().showMessage("已保存：" + f)
        except Exception as e:
            self.statusBar().showMessage("保存失败：" + str(e)[:150])

    def closeEvent(self, ev):
        self.stop_play()
        for w in list(self._workers):
            w.wait(300)
        super().closeEvent(ev)


def selftest(path):
    d = probe_duration(path)
    print("时长", round(d, 3))
    x = decode(path, 0, min(5.0, d), DEFAULT_SR)
    print("采样点", x.size, "峰值", float(np.max(np.abs(x))))
    for nfft in (512, 2048):
        r = compute_stft(x, DEFAULT_SR, nfft, "hann")
        top = np.argsort(r["avg"])[::-1][:3]
        print(f"nfft={nfft} 形状={r['spec'].shape} 主峰={[round(float(r['freqs'][i])) for i in top]} Hz")
    r = compute_stft(x, DEFAULT_SR, 1024, "hann")
    F = r["freqs"].astype(float)
    rows = np.geomspace(max(F[1], 1), F[-1], 300)
    D = interp_rows(F, r["spec"], rows)
    print("对数网格", D.shape, "dB 范围", round(float(D.min()), 1), "~", round(float(D.max()), 1))
    fig = plt.figure(figsize=(8, 3))
    ax = fig.add_subplot(111)
    im = ax.imshow(D.T, aspect="auto", origin="lower", cmap="magma", vmin=-70, vmax=0)
    fig.colorbar(im, ax=ax)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_selftest.png")
    fig.savefig(out, dpi=90)
    print("selftest 通过，图：", out)


def hide_own_console():
    """双击 .py 由 python.exe 启动时会多一个黑框控制台：只隐藏“我们自己独占”的那个
    （GetConsoleProcessList 只返回本进程 = 这个控制台是新建给我们的；从终端启动则返回 2+，不动）"""
    if os.name != "nt":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        arr = (ctypes.c_uint * 8)()
        n = k32.GetConsoleProcessList(arr, 8)
        if n == 1:
            hwnd = k32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)   # SW_HIDE
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="交互式音频频谱查看器")
    ap.add_argument("file", nargs="?", help="音频/视频文件")
    ap.add_argument("--sr", type=int, default=DEFAULT_SR)
    ap.add_argument("--nfft", type=int, default=1024)
    ap.add_argument("--logfreq", action="store_true")
    ap.add_argument("--t0", type=float, default=0.0, help="初始起点 秒")
    ap.add_argument("--t1", type=float, default=0.0, help="初始终点 秒")
    ap.add_argument("--selftest", action="store_true", help="不开窗口，自检解码与 STFT")
    a = ap.parse_args()
    if a.selftest:
        selftest(a.file or "test.wav")
        return
    hide_own_console()
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    app = QtWidgets.QApplication(sys.argv)
    app.setFont(QtGui.QFont("Microsoft YaHei", 9))
    w = Viewer(a.file, a.sr, a.nfft, a.logfreq,
               init_view=(a.t0, a.t1) if a.t1 > a.t0 else None)
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
