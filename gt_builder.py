# -*- coding: utf-8 -*-
"""Ground-Truth 数据集渲染原语：中文 PDF 构件、图片化文本、水印、加密、docx/zip。

供 defect_dataset.py 调用。仅依赖 reportlab / Pillow / pypdf / python-docx（均已安装）。
"""
import os
import zipfile

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

WIN_FONTS = r"C:\Windows\Fonts"

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
CN = "STSong-Light"

# 注册雅黑(覆盖繁体/生僻字)；失败则回退 CN
YAHEI = CN
_yh_path = os.path.join(WIN_FONTS, "msyh.ttc")
try:
    if os.path.exists(_yh_path):
        pdfmetrics.registerFont(TTFont("YaHei", _yh_path, subfontIndex=0))
        YAHEI = "YaHei"
except Exception:
    YAHEI = CN

_ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1cn", parent=_ss["Title"], fontName=CN, fontSize=20,
                    leading=28, spaceAfter=18)
H2 = ParagraphStyle("H2cn", parent=_ss["Heading2"], fontName=CN, fontSize=14,
                    leading=20, spaceBefore=10, spaceAfter=8)
BODY = ParagraphStyle("BODYcn", parent=_ss["BodyText"], fontName=CN, fontSize=10.5,
                      leading=18, firstLineIndent=21)
CENTER = ParagraphStyle("CENTERcn", parent=BODY, alignment=1, firstLineIndent=0)
TINY = ParagraphStyle("TINYcn", parent=BODY, fontSize=3.2, leading=4,
                      firstLineIndent=0, textColor=colors.Color(0.45, 0.45, 0.45))
TRAD = ParagraphStyle("TRADcn", parent=BODY, fontName=YAHEI)
INJECT = ParagraphStyle("INJcn", parent=BODY, textColor=colors.Color(0.5, 0.5, 0.5),
                        fontSize=9)


# ------------------------------------------------------------ flowables ---
def heading(text):
    return Paragraph(text, H2)


def para(text, style=BODY):
    return Paragraph(text, style)


def cover(project_name, unit, extra=""):
    out = [Spacer(1, 3 * cm), Paragraph(project_name, H1),
           Paragraph("投　标　文　件", CENTER), Spacer(1, 1 * cm),
           Paragraph(f"投标单位：{unit}", CENTER),
           Paragraph("投标日期：2026 年 06 月", CENTER)]
    if extra:
        out.append(Paragraph(extra, CENTER))
    out.append(PageBreak())
    return out


def grid_table(data, col_widths):
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), CN), ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))
    return t


def two_column(left_text, right_text):
    """双栏排版陷阱：关键信息被拆到左右两栏，跨栏阅读易被模型割裂。"""
    t = Table([[Paragraph(left_text, BODY), Paragraph(right_text, BODY)]],
              colWidths=[8 * cm, 8 * cm])
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), CN),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBEFORE", (1, 0), (1, 0), 0.5, colors.grey)]))
    return t


def filler_pages(n, label="技术方案"):
    """生成约 n 页无关紧要的填充内容(用于'大海捞针'的长文本铺垫)。每页一段+分页。"""
    blob = ("本章节就施工部署、资源配置、进度计划、质量与安全管理等内容进行常规阐述，"
            "相关条款均按行业通行做法编制，无特殊偏离，详见各专项方案。" * 6)
    out = []
    for i in range(n):
        out.append(Paragraph(f"{label} 第 {i+1} 节", H2))
        out.append(Paragraph(blob, BODY))
        out.append(PageBreak())
    return out


def image_text_flowable(png_path, lines, width_cm=15, font_size=26, scanned=False):
    """把文字渲染成 PNG(模拟扫描件/图片化资质)，返回可嵌入 PDF 的 Image。"""
    from PIL import Image as PILImage, ImageDraw, ImageFont
    W, H = 1400, 120 + font_size * 2 * len(lines)
    img = PILImage.new("RGB", (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(_yh_path, font_size, index=0)
    except Exception:
        font = ImageFont.load_default()
    y = 40
    for ln in lines:
        dr.text((50, y), ln, fill=(20, 20, 20), font=font)
        y += font_size * 2
    if scanned:
        # 加噪点+轻微旋转，模拟扫描件
        import random
        for _ in range(int(W * H * 0.01)):
            img.putpixel((random.randint(0, W - 1), random.randint(0, H - 1)),
                         (random.randint(120, 200),) * 3)
        img = img.rotate(0.6, expand=False, fillcolor=(255, 255, 255))
    img.save(png_path, "PNG")
    iw = width_cm * cm
    ih = iw * H / W
    return Image(png_path, width=iw, height=ih)


def _watermark_maker(text):
    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont(CN, 40)
        canvas.setFillColor(colors.Color(0.85, 0.85, 0.85))
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, text)
        canvas.restoreState()
    return _draw


def build_pdf(path, flowables, *, title="", author="", subject="", creator="",
              watermark=None, encrypt_password=None):
    """落地一个 PDF：可设元数据(title/author/subject/creator)、水印、口令加密。"""
    raw_path = path
    if encrypt_password:
        raw_path = path + ".raw.pdf"
    doc = SimpleDocTemplate(raw_path, pagesize=A4, title=title, author=author,
                            subject=subject, creator=creator,
                            topMargin=2.2 * cm, bottomMargin=2 * cm)
    if watermark:
        wm = _watermark_maker(watermark)
        doc.build(list(flowables), onFirstPage=wm, onLaterPages=wm)
    else:
        doc.build(list(flowables))

    if encrypt_password:
        from pypdf import PdfReader, PdfWriter
        r = PdfReader(raw_path)
        w = PdfWriter()
        for pg in r.pages:
            w.add_page(pg)
        # 保留元数据
        try:
            w.add_metadata(r.metadata or {})
        except Exception:
            pass
        w.encrypt(encrypt_password)
        with open(path, "wb") as f:
            w.write(f)
        try:
            os.remove(raw_path)
        except OSError:
            pass
    return path


# --------------------------------------------------------------- docx/zip ---
def build_docx(path, title, paragraphs):
    """生成 .docx（python-docx）；可设核心属性 author/last_modified_by。"""
    from docx import Document
    doc = Document()
    doc.add_heading(title, level=0)
    for p in paragraphs:
        doc.add_paragraph(p)
    doc.save(path)
    return path


def set_docx_author(path, author):
    from docx import Document
    doc = Document(path)
    doc.core_properties.author = author
    doc.core_properties.last_modified_by = author
    doc.save(path)


def build_zip(path, files):
    """把若干文件打进一个 zip（多格式混杂测试）。files: [(arcname, src_path)]"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, src in files:
            z.write(src, arc)
    return path
