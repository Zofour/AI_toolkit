# -*- coding: utf-8 -*-
"""命令行翻译：把英文（或文件/标准输入）翻成中文。便于先单独验证本地翻译模型。
用法：
  python cli.py "Some English text"
  echo "text" | python cli.py
  python cli.py --file in.txt -o out.txt
"""
import sys, io, os, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from translator import Translator

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help="要翻译的英文；缺省则读 stdin 或 --file")
    ap.add_argument("--file")
    ap.add_argument("-o", "--out")
    ap.add_argument("--model", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "models", "Qwen2.5-1.5B-Instruct"))
    ap.add_argument("--cpu", action="store_true")
    args = ap.parse_args()

    if args.file:
        src = open(args.file, encoding="utf-8").read()
    elif args.text:
        src = args.text
    else:
        src = sys.stdin.read()

    tr = Translator(args.model, device="cpu" if args.cpu else "cuda")
    res = tr.translate(src)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(res)
        print("written ->", args.out)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(res)

if __name__ == "__main__":
    main()
