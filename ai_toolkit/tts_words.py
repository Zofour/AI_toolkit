# -*- coding: utf-8 -*-
"""tts_words.py —— 批量生成英文单词/短语读音（Edge 神经网络 TTS），出一条连读音频 + 分条 MP3 + zip。

依赖：python -m pip install edge-tts ；ffmpeg 在 PATH（C:\\ProgramData\\chocolatey\\bin\\ffmpeg.exe）

用法（最常用）：把词表存成 txt，一行一个，行内可以带词性和中文，脚本自动只取英文部分：
    python C:\\chatbox_temp\\ai_toolkit\\tts_words.py 词表.txt
    python C:\\chatbox_temp\\ai_toolkit\\tts_words.py 词表.txt --voice en-GB-SoniaNeural --repeat 2 --out D:\\audio\\u3

直接给词也行：
    python tts_words.py rebuild enrol poverty "on horseback"

其它：
    --voice en-US-JennyNeural   音色（默认）；--voices 列出可用英文音色
    --rate -10%                 语速（默认 -10%，正数是加快）
    --gap 0.9                   连读音频里每项之间的静音秒数
    --repeat 2                  每个词读 2 遍（跟读用，默认 1）
    --out DIR                   输出目录（默认 .\\tts_out）
    --name 封面名                连读音频文件名（默认 读音_连读.mp3）
    --no-zip                    不打包分条 zip
    --selftest                  自检（3 个词，输出到 %TEMP%\\tts_words_selftest）
"""
import argparse, asyncio, os, re, shutil, subprocess, sys, zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]")
POS = re.compile(r"^(?:v|n|a|ad|adj|adv|prep|conj|pron|vt|vi|num|int)\.$", re.I)


def clean_line(s: str) -> str:
    """'malnutrition  n. 营养不良' -> 'malnutrition'；纯英文短语/带连字符的原样保留。"""
    s = s.replace("\ufeff", "").strip().strip("\u3000")
    if not s or s.startswith("#") or s.startswith("//"):
        return ""
    s = CJK.split(s)[0]
    parts = re.split(r"\t+|\s{2,}|\s+(?=(?:v|n|a|ad|adj|adv|prep|conj|pron|vt|vi|num|int)\.)", s)
    s = parts[0].strip()
    s = re.sub(r"\s+", " ", s).strip(" \t,;:：.、-")
    if s and POS.match(s.split()[-1]):
        s = " ".join(s.split()[:-1])
    return s.strip()


def read_words(args):
    words = []
    if args.file:
        with open(args.file, "r", encoding=args.encoding, errors="replace") as f:
            for line in f:
                w = clean_line(line)
                if w:
                    words.append(w)
    words += [w.strip() for w in (args.words or []) if w.strip()]
    if not words:
        sys.exit("没有读到任何词：检查 --file 或直接给单词")
    return words


def slug(w, i):
    s = re.sub(r"[^0-9A-Za-z]+", "_", w).strip("_").lower() or "item"
    return f"{i:02d}_{s}.mp3"


async def synth(jobs, voice, rate):
    import edge_tts
    sem = asyncio.Semaphore(2)  # 并发别太高，edge 会限流

    async def one(i, text, path):
        async with sem:
            for _ in range(3):
                try:
                    await edge_tts.Communicate(text, voice, rate=rate).save(path)
                    if os.path.getsize(path) > 500:
                        return
                except Exception as e:
                    print("  重试:", text, e)
                    await asyncio.sleep(1.5)
            raise RuntimeError("合成失败: " + text)

    await asyncio.gather(*[one(i, t, p) for i, t, p in jobs])


def run(args):
    words = read_words(args)
    voice = args.voice
    out = os.path.abspath(args.out or "tts_out")
    raw = os.path.join(out, "_raw")
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(raw, exist_ok=True)
    print(f"共 {len(words)} 条 → 音色 {voice}，语速 {args.rate}，每词 {args.repeat} 遍，输出 {out}")

    plan = []
    for i, w in enumerate(words, 1):
        base = slug(w, i)
        for r in range(1, max(1, args.repeat) + 1):
            p = os.path.join(raw, base if r == 1 else base.replace(".mp3", f"_{r}.mp3"))
            plan.append((p, w))
    jobs = [(k, w, p) for k, (p, w) in enumerate(plan)]

    asyncio.run(synth(jobs, voice, args.rate))

    # 统一格式（24k 单声道）+ 排序
    def keyf(p):
        m = re.match(r"(\d+)_", os.path.basename(p))
        m2 = re.search(r"_(\d+)\.mp3$", os.path.basename(p))
        return (int(m.group(1)) if m else 0, int(m2.group(1)) if m2 else 1)

    norm = []
    for p in sorted([x[0] for x in plan], key=keyf):
        o = os.path.join(out, os.path.basename(p))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", p, "-ac", "1", "-ar", "24000",
                        "-b:a", "64k", o], check=True)
        norm.append(o)

    gap = float(args.gap)
    sil = os.path.join(raw, "_gap.mp3")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=24000:cl=mono", "-t", str(gap), "-b:a", "64k", sil], check=True)

    lst = os.path.join(raw, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for i, p in enumerate(norm):
            f.write("file '%s'\n" % p.replace("\\", "/"))
            if i != len(norm) - 1:
                f.write("file '%s'\n" % sil.replace("\\", "/"))

    final = os.path.join(out, args.name)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-b:a", "64k", final], check=True)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", final],
                         capture_output=True, text=True).stdout.strip()

    zpath = None
    if not args.no_zip:
        zpath = os.path.join(out, os.path.splitext(args.name)[0] + "_单条.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for p in norm:
                z.write(p, os.path.basename(p))

    print(f"连读音频: {final}  ({float(dur):.1f}s)")
    print(f"分条文件: {len(norm)} 个（目录 {out}）")
    if zpath:
        print("打包 zip:", zpath)
    print("词序校验:", " / ".join(words[:3]) + (" ... " + words[-1] if len(words) > 3 else ""))


def main():
    ap = argparse.ArgumentParser(add_help=True, description="英文词表 → 读音音频（Edge TTS）")
    ap.add_argument("words", nargs="*", help="直接给单词/短语（也可用 --file）")
    ap.add_argument("--file", help="词表 txt，一行一个；行内带词性/中文会自动只取英文")
    ap.add_argument("--encoding", default="utf-8", help="词表编码，默认 utf-8（GBK 就写 gbk）")
    ap.add_argument("--voice", default="en-US-JennyNeural", help="音色，默认 en-US-JennyNeural")
    ap.add_argument("--rate", default="-10%", help="语速，默认 -10%")
    ap.add_argument("--gap", default="0.9", help="连读时每项间静音秒数，默认 0.9")
    ap.add_argument("--repeat", type=int, default=1, help="每词读几遍，默认 1（跟读可设 2）")
    ap.add_argument("--out", help="输出目录，默认 .\\tts_out")
    ap.add_argument("--name", default="读音_连读.mp3", help="连读音频文件名")
    ap.add_argument("--no-zip", action="store_true", help="不打包分条 zip")
    ap.add_argument("--voices", action="store_true", help="列出可用英文音色后退出")
    ap.add_argument("--selftest", action="store_true", help="自检 3 个词")
    args = ap.parse_args()

    # 便利：直接 python tts_words.py 词表.txt 也当 --file 处理
    if not args.file and len(args.words) == 1 and args.words[0].lower().endswith(
            (".txt", ".csv", ".md")) and os.path.isfile(args.words[0]):
        args.file, args.words = args.words[0], []

    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except Exception:
        sys.exit("找不到 ffmpeg（需在 PATH 里）")

    if args.voices:
        import asyncio, edge_tts
        for v in asyncio.run(edge_tts.list_voices()):
            if v["Locale"].startswith("en-"):
                print(v["ShortName"], v["Gender"], v["Locale"])
        return

    if args.selftest:
        args.words = ["accommodate", "malnourished", "per se"]
        args.file = None
        args.out = os.path.join(os.environ.get("TEMP", "."), "tts_words_selftest")
        args.no_zip = False
    run(args)


if __name__ == "__main__":
    main()
