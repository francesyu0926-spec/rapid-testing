# -*- coding: utf-8 -*-
"""把中文 Markdown 报告渲染成 PDF（reportlab + STSong-Light CID 字体，无需外部依赖）。

支持：# ## ### 标题、| 表格 |、- 列表、1. 有序、> 引用、``` 代码块、--- 分隔线、**加粗**。

用法：
  python md_to_pdf.py 快检AI缺陷测试报告.md
  python md_to_pdf.py 输入.md --out 输出.pdf
"""
import argparse
import functools
import html
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
CN = "STSong-Light"
_ss = getSampleStyleSheet()

H1 = ParagraphStyle("H1", parent=_ss["Title"], fontName=CN, fontSize=20, leading=28,
                    spaceAfter=14, textColor=colors.HexColor("#1a2b4a"))
H2 = ParagraphStyle("H2", parent=_ss["Heading2"], fontName=CN, fontSize=15, leading=22,
                    spaceBefore=14, spaceAfter=8, textColor=colors.HexColor("#23457a"))
H3 = ParagraphStyle("H3", parent=_ss["Heading3"], fontName=CN, fontSize=12.5, leading=18,
                    spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#2f5fa0"))
BODY = ParagraphStyle("Body", parent=_ss["BodyText"], fontName=CN, fontSize=10.5,
                      leading=17, alignment=TA_LEFT)
QUOTE = ParagraphStyle("Quote", parent=BODY, leftIndent=12, textColor=colors.HexColor("#555"),
                       backColor=colors.HexColor("#f2f5fb"), borderPadding=6, spaceBefore=4,
                       spaceAfter=6)
LIST = ParagraphStyle("List", parent=BODY, leftIndent=16, bulletIndent=4)
CODE = ParagraphStyle("Code", parent=BODY, fontName="Courier", fontSize=9, leading=12,
                      backColor=colors.HexColor("#f4f4f4"), borderPadding=6,
                      textColor=colors.HexColor("#222"))
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=8.6, leading=12)
CELLH = ParagraphStyle("CellH", parent=CELL, textColor=colors.white)

USABLE = A4[0] - 3 * cm  # 左右各 1.5cm


def inline(t):
    """转义 + 处理 **加粗** 与 `代码`。"""
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`]+)`", r"<font face='Courier'>\1</font>", t)
    return t


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def is_sep_row(line):
    return bool(re.match(r"^\|?[\s:-]+\|[\s:|-]*$", line.strip())) and "-" in line


def make_table(rows):
    header = rows[0]
    body = rows[1:]
    ncol = max(len(r) for r in rows)
    col_w = USABLE / ncol
    data = []
    data.append([Paragraph(inline(c), CELLH) for c in header] +
                [Paragraph("", CELLH)] * (ncol - len(header)))
    for r in body:
        data.append([Paragraph(inline(c), CELL) for c in r] +
                    [Paragraph("", CELL)] * (ncol - len(r)))
    t = Table(data, colWidths=[col_w] * ncol, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#23457a")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b9c4d6")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#eef2f9")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def parse(md):
    lines = md.splitlines()
    flow = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        s = ln.strip()
        if not s:
            flow.append(Spacer(1, 5)); i += 1; continue
        # 代码块
        if s.startswith("```"):
            buf = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1
            txt = html.escape("\n".join(buf)).replace("\n", "<br/>").replace(" ", "&nbsp;")
            flow.append(Paragraph(txt, CODE)); flow.append(Spacer(1, 6)); continue
        # 表格
        if s.startswith("|"):
            tbl = [split_row(lines[i])]; i += 1
            if i < n and is_sep_row(lines[i]):
                i += 1
            while i < n and lines[i].strip().startswith("|"):
                tbl.append(split_row(lines[i])); i += 1
            flow.append(make_table(tbl)); flow.append(Spacer(1, 8)); continue
        # 标题
        if s.startswith("### "):
            flow.append(Paragraph(inline(s[4:]), H3)); i += 1; continue
        if s.startswith("## "):
            flow.append(Paragraph(inline(s[3:]), H2)); i += 1; continue
        if s.startswith("# "):
            flow.append(Paragraph(inline(s[2:]), H1)); i += 1; continue
        # 分隔线
        if re.match(r"^-{3,}$", s):
            flow.append(HRFlowable(width="100%", thickness=0.6,
                                   color=colors.HexColor("#b9c4d6"),
                                   spaceBefore=6, spaceAfter=6)); i += 1; continue
        # 引用
        if s.startswith(">"):
            flow.append(Paragraph(inline(s.lstrip("> ").strip()), QUOTE)); i += 1; continue
        # 列表
        m = re.match(r"^(\d+)\.\s+(.*)", s)
        if s.startswith("- ") or s.startswith("* "):
            flow.append(Paragraph("• " + inline(s[2:]), LIST)); i += 1; continue
        if m:
            flow.append(Paragraph(f"{m.group(1)}. " + inline(m.group(2)), LIST))
            i += 1; continue
        # 普通段落
        flow.append(Paragraph(inline(s), BODY)); i += 1
    return flow


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("md")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    out = args.out or re.sub(r"\.md$", ".pdf", args.md)
    md = open(args.md, encoding="utf-8").read()
    doc = SimpleDocTemplate(out, pagesize=A4, topMargin=1.6 * cm,
                            bottomMargin=1.6 * cm, leftMargin=1.5 * cm,
                            rightMargin=1.5 * cm, title="快检AI缺陷测试报告")
    doc.build(parse(md))
    print(f"已导出 PDF: {out}")


if __name__ == "__main__":
    main()
