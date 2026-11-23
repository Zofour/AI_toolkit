# -*- coding: utf-8 -*-
'''
md2docx.py —— 把 Markdown 转成 Word(.docx)，用于发人 / 打印。

支持：# ## ### 标题、- / 1. 列表、``` 代码块、| 管道表格 |、**粗体**、`行内代码`

用法：
    python md2docx.py in.md                 # 生成同目录同名 .docx
    python md2docx.py in.md -o out.docx     # 指定输出
'''
import argparse
import os
import re
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

EA_FONT = "微软雅黑"
CODE_FONT = "Consolas"


def set_base_font(doc):
    # 正文/标题的拉丁字体与中文字体统一用 EA_FONT（微软雅黑），
    # Consolas 只用于代码块与行内代码，避免中英混排时英文变等宽体。
    st = doc.styles["Normal"]
    st.font.name = EA_FONT
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), EA_FONT)
    for name in ("Title", "Heading 1", "Heading 2", "Heading 3"):
        try:
            s = doc.styles[name]
            s.font.name = EA_FONT
            s.element.rPr.rFonts.set(qn("w:eastAsia"), EA_FONT)
            s.font.color.rgb = RGBColor(0x1F, 0x37, 0x64)
        except Exception:
            pass


def shade(par, color="F2F2F2"):
    pPr = par._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), color)
    pPr.append(shd)


def plain(s):
    """标题里不渲染行内样式，去掉标记即可"""
    return s.replace("**", "").replace("`", "")


def add_runs(par, text):
    """支持 **粗体** 与 `行内代码`"""
    for chunk in re.split(r"(\*\*.+?\*\*|`[^`]+`)", text):
        if not chunk:
            continue
        if chunk.startswith("**") and chunk.endswith("**") and len(chunk) > 4:
            par.add_run(chunk[2:-2]).bold = True
        elif chunk.startswith("`") and chunk.endswith("`") and len(chunk) > 2:
            r = par.add_run(chunk[1:-1])
            r.font.name = CODE_FONT
            r.font.color.rgb = RGBColor(0xA3, 0x15, 0x15)
        else:
            par.add_run(chunk)


def add_code(doc, lines):
    for ln in lines:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.left_indent = Pt(12)
        shade(p)
        r = p.add_run(ln if ln.strip() else " ")
        r.font.name = CODE_FONT
        r.font.size = Pt(9)


def add_table(doc, rows):
    ncol = max(len(r) for r in rows)
    t = doc.add_table(rows=0, cols=ncol)
    t.style = "Table Grid"
    for i, row in enumerate(rows):
        cells = t.add_row().cells
        for j in range(ncol):
            txt = row[j] if j < len(row) else ""
            par = cells[j].paragraphs[0]
            par.paragraph_format.space_after = Pt(0)
            add_runs(par, txt)
            if i == 0:
                for run in par.runs:
                    run.bold = True
    doc.add_paragraph()


def split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def convert(md_path, out_path):
    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    doc = Document()
    set_base_font(doc)

    i = 0
    in_code = False
    code_buf = []
    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            if in_code:
                add_code(doc, code_buf)
                code_buf = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(ln)
            i += 1
            continue

        s = ln.strip()
        if not s:
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lines) and set(lines[i + 1].strip()) <= set("|-: "):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cur = lines[i].strip()
                if not set(cur) <= set("|-: "):
                    rows.append(split_row(cur))
                i += 1
            add_table(doc, rows or [[""]])
            continue
        if s.startswith("### "):
            doc.add_heading(plain(s[4:]), level=3)
        elif s.startswith("## "):
            doc.add_heading(plain(s[3:]), level=2)
        elif s.startswith("# "):
            doc.add_heading(plain(s[2:]), level=1)
        elif s.startswith(("- ", "* ")):
            p = doc.add_paragraph(style="List Bullet")
            add_runs(p, s[2:])
        elif re.match(r"^\d+\.\s", s):
            p = doc.add_paragraph(style="List Number")
            add_runs(p, re.sub(r"^\d+\.\s", "", s))
        elif s.startswith("> "):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Pt(18)
            add_runs(p, s[2:])
            for r in p.runs:
                r.italic = True
        elif set(s) <= set("-—"):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run("—" * 20)
        else:
            p = doc.add_paragraph()
            add_runs(p, s)
        i += 1

    if code_buf:
        add_code(doc, code_buf)
    doc.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser("Markdown -> Word")
    ap.add_argument("md")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()
    out = a.out or os.path.splitext(a.md)[0] + ".docx"
    convert(a.md, out)
    print("OK ->", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
