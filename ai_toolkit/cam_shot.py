# -*- coding: utf-8 -*-
"""本机摄像头拍照（Windows 通用）。

用法:
  python cam_shot.py                          # 默认输出 Desktop/working!/webcam_<时间>.jpg
  python cam_shot.py out.jpg                  # 指定输出
  python cam_shot.py out.jpg --index 1        # 指定设备索引
  python cam_shot.py out.jpg --w 1920 --h 1080

要点（踩过的坑）:
  1. 帧缓冲会被复用 -> 保存候选帧必须 f.copy()，否则存下来的是最后那个黑帧。
  2. 设备常间歇性返回全黑帧（ASUS 机器实测）-> 连续读若干帧，
     先过滤 mean>20，再按 Laplacian 方差挑最清晰的一张。
  3. 只有 imageio/ffmpeg 更稳时就优先 ffmpeg（DirectShow 出图成功率高）。
     ffmpeg 抓完可能不退出（dshow 线程），所以用 -frames:v 1 + 超时。
  4. 索引探测：ffmpeg -f dshow -list_devices true -i dummy
     虚拟摄像头（OBS Virtual Camera）会排在真机后面，别抓错。
"""
import argparse, os, sys, time, glob, subprocess, datetime

def pick(out, index, W, H):
    import cv2, numpy as np
    cands = []
    for backend, name in [(cv2.CAP_MSMF, "MSMF"), (cv2.CAP_DSHOW, "DSHOW")]:
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release(); continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
        t0 = time.time()
        got = 0
        while time.time() - t0 < 4.0 and got < 40:
            ok, f = cap.read()
            if not ok or f is None:
                time.sleep(0.05); continue
            f = f.copy()                      # 坑 1
            got += 1
            g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            if float(g.mean()) < 20:          # 坑 2
                continue
            sh = float(cv2.Laplacian(g, cv2.CV_64F).var())
            cands.append((sh, float(g.mean()), f))
        cap.release()
        print(f"[{name}] frames={got} usable={len(cands)}", file=sys.stderr)
        if cands:
            break
    if not cands:
        return None
    cands.sort(key=lambda x: -x[0])
    sh, m, f = cands[0]
    print(f"picked sharp={sh:.2f} mean={m:.1f} size={f.shape[1]}x{f.shape[0]}", file=sys.stderr)
    return f

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=None)
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--w", type=int, default=1920)
    ap.add_argument("--h", type=int, default=1080)
    a = ap.parse_args()

    out = a.out or os.path.join(
        os.path.expanduser("~"), "Desktop", "working!",
        "webcam_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".jpg")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    f = pick(out, a.index, a.w, a.h)
    if f is None:
        print("ERROR: 没有拿到有效画面（检查隐私快门/占用/索引）", file=sys.stderr)
        sys.exit(1)
    import cv2
    cv2.imwrite(out, f, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    print(out)

if __name__ == "__main__":
    main()
