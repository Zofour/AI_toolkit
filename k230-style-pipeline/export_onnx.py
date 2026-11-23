# -*- coding: utf-8 -*-
"""
export_onnx.py（在 Windows 上跑）—— 学生网络 -> ONNX -> 简化 -> ORT 数值对齐 -> 导出校准集

板端链路：
    pth  --(本脚本)-->  onnx  --(WSL 里的 compile_kmodel.py)-->  kmodel  -->  K230

本脚本做四件事：
  1) 加载 student_fused.pth（BN 已折叠 -> 图里没有 BatchNormalization 节点，这是 nncase 的要求）
  2) 把「归一化」和「输出映射到 0~255」**写进 ONNX 图里**：
       输入 uint8 [0,255] -> (x-127.5)/127.5 -> 网络 -> tanh[-1,1] -> (y+1)*127.5 -> 输出 [0,255]
     这样板端 AI2D 吐出来的 uint8 可以直连模型，输出也能直接当图像用，零后处理。
  3) onnxsim 化简 + 用 ONNX Runtime 跟 PyTorch 对数值，误差超标就**报错退出**
  4) 从真实样本里抽 200 张，导出成 calib.npy 给 WSL 做 PTQ 校准

用法：
    python export_onnx.py --ckpt .\\work\\student\\student_fused.pth ^
        --pairs C:\\chatbox_temp\\work\\m1 --out .\\work\\export --hw 768 608
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def need(pkgs):
    miss = []
    for p in pkgs:
        try:
            __import__(p)
        except ImportError:
            miss.append(p)
    if miss:
        print("缺少依赖：" + ", ".join(miss))
        print("装一下： python -m pip install " + " ".join(miss))
        print("（国内加速： -i https://pypi.tuna.tsinghua.edu.cn/simple）")
        sys.exit(2)


need(["torch", "cv2", "onnx", "onnxruntime"])

import cv2  # noqa: E402
import torch  # noqa: E402
import torch.nn as nn  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_distill import StudentNet, fuse_bn  # noqa: E402


def _imread(path):
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


class ExportWrapper(nn.Module):
    """
    把预处理/后处理都塞进图里，让板端只认 uint8。
      x: uint8 语义的 float [0,255]
    这样 K230 侧：AI2D 输出 uint8 -> 直接喂 -> 取回 uint8 就是成图
    """

    def __init__(self, net, norm=True, to_u8=True):
        super().__init__()
        self.net = net
        self.norm = norm
        self.to_u8 = to_u8

    def forward(self, x):
        if self.norm:
            x = (x - 127.5) / 127.5
        y = self.net(x)
        if self.to_u8:
            y = (y + 1.0) * 127.5
        return y


def parse():
    ap = argparse.ArgumentParser("导出学生网络到 ONNX")
    ap.add_argument("--residual", action="store_true",
                    help="按残差模型导出（out = 输入 + 网络增量）。若 ckpt 旁有 model_info.json 会自动识别；"
                         "漏加会让 ONNX 只输出增量，板端得到灰底幽灵图")
    ap.add_argument("--in_skip", action="store_true",
                    help="架构启用 1/1 输入 skip（必须和训练时一致，否则键不匹配）；有 model_info.json 会自动识别")
    ap.add_argument("--ckpt", required=True,
                    help="学生权重。**推荐用 student.pth（未折叠版）**，本脚本会自己折叠 BN。\n"
                         "        student_fused.pth 也能用，但要加 --already-fused")
    ap.add_argument("--already-fused", action="store_true",
                    help="ckpt 已经是折叠过的（conv 带 bias）")
    ap.add_argument("--pairs", required=True, help="gen_m1.py 的输出目录，用来抽校准集")
    ap.add_argument("--out", required=True)
    ap.add_argument("--hw", type=int, nargs=2, default=[768, 608], help="高 宽")
    ap.add_argument("--base", type=int, default=32)
    ap.add_argument("--opset", type=int, default=13)
    ap.add_argument("--calib", type=int, default=200, help="校准集张数")
    ap.add_argument("--atol", type=float, default=1e-3,
                    help="ORT 与 PyTorch 的最大允许误差（单位是 0~255 的灰阶）")
    ap.add_argument("--no-norm", dest="norm", action="store_false", default=True,
                    help="不把归一化写进图里（交给 nncase 的 mean/std）")
    ap.add_argument("--no-u8", dest="to_u8", action="store_false", default=True,
                    help="输出保持 [-1,1] 浮点")
    ap.add_argument("--skip-sim", action="store_true", help="跳过 onnxsim")
    ap.add_argument("--dynamo", action="store_true", default=False,
                    help="用新版 dynamo 导出器（需要 onnxscript）。默认用旧版，算子更干净可控")
    return ap.parse_args()


def main():
    a = parse()
    H, W = a.hw
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    # ---------------- 1. 载模型 ----------------
    # 先读 model_info.json：residual / in_skip 决定网络结构，必须在建模前就知道
    info_cfg = {}
    for cand in (Path(a.ckpt).parent / "model_info.json",
                 Path(a.ckpt).parent.parent / "model_info.json"):
        if cand.exists():
            try:
                info_cfg = json.loads(cand.read_text(encoding="utf-8"))
                print("[0] 读到 %s -> residual=%s in_skip=%s base=%s"
                      % (cand, info_cfg.get("residual"), info_cfg.get("in_skip"), info_cfg.get("base")))
            except Exception as e:
                print("[0] 读 %s 失败: %r" % (cand, e))
            break
    a.in_skip = bool(getattr(a, "in_skip", False) or info_cfg.get("in_skip"))
    net = StudentNet(base=a.base, in_skip=a.in_skip)
    if a.in_skip:
        print("[0] 已启用 1/1 输入 skip（head 直接看到原图）")
    sd = torch.load(a.ckpt, map_location="cpu")
    if not a.already_fused:
        # 未折叠版：键必须严格匹配，不许静默丢参数
        try:
            net.load_state_dict(sd, strict=True)
        except RuntimeError as e:
            msg = str(e)
            print("[1] 载入失败（键不匹配）。")
            print(f"    {msg[:300]}")
            print("    -> 如果这个 ckpt 是 student_fused.pth，请加 --already-fused")
            print("    -> 否则检查 --base 是否和训练时一致")
            sys.exit(1)
        net.eval()
        print(f"[1] 载入 {a.ckpt}（未折叠版，键完全匹配 ✓）")
        # BN 折叠：折叠后 conv 会多出 bias，所以**必须在同一进程里先建模再折叠**，
        # 不能拿折叠后的 ckpt 去套一个新模型（会静默丢 bias）。
        net = fuse_bn(net)
    else:
        net.load_state_dict(sd, strict=True)
        net.eval()
        print(f"[1] 载入 {a.ckpt}（已是折叠版）")

    n_bn = sum(1 for m in net.modules() if isinstance(m, nn.BatchNorm2d))
    n_par = sum(p.numel() for p in net.parameters())
    print(f"    参数量 {n_par/1e6:.2f} M；剩余 BatchNorm2d 模块 {n_bn} 个 "
          f"{'（已折叠，ONNX 里不会出现 BatchNormalization 节点 ✓）' if n_bn == 0 else '（!! 没折叠干净）'}")
    if n_bn:
        sys.exit(1)

    # ---- 残差学习：必须和训练时一致，否则 ONNX 只输出"增量"（板端 = 灰底幽灵图）----
    if not a.residual:
        for cand in (Path(a.ckpt).parent / "model_info.json",
                     Path(a.ckpt).parent.parent / "model_info.json"):
            if cand.exists():
                try:
                    info = json.loads(cand.read_text(encoding="utf-8"))
                    if info.get("residual"):
                        a.residual = True
                        print("[1b] 从 %s 读到 residual=True，自动按残差模型导出" % cand)
                except Exception as e:
                    print("[1b] 读 %s 失败: %r" % (cand, e))
                break
    net.residual = bool(a.residual)
    print("[1b] 残差学习 = %s（out = 输入 + 网络增量）" % ("开" if net.residual else "关"))
    if not net.residual:
        print("     提醒：若这个 ckpt 是 --residual 训练的，这里必须是\"开\"，否则板端会得到灰底幽灵图。")

    wrap = ExportWrapper(net, norm=a.norm, to_u8=a.to_u8).eval()

    # ---------------- 2. 导出 ONNX ----------------
    dummy = torch.rand(1, 3, H, W) * 255.0          # uint8 语义的 float
    onnx_raw = out / "student.onnx"
    torch.onnx.export(
        wrap, dummy, str(onnx_raw),
        input_names=["input"], output_names=["output"],
        opset_version=a.opset, do_constant_folding=True,
        dynamic_axes=None,                           # 静态 shape
        dynamo=a.dynamo,
    )
    print(f"[2] 导出 ONNX -> {onnx_raw}  (opset {a.opset}, 静态 shape 1x3x{H}x{W})")

    import onnx

    m = onnx.load(str(onnx_raw))
    onnx.checker.check_model(m)
    ops = sorted({n.op_type for n in m.graph.node})
    print(f"    图里用到的算子：{ops}")
    bad = {"InstanceNormalization", "GroupNormalization", "LayerNormalization",
           "GridSample", "DeformConv", "Gelu", "Erf", "Bernoulli"}
    hit = bad & set(ops)
    if hit:
        print(f"    !! 出现 nncase 不支持的算子：{hit}")
        sys.exit(3)
    if "BatchNormalization" in ops:
        print("    !! 还有 BatchNormalization 节点，说明 ckpt 不是 student_fused.pth")
        sys.exit(3)
    if "ConvTranspose" in ops:
        print("    !! 出现 ConvTranspose，方案要求用 Resize+Conv")
        sys.exit(3)
    print("    算子白名单自检通过 ✓")

    # ---------------- 3. onnxsim ----------------
    onnx_use = onnx_raw
    if not a.skip_sim:
        try:
            import onnxsim
            print("[3] onnxsim 化简 ...")
            ms, ok = onnxsim.simplify(onnx.load(str(onnx_raw)))
            if ok:
                onnx_use = out / "student_sim.onnx"
                onnx.save(ms, str(onnx_use))
                print(f"    简化后 -> {onnx_use}"
                      f"（{onnx_raw.stat().st_size/1e6:.1f}MB -> {onnx_use.stat().st_size/1e6:.1f}MB）")
            else:
                print("    化简失败，继续用原始 ONNX")
        except ImportError:
            print("[3] 没装 onnxsim，跳过（pip install onnxsim）")
    else:
        print("[3] 跳过 onnxsim")

    # ---------------- 4. ORT 数值对齐 ----------------
    print("[4] ONNX Runtime 数值对齐 ...")
    import onnxruntime as ort

    sess = ort.InferenceSession(str(onnx_use), providers=["CPUExecutionProvider"])
    rng = np.random.RandomState(0)
    worst = 0.0
    for t in range(3):
        x = (rng.rand(1, 3, H, W) * 255).astype(np.float32)
        with torch.no_grad():
            ref = wrap(torch.from_numpy(x)).numpy()
        got = sess.run(None, {"input": x})[0]
        d = float(np.abs(ref - got).max())
        worst = max(worst, d)
        print(f"    第 {t+1} 次：max|Δ| = {d:.3e}   (输出值域 {got.min():.1f} ~ {got.max():.1f})")

    # 也用真实图对一次
    inp_dir = Path(a.pairs) / "input"
    names = sorted(p for p in inp_dir.glob("*.png"))[:3]
    for p in names:
        bgr = _imread(p)
        if bgr is None:
            continue
        bgr = cv2.resize(bgr, (W, H), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32)
        rgb = np.ascontiguousarray(rgb.transpose(2, 0, 1)[None])   # NHWC -> NCHW
        with torch.no_grad():
            ref = wrap(torch.from_numpy(rgb)).numpy()
        got = sess.run(None, {"input": rgb})[0]
        d = float(np.abs(ref - got).max())
        worst = max(worst, d)
        print(f"    {p.name}: max|Δ| = {d:.3e}")

    rel = worst / 255.0
    print(f"\n    最大绝对误差 {worst:.3e}（相对满量程 {rel:.2e}）")
    if worst > a.atol:
        print(f"    !! 超过阈值 {a.atol}。误差 >1e-3 就不要往下走，先查模型/导出。")
        sys.exit(4)
    print("    数值对齐通过 ✓")

    # ---------------- 5. 校准集 ----------------
    print(f"[5] 抽校准集（{a.calib} 张，用真实推理分布 = input/ 的裁剪图）")
    all_names = sorted(p for p in inp_dir.glob("*.png"))
    if not all_names:
        print("    !! 找不到 input/*.png")
        sys.exit(5)
    idx = np.linspace(0, len(all_names) - 1, min(a.calib, len(all_names))).astype(int)
    arrs = []
    for i in idx:
        bgr = _imread(all_names[i])
        if bgr is None:
            continue
        arrs.append(cv2.cvtColor(cv2.resize(bgr, (W, H), interpolation=cv2.INTER_AREA),
                                 cv2.COLOR_BGR2RGB))
    calib = np.stack(arrs).astype(np.uint8)          # (N,H,W,3) NHWC
    np.save(out / "calib.npy", calib)
    print(f"    {calib.shape} uint8 -> {out/'calib.npy'}  ({calib.nbytes/1e6:.0f} MB)")

    # ---------------- 汇总 ----------------
    print("\n" + "=" * 68)
    print(f"[done] 产物在 {out.resolve()}")
    print(f"  {onnx_use.name}     <- 送到 WSL 编译")
    print(f"  calib.npy          <- PTQ 校准集")
    print("\n下一步 —— 在 WSL Ubuntu 里跑（compile_kmodel.py 放 C:\\chatbox_temp\\ 下）：")
    print("  ~/nn313/bin/python /mnt/c/chatbox_temp/compile_kmodel.py \\")
    print(f"      --onnx  {to_wsl(onnx_use)} \\")
    print(f"      --calib {to_wsl(out / 'calib.npy')} \\")
    print(f"      --out   {to_wsl(out / 'style.kmodel')} --hw {H} {W}")
    print("\n  （环境变量脚本会自己设；想手动加也行："
          " export DOTNET_ROLL_FORWARD=LatestMajor）")


def to_wsl(p: Path) -> str:
    """Windows 路径 -> WSL 路径： C:\\a\\b -> /mnt/c/a/b"""
    s = str(Path(p).resolve()).replace("\\", "/")
    return "/mnt/" + s[0].lower() + s[2:] if len(s) > 1 and s[1] == ":" else s


if __name__ == "__main__":
    main()
