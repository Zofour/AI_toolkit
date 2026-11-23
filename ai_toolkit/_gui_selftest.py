# -*- coding: utf-8 -*-
"""离屏功能自检：不弹窗、不抢鼠标，验证 载入/缩放/平移/播放/导出 逻辑"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\chatbox_temp\ai_toolkit")

from PyQt5 import QtWidgets  # noqa: E402
import audio_spectrum_gui as g  # noqa: E402

app = QtWidgets.QApplication(sys.argv)


class FakeEv:
    def __init__(self, **kw):
        self.dict = kw
        self.inaxes = kw.get("inaxes")
        self.xdata = kw.get("xdata")
        self.ydata = kw.get("ydata")
        self.button = kw.get("button")
        self.key = kw.get("key", "")
        self.x = kw.get("x")
        self.y = kw.get("y")
        self.dblclick = kw.get("dblclick", False)


def wait(w, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if w.cache is not None:
            return True
        time.sleep(0.05)
    return False


def settle(w, timeout=40):
    """等后台线程算完（参数改动后调用）"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if not any(x.isRunning() for x in w._workers) and not w._timer.isActive():
            app.processEvents()
            return True
        time.sleep(0.05)
    return False


path = sys.argv[1]
v = g.Viewer(path, g.DEFAULT_SR, 1024, True)
v.show()
ok = wait(v)
print("载入+计算:", ok, "| view=", [round(x, 2) for x in v.view])
print("  形状", v.cache["spec"].shape, "| 频率上限", round(float(v.cache["freqs"][-1])))

# 初始渲染
v.render()
app.processEvents()
print("渲染 xlim", [round(x, 2) for x in v.ax.get_xlim()], "ylim", [round(x, 2) for x in v.ax.get_ylim()])
print("y 刻度标签:", [t.get_text() for t in v.ax.get_yticklabels()][:8])

# 滚轮放大（时间轴）
box = v.ax.get_window_extent()
cx, cy = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
t_before = v.view
for _ in range(6):
    v.on_scroll(FakeEv(inaxes=v.ax, xdata=(v.view[0] + v.view[1]) / 2,
                       ydata=v.ax.get_ylim()[0] + 0.3, button="up", key=""))
v._timer.stop()
app.processEvents()
print("滚轮放大后 view=", [round(x, 3) for x in v.view], "(变窄 =", v.view[1] - v.view[0] < t_before[1] - t_before[0], ")")

# 触发重算
v._recompute()
settle(v)

# 拖动平移
v.on_press(FakeEv(inaxes=v.ax, x=cx, y=cy, button=1, xdata=(v.view[0] + v.view[1]) / 2,
                  ydata=(v.ax.get_ylim()[0] + v.ax.get_ylim()[1]) / 2))
t_pre = v.view
v.on_motion(FakeEv(inaxes=v.ax, x=cx - 200, y=cy,
                   xdata=(v.view[0] + v.view[1]) / 2, ydata=(v.ax.get_ylim()[0] + v.ax.get_ylim()[1]) / 2))
v.on_release(FakeEv(x=cx - 200, y=cy))
app.processEvents()
print("拖动后 view=", [round(x, 3) for x in v.view], "(平移了", round(v.view[0] - t_pre[0], 3), "s)")
v._timer.stop()

# Shift+滚轮缩放频率轴
fy = v.ax.get_ylim()
v.on_scroll(FakeEv(inaxes=v.ax, xdata=(v.view[0] + v.view[1]) / 2,
                   ydata=(fy[0] + fy[1]) / 2, button="up", key="shift"))
print("频率轴缩放:", [round(x, 2) for x in fy], "->", [round(x, 2) for x in v.ax.get_ylim()])

# 改参数：采样率 / FFT / 去直流 / 色图
v.cb_sr.setCurrentText("8000")
app.processEvents()
settle(v)
print("改 8000Hz 后 sr =", v.sr, "频率上限", round(float(v.cache["freqs"][-1])))
v.cb_nfft.setCurrentText("2048")
app.processEvents()
settle(v)
print("FFT 2048 后 nfft =", v.nfft, "bin 数", v.cache["spec"].shape[1])
v.chk_dc.setChecked(False)
app.processEvents()
settle(v)
v.chk_dc.setChecked(True)
app.processEvents()
settle(v)
print("去直流开关后 sr =", v.sr, "nfft =", v.nfft)
v.cb_cmap.setCurrentText("turbo")
v.sp_db.setValue(55)
app.processEvents()

# 播放 1.5 秒
v.toggle_play()
print("播放启动:", v._ptimer.isActive(), "| 按钮文字", v.btn_play.text())
time.sleep(1.2)
v._tick_play()
app.processEvents()
print("播放光标:", v._cursor is not None)
v.stop_play()
print("停止后按钮", v.btn_play.text())

# 导出
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_gui_selftest.png")
v.fig.savefig(out, dpi=110)
print("导出图:", out, os.path.getsize(out), "bytes")

# 全览
v.fit_all()
settle(v)
print("全览 view=", [round(x, 1) for x in v.view], "列数", v.cache["spec"].shape[0])
v.fig.savefig(os.path.join(os.path.dirname(out), "_gui_selftest_all.png"), dpi=110)
v.close()
print("自检结束")
