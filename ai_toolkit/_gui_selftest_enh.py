# -*- coding: utf-8 -*-
"""离屏验证：重分配 / HPSS / 谱白化 / CLAHE / 对比线"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, r"C:\chatbox_temp\ai_toolkit")

from PyQt5 import QtWidgets  # noqa: E402
import audio_spectrum_gui as g  # noqa: E402

app = QtWidgets.QApplication(sys.argv)
path = r"C:\Users\yourname\Desktop\db79e3ce4f873bea70d1fbb5d08d03e4.mp4"
out_dir = r"C:\chatbox_temp\ai_toolkit"
v = g.Viewer(path, 22050, 1024, True, init_view=(1230.0, 1238.0))
v.show()


def settle(timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if v.cache is not None and not any(w.isRunning() for w in v._workers) and not v._timer.isActive():
            app.processEvents()
            return
        time.sleep(0.05)


settle()
print("初始", v.cache["spec"].shape, "列数", v.cache["spec"].shape[0])
v.fig.savefig(os.path.join(out_dir, "_enh_0_plain.png"), dpi=110)

t = time.time()
v.chk_reassign.setChecked(True)
settle()
print(f"重分配: {time.time()-t:.1f}s, 形状={v.cache['spec'].shape}, flags={v.cache.get('flags')}")
v.fig.savefig(os.path.join(out_dir, "_enh_1_reassign.png"), dpi=110)

t = time.time()
v.cb_hpss.setCurrentIndex(1)     # 只留谐波
settle()
print(f"重分配+谐波: {time.time()-t:.1f}s, flags={v.cache.get('flags')}")
v.fig.savefig(os.path.join(out_dir, "_enh_2_harm.png"), dpi=110)

v.cb_hpss.setCurrentIndex(2)     # 只留打击
settle()
v.fig.savefig(os.path.join(out_dir, "_enh_3_perc.png"), dpi=110)
print("打击完成 flags=", v.cache.get("flags"))

v.cb_hpss.setCurrentIndex(0)
v.chk_reassign.setChecked(False)
settle()

t = time.time()
v.chk_denoise.setChecked(True)
v.chk_white.setChecked(True)
v.chk_clahe.setChecked(True)
app.processEvents()
print(f"显示增强渲染: {(time.time()-t)*1000:.0f} ms")
v.fig.savefig(os.path.join(out_dir, "_enh_4_display.png"), dpi=110)

v.chk_cmp.setChecked(True)
app.processEvents()
print("对比线存在:", v._divider is not None, "compare_t=", v.compare_t)
v.fig.savefig(os.path.join(out_dir, "_enh_5_compare.png"), dpi=110)

# 拖分隔线
class E:
    xdata = 1234.0
    ydata = None
v._div_drag = True
v.on_motion(E())
v._div_drag = False
print("拖动后 compare_t=", round(v.compare_t, 2))

print("clim=", v.im.get_clim(), "| colorbar 标签=", v.cb.ax.get_ylabel())
v.close()
print("done")
