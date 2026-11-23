#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""bili_interp.py —— B站/本地视频 AI 插帧（RIFE ncnn-vulkan），可补到 60/120/240fps

用法示例:
  python bili_interp.py "https://www.bilibili.com/video/BVxxxxxxxx" --fps 240
  python bili_interp.py "D:/video/a.mp4" --fps 120 --anime
  python bili_interp.py "URL" --fps 240 --cookies edge --limit 60    # 只处理前 60 秒试水

要点:
  * 分块处理（默认每块 10 秒），磁盘占用只跟块大小有关，不会炸
  * 编码走 NVENC (hevc/h264)，40 系/50 系几秒钟一条
  * 音频直接从源视频 copy 回来
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TOOL_ROOT = Path(__file__).resolve().parent
RIFE_EXE = TOOL_ROOT / "bin" / "rife-ncnn-vulkan-20221029-windows" / "rife-ncnn-vulkan.exe"
RIFE_MODELS = RIFE_EXE.parent

MODEL_ALIAS = {
    "auto": "rife-v4.6",
    "anime": "rife-anime",
    "hd": "rife-HD",
    "uhd": "rife-UHD",
    "v46": "rife-v4.6",
    "v31": "rife-v3.1",
}


def log(msg):
    print(msg, flush=True)


def find_ffmpeg(name):
    p = shutil.which(name)
    if p:
        return p
    cand = Path(r"C:\ProgramData\chocolatey\bin") / (name + ".exe")
    if cand.exists():
        return str(cand)
    raise SystemExit(f"找不到 {name}，请确认 ffmpeg 在 PATH 里")


FFMPEG = find_ffmpeg("ffmpeg")
FFPROBE = find_ffmpeg("ffprobe")


def run(cmd, cwd=None, quiet=True):
    if not quiet:
        log("  $ " + " ".join(str(c) for c in cmd))
    if quiet:
        r = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            log("[FAIL] " + " ".join(str(c) for c in cmd))
            log((r.stdout or "")[-1500:])
            log((r.stderr or "")[-3000:])
            raise SystemExit(1)
        return r
    subprocess.run([str(c) for c in cmd], cwd=cwd, check=True)
    return None


def detect_gpu():
    """自动挑独显：枚举 Vulkan 设备，跳过 Intel 核显。结果缓存到 bin/rife_gpu.json"""
    cache = TOOL_ROOT / "bin" / "rife_gpu.json"
    if cache.exists():
        try:
            d = json.loads(cache.read_text(encoding="utf-8"))
            if d.get("devices"):
                return int(d["id"]), d.get("name", "")
        except Exception:
            pass
    probe = TOOL_ROOT / "bin" / "_gpu_probe"
    shutil.rmtree(probe, ignore_errors=True)
    (probe / "in").mkdir(parents=True, exist_ok=True)
    (probe / "out").mkdir(parents=True, exist_ok=True)
    tiny = TOOL_ROOT / "bin" / "_tiny.png"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=32x32:d=0.1",
                    "-frames:v", "2", str(tiny)], capture_output=True)
    for i in (1, 2):
        shutil.copy(tiny, probe / "in" / f"{i:08d}.png")
    # 必须带 -m 全路径并在 RIFE 目录下跑，否则它在枚举显卡前就退出了
    r = subprocess.run([str(RIFE_EXE), "-i", str(probe / "in"), "-o", str(probe / "out"),
                        "-m", str(RIFE_MODELS / "rife-v4.6"), "-g", "0", "-n", "4"],
                       cwd=str(RIFE_EXE.parent), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    devs = {}
    for line in ((r.stderr or "") + "\n" + (r.stdout or "")).splitlines():
        m = re.match(r"^\[(\d+)\s+([^\]]+)\]", line.strip())
        if m:
            devs.setdefault(int(m.group(1)), m.group(2).strip())
    pick, name = None, ""
    for idx in sorted(devs):
        nm = devs[idx]
        if re.search(r"nvidia|geforce|rtx|radeon|amd|arc", nm, re.I):
            pick, name = idx, nm
            break
    if pick is None:
        for idx in sorted(devs):
            if not re.search(r"intel", devs[idx], re.I):
                pick, name = idx, devs[idx]
                break
    if pick is None and devs:
        pick, name = min(devs), devs[min(devs)]
    if pick is None:
        pick, name = 0, "unknown"
    shutil.rmtree(probe, ignore_errors=True)
    tiny.unlink(missing_ok=True)
    try:
        cache.write_text(json.dumps({"id": pick, "name": name, "devices": devs}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return pick, name


def media_info(path):
    r = run([FFPROBE, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)])
    data = json.loads(r.stdout)
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    if v is None:
        raise SystemExit("源文件里没有视频流")
    num, den = (v.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den or 1)
    dur = float(data["format"].get("duration") or v.get("duration") or 0)
    return {
        "width": int(v["width"]),
        "height": int(v["height"]),
        "fps": round(fps, 4),
        "duration": dur,
        "has_audio": a is not None,
    }


def download(url, workdir, cookies, cookies_file=""):
    log("[1/5] 下载源视频 ...")
    out_tpl = str(workdir / "%(title).70s.%(ext)s")
    cmd = [sys.executable, "-m", "yt_dlp",
           "-f", "bv*[height<=2160]+ba/bv*+ba/b",
           "--merge-output-format", "mp4",
           "--no-playlist", "--newline",
           "-o", out_tpl]
    if cookies_file:
        cmd += ["--cookies", cookies_file]
    elif cookies:
        cmd += ["--cookies-from-browser", cookies]
    cmd.append(url)
    try:
        run(cmd, quiet=False)
    except (SystemExit, subprocess.CalledProcessError):
        raise SystemExit(
            "\n[下载失败] 需要登录态，但没拿到可用 Cookie。常见原因：\n"
            "  1) 新版 Edge/Chrome 启用了 App-Bound 加密（报 Failed to decrypt with DPAPI）\n"
            "     → yt-dlp 现在读不了浏览器 Cookie，必须用 SESSDATA 或 cookies.txt\n"
            "  2) 浏览器开着锁住了 Cookie 库（报 Could not copy）\n"
            "  3) SESSDATA 已失效/不完整（过期、或复制时带了多余字符/空格）\n"
            "\n  办法 A（最简单）：加 --sessdata \"<你的SESSDATA>\"\n"
            "     SESSDATA 怎么拿：Edge 打开 bilibili.com 并登录 → F12 → Application/应用 →\n"
            "     Cookies → https://www.bilibili.com → 找 SESSDATA，复制它的 Value\n"
            "  办法 B：用扩展 Get cookies.txt LOCALLY 导出 → --cookies-file \"D:\\cookies.txt\"\n")
    cands = sorted([p for p in workdir.glob("*.mp4")], key=lambda p: p.stat().st_size, reverse=True)
    if not cands:
        cands = sorted([p for p in workdir.iterdir() if p.suffix.lower() in (".mp4", ".mkv", ".flv", ".webm")],
                       key=lambda p: p.stat().st_size, reverse=True)
    if not cands:
        raise SystemExit("下载完成但找不到视频文件")
    return cands[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default="", help="B站链接 或 本地视频路径（不填则交互提问）")
    ap.add_argument("--fps", type=float, default=None, help="目标帧率（默认 240）")
    ap.add_argument("--mult", type=int, default=0, help="直接指定倍数（覆盖 --fps）")
    ap.add_argument("--model", default="auto", help="auto/anime/hd/uhd/v46/v31")
    ap.add_argument("--anime", action="store_true", help="等同 --model anime")
    ap.add_argument("--chunk", type=float, default=15.0, help="每块秒数（默认 15）")
    ap.add_argument("--limit", type=float, default=0, help="只处理前 N 秒（0=全片）")
    ap.add_argument("--cookies", default="", help="从浏览器取 Cookie：edge/chrome/firefox（大会员画质必需）")
    ap.add_argument("--cookies-file", default="", help="Netscape 格式 cookies.txt（浏览器登录态读不出来时用）")
    ap.add_argument("--sessdata", default="", help="B站 SESSDATA（F12 里复制，替代浏览器读 Cookie，最省事）")
    ap.add_argument("--out-dir", default="", help="输出目录（默认 D:\\video_interp）")
    ap.add_argument("--bitrate", default="", help="输出码率，如 40M（默认按分辨率/帧率自动）")
    ap.add_argument("--codec", default="hevc", choices=["hevc", "h264"])
    ap.add_argument("--gpu", default="auto", help="Vulkan 设备号（auto=自动选独显）")
    ap.add_argument("--threads", default="2:4:4", help="RIFE load:proc:save 线程（默认 2:4:4）")
    ap.add_argument("--tta", action="store_true", help="开启 TTA，质量更高、速度减半")
    ap.add_argument("--fast", action="store_true", help="中间帧用 jpg（省磁盘、稍快，画质差别很小）")
    ap.add_argument("--width", type=int, default=0, help="输出宽度（在抽帧阶段就缩，RIFE 也变便宜）")
    ap.add_argument("--height", type=int, default=0, help="输出高度（如 1080）")
    ap.add_argument("--keep", action="store_true", help="保留中间文件")
    args = ap.parse_args()

    # 交互模式（双击 bat 时进来）：只在该问的时候问，管道/脚本调用不会卡住
    tty = sys.stdin.isatty()
    if not args.src and tty:
        args.src = input("请粘贴 B 站视频链接，或把视频文件拖到这里后回车: ").strip().strip('"')
    if not args.src:
        raise SystemExit("没有提供视频来源")
    if args.fps is None:
        args.fps = 240.0
        if tty:
            s = input("目标帧率（直接回车=240，可填 60/120/240）: ").strip()
            if s:
                try:
                    args.fps = float(s)
                except ValueError:
                    log(f"[!] 请输入数字，已用默认 240")
    if not args.cookies and tty and args.src.lower().startswith(("http://", "https://")):
        s = input("需要 1080P高码率/4K/大会员画质吗？（需登录）y/N: ").strip().lower()
        if s == "y":
            v = input("  粘贴 SESSDATA（F12→应用→Cookie→bilibili.com→SESSDATA；\n  直接回车 = 尝试读 Edge 登录态，新版 Edge 多半会失败）: ").strip()
            if v:
                args.sessdata = v
                try:
                    (TOOL_ROOT / "bili_sessdata.txt").write_text(v, encoding="utf-8")
                    log("[i] SESSDATA 已保存，下次不用再填（删 ai_toolkit\\bili_sessdata.txt 即可撤销）")
                except Exception:
                    pass
            else:
                args.cookies = "edge"

    if not RIFE_EXE.exists():
        raise SystemExit(f"RIFE 未安装：{RIFE_EXE}")

    model = "rife-anime" if args.anime else MODEL_ALIAS.get(args.model, args.model)
    if not (RIFE_MODELS / model).exists():
        raise SystemExit(f"模型不存在：{model}，可用：{', '.join(p.name for p in RIFE_MODELS.iterdir() if p.is_dir())}")

    src_arg = args.src
    out_dir = Path(args.out_dir) if args.out_dir else Path("D:/video_interp")
    out_dir.mkdir(parents=True, exist_ok=True)

    tmp = out_dir / ("_work_" + time.strftime("%Y%m%d_%H%M%S"))
    tmp.mkdir(parents=True, exist_ok=True)

    # SESSDATA 可复用：环境变量 BILI_SESSDATA 或 ai_toolkit\bili_sessdata.txt
    if not args.sessdata:
        env_sd = os.environ.get("BILI_SESSDATA", "").strip()
        sd_file = TOOL_ROOT / "bili_sessdata.txt"
        if env_sd:
            args.sessdata = env_sd
        elif sd_file.exists():
            try:
                args.sessdata = sd_file.read_text(encoding="utf-8-sig").strip().strip('"')
                if args.sessdata:
                    log(f"[i] 已自动读取保存的 SESSDATA：{sd_file.name}")
            except Exception:
                pass

    if not args.cookies_file and args.sessdata:
        args.cookies_file = str(tmp / "cookies.txt")
        exp = int(time.time()) + 30 * 86400
        lines = ["# Netscape HTTP Cookie File", ""]
        lines.append(f".bilibili.com\tTRUE\t/\tFALSE\t{exp}\tSESSDATA\t{args.sessdata.strip()}")
        Path(args.cookies_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
        log("[i] 已用 SESSDATA 生成 cookies.txt")

    if src_arg.lower().startswith(("http://", "https://")):
        src = download(src_arg, tmp, args.cookies, args.cookies_file)
    else:
        src = Path(src_arg)
        if not src.exists():
            raise SystemExit(f"文件不存在：{src}")

    info = media_info(src)
    src_fps = info["fps"]
    mult = args.mult if args.mult > 0 else max(1, round(args.fps / src_fps))
    target_fps = src_fps * mult
    if args.mult <= 0 and abs(target_fps - args.fps) > 0.6:
        log(f"[!] 源 {src_fps:.3f}fps × {mult} = {target_fps:.2f}fps（{mult} 倍整数插帧，无法精确 {args.fps}）")

    duration = info["duration"]
    if args.limit and args.limit < duration:
        duration = args.limit

    # 输出分辨率（抽帧时就缩，RIFE 处理量同比例下降）
    out_w, out_h = info["width"], info["height"]
    scale_vf = None
    if args.width > 0 and args.height > 0:
        scale_vf = f"scale={args.width}:{args.height}"
        out_w, out_h = args.width, args.height
    elif args.height > 0:
        scale_vf = f"scale=-2:{args.height}"
        out_h = args.height
        out_w = int(round(info["width"] * args.height / info["height"] / 2) * 2)
    elif args.width > 0:
        scale_vf = f"scale={args.width}:-2"
        out_w = args.width
        out_h = int(round(info["height"] * args.width / info["width"] / 2) * 2)

    log(f"[2/5] 源: {src.name}")
    log(f"      {info['width']}x{info['height']} @ {src_fps:.3f}fps, {duration:.1f}s  →  目标 {target_fps:.2f}fps ({mult}x), 模型 {model}")
    if scale_vf:
        log(f"      输出缩放 → {out_w}x{out_h}（RIFE 也按此尺寸跑，速度提升明显）")

    if args.bitrate:
        br = args.bitrate
    else:
        mbps = max(6.0, out_w * out_h * target_fps * 0.12 / 1e6)
        br = f"{mbps:.0f}M"
        if mbps > 100:
            br = "100M"
    enc = "hevc_nvenc" if args.codec == "hevc" else "h264_nvenc"
    log(f"      编码 {enc} {br} / 块 {args.chunk:g}s")

    if args.gpu == "auto":
        gpu_id, gpu_name = detect_gpu()
    else:
        gpu_id, gpu_name = int(args.gpu), f"手动指定 {args.gpu}"
    log(f"      RIFE 设备: [{gpu_id}] {gpu_name}")
    tta = ["-x"] if args.tta else []

    uhd = ["-u"] if out_h > 1200 and "UHD" not in model else []
    ext = "jpg" if args.fast else "png"
    qflag = ["-q:v", "2"] if args.fast else []
    chunks = []
    n_chunks = max(1, int((duration + args.chunk - 1) // args.chunk))
    t_all = time.time()
    done_sec = 0.0
    idx = 0
    while done_sec < duration - 0.03:
        seg = min(args.chunk, duration - done_sec)
        idx += 1
        t0 = time.time()
        in_dir = tmp / f"in_{idx:03d}"
        out_fr = tmp / f"out_{idx:03d}"
        in_dir.mkdir(parents=True, exist_ok=True)
        out_fr.mkdir(parents=True, exist_ok=True)

        run([FFMPEG, "-v", "error", "-ss", f"{done_sec:.3f}", "-t", f"{seg:.3f}", "-i", str(src),
             "-fps_mode", "passthrough"] + (["-vf", scale_vf] if scale_vf else []) + qflag + [str(in_dir / f"%08d.{ext}")])
        n_in = len(list(in_dir.glob(f"*.{ext}")))
        if n_in < 2:
            shutil.rmtree(in_dir, ignore_errors=True)
            shutil.rmtree(out_fr, ignore_errors=True)
            done_sec += seg
            continue

        # 注意：rife-ncnn-vulkan 的 -n 是【总输出帧数】，不是倍数
        n_target = max(mult, int(round(n_in * mult)))
        run([str(RIFE_EXE), "-i", str(in_dir), "-o", str(out_fr), "-m", str(RIFE_MODELS / model),
             "-n", str(n_target), "-g", str(gpu_id), "-j", args.threads,
             "-f", f"%08d.{ext}"] + uhd + tta)
        n_out = len(list(out_fr.glob(f"*.{ext}")))

        chunk_mp4 = tmp / f"chunk_{idx:03d}.mp4"
        # 目标帧率不是源帧率整数倍时（如 25→120），先按整数倍生成再用 -r 精确落到目标帧率
        exact = ["-r", f"{args.fps:.6f}"] if (args.mult <= 0 and abs(target_fps - args.fps) > 0.5) else []
        run([FFMPEG, "-v", "error", "-framerate", f"{target_fps:.6f}", "-i", str(out_fr / f"%08d.{ext}"),
             ] + exact + ["-c:v", enc, "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-b:v", br,
             "-maxrate", br, "-bufsize", br, "-pix_fmt", "yuv420p", "-g", "120", str(chunk_mp4)])
        chunks.append(chunk_mp4)
        if not args.keep:
            shutil.rmtree(in_dir, ignore_errors=True)
            shutil.rmtree(out_fr, ignore_errors=True)
        spd = n_in / max(0.001, time.time() - t0)
        log(f"      块 {idx}/{n_chunks}: {seg:.1f}s  {n_in} → {n_out} 帧  ({spd:.0f} 输入帧/秒)")
        done_sec += seg

    if not chunks:
        raise SystemExit("没有生成任何分块，检查源文件")

    log("[3/5] 合并分块 ...")
    lst = tmp / "list.txt"
    with open(lst, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write("file '" + str(c).replace("\\", "/") + "'\n")

    out_name = Path(src).stem + f"_{target_fps:.0f}fps_{model}.mp4"
    out_file = out_dir / out_name
    map_audio = ["-map", "1:a:0?"] if info["has_audio"] else []
    run([FFMPEG, "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(src),
         "-map", "0:v:0"] + map_audio + ["-c", "copy", "-shortest", "-movflags", "+faststart", "-y", str(out_file)])

    final = media_info(out_file)
    size_mb = out_file.stat().st_size / 1e6
    log(f"[4/5] 完成: {out_file}")
    log(f"      {final['width']}x{final['height']} @ {final['fps']:.2f}fps, {final['duration']:.1f}s, {size_mb:.0f} MB")
    log(f"[5/5] 耗时 {(time.time()-t_all)/60:.2f} 分钟")
    if not args.keep:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
