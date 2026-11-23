# -*- coding: utf-8 -*-
"""频谱查看器（窗口版启动器）
双击本文件不会出现黑色控制台窗口：.pyw 一律由 pythonw.exe 打开。
真正干活的是同目录的 audio_spectrum_gui.py。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import audio_spectrum_gui as gui
except Exception as exc:  # 出错时用消息框，别让错误“静默消失”
    import ctypes
    ctypes.windll.user32.MessageBoxW(
        0, "启动失败：\n\n%s" % exc, "频谱查看器", 0x10)
    raise

if __name__ == "__main__":
    gui.main()
