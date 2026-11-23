# -*- coding: utf-8 -*-
"""
compile_kmodel.py（在 WSL Ubuntu 里跑）—— ONNX + 校准集 -> k230 kmodel

用法（WSL 里）：
    ~/nn313/bin/python /mnt/c/chatbox_temp/compile_kmodel.py \
        --onnx  /mnt/c/chatbox_temp/work/export/student_sim.onnx \
        --calib /mnt/c/chatbox_temp/work/export/calib.npy \
        --out   /mnt/c/chatbox_temp/work/export/style.kmodel \
        --hw 768 608

    # 掉点时换校准方法
    ... --calibrate Kld
    # 首尾层提精度（导出量化参数后手改再回灌）
    ... --export-quant-scheme ./quant_scheme.json

环境（脚本会自己设好，不用你记）：
    DOTNET_ROLL_FORWARD=LatestMajor            nncase 要 .NET 7，Ubuntu 26.04 是 .NET 10
    NNCASE_PLUGIN_PATH=<site-packages>/nncase_kpu
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# ---- 必须在 import nncase 之前设好，否则 nncase 初始化就炸
os.environ.setdefault("DOTNET_ROLL_FORWARD", "LatestMajor")
os.environ.setdefault("DOTNET_ROLL_FORWARD_TO_PRERELEASE", "1")
try:
    import nncase_kpu
    os.environ.setdefault("NNCASE_PLUGIN_PATH", os.path.dirname(nncase_kpu.__file__))
except ImportError:
    print("!! 没装 nncase-kpu。装： pip install nncase-kpu==2.11.0")
    sys.exit(2)

import numpy as np  # noqa: E402


def parse():
    ap = argparse.ArgumentParser("ONNX -> k230 kmodel")
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--calib", required=True, help="calib.npy（NHWC uint8），export_onnx.py 产出")
    ap.add_argument("--out", required=True)
    ap.add_argument("--hw", type=int, nargs=2, default=[768, 608], help="高 宽（NCHW 里的 H W）")
    ap.add_argument("--calibrate", default="NoClip", choices=["NoClip", "Kld", "MinMax"])
    ap.add_argument("--quant_type", default="uint8", choices=["uint8", "int8", "int16"])
    ap.add_argument("--w_quant_type", default="int8", choices=["int8", "int16"])
    ap.add_argument("--mean", type=float, nargs=3, default=[0.0, 0.0, 0.0],
                    help="nncase 预处理均值。归一化已经写进图里了，这里保持 0")
    ap.add_argument("--std", type=float, nargs=3, default=[1.0, 1.0, 1.0])
    ap.add_argument("--export-quant-scheme", default=None,
                    help="把量化参数导出成 json，用于手改首尾层精度后回灌")
    ap.add_argument("--quant-scheme", default=None, help="回灌手改后的量化参数 json")
    ap.add_argument("--dump-dir", default=None, help="导出 IR/汇编，排查编译问题时用")
    ap.add_argument("--calib-limit", type=int, default=0, help="只用前 N 张校准（调试）")
    return ap.parse_args()


def main():
    a = parse()
    H, W = a.hw

    print("=" * 70)
    print("环境")
    print("  DOTNET_ROLL_FORWARD  =", os.environ.get("DOTNET_ROLL_FORWARD"))
    print("  NNCASE_PLUGIN_PATH   =", os.environ.get("NNCASE_PLUGIN_PATH"))

    import nncase
    print("  nncase 已初始化")

    # ---------------- 校准集 ----------------
    calib = np.load(a.calib)                      # (N,H,W,3) uint8
    if a.calib_limit:
        calib = calib[:a.calib_limit]
    if calib.shape[1:3] != (H, W):
        print(f"  !! 校准集尺寸 {calib.shape[1:3]} 和 --hw {(H, W)} 对不上")
        sys.exit(3)
    print(f"\n校准集：{calib.shape} uint8，"
          f"共 {calib.shape[0]} 张，像素范围 [{calib.min()}, {calib.max()}]")

    cali = [nncase.RuntimeTensor.from_numpy(
        np.ascontiguousarray(c.transpose(2, 0, 1)[None])) for c in calib]   # NHWC -> NCHW
    print("  已转成 NCHW RuntimeTensor")

    # ---------------- 编译配置 ----------------
    opt = nncase.CompileOptions()
    opt.target = "k230"
    opt.input_shape = [1, 3, H, W]
    opt.input_type = "uint8"
    opt.input_range = [0, 255]
    opt.input_layout = "NCHW"
    opt.output_layout = "NCHW"
    opt.preprocess = True
    opt.mean = list(a.mean)
    opt.std = list(a.std)
    opt.quant_type = a.quant_type
    opt.w_quant_type = a.w_quant_type
    if a.dump_dir:
        opt.dump_dir = a.dump_dir
        opt.dump_ir = True
        opt.dump_asm = True
    print(f"\n编译配置：target=k230 input=1x3x{H}x{W} uint8[{0},{255}] "
          f"quant={a.quant_type} w_quant={a.w_quant_type}")

    onnx_bytes = Path(a.onnx).read_bytes()
    print(f"ONNX：{a.onnx}  ({len(onnx_bytes)/1e6:.1f} MB)")

    c = nncase.Compiler(opt)
    t0 = time.time()
    c.import_onnx(onnx_bytes, "student")
    print(f"  import_onnx OK ({time.time()-t0:.1f}s)")

    # ---------------- PTQ ----------------
    ptq = nncase.PTQTensorOptions()
    ptq.samples_count = len(cali)
    ptq.calibrate_method = a.calibrate
    ptq.input_mean = list(a.mean)
    ptq.input_std = list(a.std)
    ptq.cali_data = cali                    # 注意：必须是 RuntimeTensor
    if a.export_quant_scheme:
        ptq.export_quant_scheme = True
    if a.quant_scheme:
        import json
        ptq.quant_scheme = json.loads(Path(a.quant_scheme).read_text())
    c.use_ptq(ptq)
    print(f"  PTQ：{len(cali)} 张校准，方法 {a.calibrate}")

    # ---------------- 编译 ----------------
    t0 = time.time()
    c.compile()
    print(f"  compile() OK ({time.time()-t0:.1f}s)")

    km = c.gencode_tobytes()                # 注意：gencode() 需要 stream，用这个
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(km)
    print(f"  gencode OK -> {out}  ({len(km)/1e6:.2f} MB)")

    # ---------------- 量化参数导出 ----------------
    if a.export_quant_scheme:
        try:
            qs = ptq.quant_scheme
            p = Path(a.export_quant_scheme)
            p.write_text(json.dumps(qs), encoding="utf-8")
            print(f"  量化参数 -> {p}（改完用 --quant-scheme 回灌）")
        except Exception as e:
            print("  导出量化参数失败：", e)

    print("\n" + "=" * 70)
    print("完成。下一步：")
    print(f"  1) 把 {out.name} 拷到 SD 卡 /sdcard/")
    print("  2) 跑板端 MicroPython 脚本（AI2D 预处理 + KPU 推理 + 与模板合成）")
    print("  3) 量耗时：单帧多少 ms、工作内存多少（编译日志里也有）")
    print("\n掉点时的调整顺序（按性价比）：")
    print("  ① 换校准集（必须是真实推理分布） ② --calibrate Kld")
    print("  ③ --export-quant-scheme 导出后手改首尾层为 int16，再 --quant-scheme 回灌")


if __name__ == "__main__":
    main()
