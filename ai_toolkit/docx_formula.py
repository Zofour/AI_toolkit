# -*- coding: utf-8 -*-
"""LaTeX -> Word 原生可编辑公式(OMML) 流水线：库 + 命令行。

已验证的坑（勿改回去）:
  1) 字号必须写进 m:r/w:rPr/w:sz；写 m:rPr/m:sz 会让 Word 报“需要修复”。
  2) \\vec{X} 被 latex2mathml 转成 m:limUpp(箭头当上标)，必须改写成 m:acc + m:chr=U+20D7。
  3) 传 LaTeX 时用 raw 字符串(r"...")，否则 \\v \\r \\t \\b \\f 会被 Python 转义吃掉。

用法(命令行):
    python docx_formula.py -o out.docx --title "第七章" -e "E=mc^2" -e r"\\vec{F}=m\\vec{a}"
    python docx_formula.py -o out.docx --file eqs.txt      # 每行一条 LaTeX，'#' 开头为注释
    python docx_formula.py --selftest                      # 自检：生成临时 docx 并校验 OMML

用法(库):
    from docx_formula import add_equation, latex_to_omml
    doc = Document(); add_equation(doc, r"\\oint \\vec{B}\\cdot d\\vec{l}=\\mu_0 I", size_pt=12)
"""
import os
import sys

from lxml import etree
import latex2mathml.converter as l2m
from docx import Document

M_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M = '{%s}' % M_NS
W = '{%s}' % W_NS
XSL = r'C:\Program Files\Microsoft Office\root\Office16\MML2OMML.XSL'

_XSLT = None
# latex2mathml 把 \vec/\dot/\tilde/\ddot 等 accent 转成 <mover>（**不带 accent 属性**），
# MML2OMML.XSL 于是把重音符当成上标、转成 m:limUpp。这里把 lim 里的重音符映射成 Word
# m:acc 需要的组合重音符（combining mark），再把 limUpp 改写为 m:acc。
_ACCENT_MAP = {
    '\u2192': '\u20d7',  # \vec  →（U+2192）→ U+20D7 combining right arrow above
    '\u2190': '\u20d6',  # \overleftarrow ← → U+20D6 combining left arrow above
    '\u02d9': '\u0307',  # \dot  ˙（U+02D9）→ U+0307 combining dot above
    '\u007e': '\u0303',  # \tilde ~（U+007E）→ U+0303 combining tilde
    '\u00a8': '\u0308',  # \ddot ¨（U+00A8）→ U+0308 combining diaeresis
    '\u005e': '\u0302',  # \hat ^（U+005E）→ U+0302 combining circumflex（兜底）
    '\u20db': '\u20db',  # \dddot
}


def _xslt():
    global _XSLT
    if _XSLT is None:
        if not os.path.exists(XSL):
            raise FileNotFoundError('未找到 MML2OMML.XSL: %s (需要已安装 Office)' % XSL)
        _XSLT = etree.XSLT(etree.parse(XSL))
    return _XSLT


def _fix_accents(omml):
    r"""\vec/\dot/\tilde/\ddot 等被转成 m:limUpp，改写为 m:acc（Word 里显示为正常重音符）。"""
    for lu in list(omml.iter(M + 'limUpp')):
        lim = lu.find(M + 'lim')
        base = lu.find(M + 'e')
        if lim is None or base is None:
            continue
        txt = ''.join(lim.itertext()).strip()
        if txt not in _ACCENT_MAP:
            continue
        acc = etree.Element(M + 'acc', nsmap={'m': M_NS})
        pr = etree.SubElement(acc, M + 'accPr')
        ch = etree.SubElement(pr, M + 'chr')
        ch.set(M + 'val', _ACCENT_MAP[txt])
        acc.append(base)               # 迁移基元
        parent = lu.getparent()
        if parent is not None:
            parent.replace(lu, acc)


def _set_size(omml, size_pt):
    """把字号写进 m:r/w:rPr/w:sz（半磅）。"""
    half = str(int(round(size_pt * 2)))
    for r in omml.iter(M + 'r'):
        rpr = r.find(W + 'rPr')
        if rpr is None:
            rpr = etree.Element(W + 'rPr', nsmap={'w': W_NS})
            mrpr = r.find(M + 'rPr')
            r.insert(1 if mrpr is not None else 0, rpr)
        for tag in ('sz', 'szCs'):
            el = rpr.find(W + tag)
            if el is None:
                el = etree.SubElement(rpr, W + tag)
            el.set(W + 'val', half)


def latex_to_omml(latex, size_pt=None):
    """LaTeX 字符串 -> lxml 的 m:oMath 元素。"""
    mathml = l2m.convert(latex)
    xml = etree.fromstring(mathml.encode('utf-8') if isinstance(mathml, str) else mathml)
    omml = _xslt()(xml).getroot()
    _fix_accents(omml)
    if size_pt:
        _set_size(omml, size_pt)
    return omml


def add_equation(doc, latex, size_pt=12, center=True):
    """在 doc 末尾追加一条居中显示公式，返回该段落。"""
    p = doc.add_paragraph()
    if center:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p._p.append(latex_to_omml(latex, size_pt=size_pt))
    return p


def build(out_path, title=None, equations=(), size_pt=12):
    doc = Document()
    if title:
        doc.add_heading(title, level=1)
    for tex in equations:
        add_equation(doc, tex, size_pt=size_pt)
    doc.save(out_path)
    return out_path


def _selftest():
    import tempfile
    import zipfile
    eqs = [r'E=mc^2', r'\vec{F}=m\vec{a}', r'\theta=\frac{\pi}{2}',
           r'\oint \vec{B}\cdot d\vec{l}=\mu_0 I',
           r'\dot{x}', r'\tilde{x}', r'\ddot{x}', r'\hat{x}', r'\bar{x}']
    out = os.path.join(tempfile.gettempdir(), 'docx_formula_selftest.docx')
    build(out, '公式自检', eqs)
    doc = Document(out)
    n = sum(1 for p in doc.paragraphs for _ in p._p.iter(M + 'oMath'))
    xml = zipfile.ZipFile(out).read('word/document.xml').decode('utf-8')
    # 所有 accent 都应变成 m:acc，且 vec 的组合箭头必须是 U+20D7（不能是普通箭头 U+2192）
    has_acc = ':acc' in xml or '</m:acc>' in xml
    has_limupp = ':limUpp' in xml or '</m:limUpp>' in xml
    has_vec_comb = '\u20d7' in xml
    has_bad_arrow = 'm:chr m:val="\u2192"' in xml
    has_sz = 'w:sz' in xml
    print('written :', out, os.path.getsize(out), 'bytes')
    print('oMath   :', n, '(expect %d)' % len(eqs))
    print('acc     :', has_acc, '| 残留limUpp:', has_limupp, '(应 False)')
    print('vec组合箭头:', has_vec_comb, '| 错误普通箭头:', has_bad_arrow, '(应 False)')
    print('size sz :', has_sz)
    ok = (n == len(eqs)) and has_acc and (not has_limupp) and has_vec_comb and (not has_bad_arrow)
    return 0 if ok else 1


def main(argv):
    out = None
    title = None
    eqs = []
    size = 12
    i = 1
    while i < len(argv):
        a = argv[i]
        if a in ('-o', '--out'):
            out = argv[i + 1]; i += 2
        elif a == '--title':
            title = argv[i + 1]; i += 2
        elif a in ('-e', '--eq'):
            eqs.append(argv[i + 1]); i += 2
        elif a == '--file':
            with open(argv[i + 1], encoding='utf-8') as f:
                for ln in f:
                    ln = ln.rstrip('\n').strip()
                    if ln and not ln.startswith('#'):
                        eqs.append(ln)
            i += 2
        elif a == '--size':
            size = float(argv[i + 1]); i += 2
        elif a == '--selftest':
            return _selftest()
        else:
            print('unknown arg:', a); return 2
    if not out or not eqs:
        print(__doc__); return 2
    build(out, title, eqs, size_pt=size)
    print('OK ->', out)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
