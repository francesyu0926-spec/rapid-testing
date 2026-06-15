# -*- coding: utf-8 -*-
"""瑕疵标书生成器：为快检项目「轰炸测试」构造带特定瑕疵的招标/投标 PDF。

每个"场景"= 1 个快检项目 = 1 份招标文件 + N 份投标文件，瑕疵被注入到对应区块，
以便触发平台的不同检测项：

  dup    投标文件查重(3.3.1)/相同投标(3.3.6)   各家正文整段雷同
  person 人员雷同筛查(3.3.2)                   多家共用同一联系人/电话/地址
  meta   文件属性校验(3.3.4)                   多份 PDF 元数据 作者/创建者 相同
  price  报价规律校验(3.3.10)                  各家报价构成等差数列
  check  投标文件校验(3.2.6)                   缺投标函/缺签字/缺公章/缺报价表

仅依赖 reportlab（内置 STSong-Light 中文 CID 字体，无需外部字体文件）。

用法：
  python defect_bids.py                       # 生成全部场景，默认每场景 8 家
  python defect_bids.py --bidders 10          # 每场景 10 家
  python defect_bids.py --scenarios dup,price # 只生成指定场景
  python defect_bids.py --out defect_out      # 指定输出目录
"""
import argparse
import functools
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle, PageBreak)
from reportlab.lib import colors

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
CN = "STSong-Light"

# ------------------------------------------------------------------ styles ---
_ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1cn", parent=_ss["Title"], fontName=CN, fontSize=20,
                    leading=28, spaceAfter=18)
H2 = ParagraphStyle("H2cn", parent=_ss["Heading2"], fontName=CN, fontSize=14,
                    leading=20, spaceBefore=10, spaceAfter=8)
BODY = ParagraphStyle("BODYcn", parent=_ss["BodyText"], fontName=CN, fontSize=10.5,
                      leading=18, firstLineIndent=21)
CENTER = ParagraphStyle("CENTERcn", parent=BODY, alignment=1, firstLineIndent=0)

# 共用的技术方案正文（dup 场景里多家共用 → 触发查重）
SHARED_TECH = (
    "本工程施工组织设计依据招标文件及现行国家规范编制。项目部将设立以项目经理为核心的"
    "管理机构，下设技术、质量、安全、物资、财务等职能组，实行项目经理负责制。"
    "施工总体部署遵循先地下后地上、先主体后装饰的原则，合理划分施工流水段，"
    "采用平行流水与立体交叉作业相结合的组织方式，确保总工期满足招标要求。"
    "质量管理执行三检制，关键工序设置质量控制点，严格隐蔽工程验收。"
    "安全生产坚持安全第一、预防为主、综合治理方针，建立健全安全生产责任制，"
    "落实危大工程专项方案及专家论证。文明施工实行标准化工地管理，"
    "做好扬尘、噪声、污水防治，确保绿色施工目标实现。"
)

UNIQUE_TECH = (
    "我单位结合本项目{n}标段实际地质与气候条件，编制差异化施工组织方案："
    "针对{kw}采用专项工艺，配置{n}套大型机械设备，组建{n}个专业化作业班组，"
    "并就工期、质量、安全制定有别于通用做法的针对性保障措施，"
    "形成可追溯、可量化的过程管控体系。"
)


def _num_to_cn_money(amount: int) -> str:
    return f"人民币{amount:,}元整"


def build_tender_pdf(path: str, project_name: str, tender_no: str):
    """生成一份招标文件正文 PDF。"""
    doc = SimpleDocTemplate(path, pagesize=A4, title=project_name,
                            author="招标代理机构", subject="招标文件",
                            creator="招投标AI检测平台-测试数据生成器",
                            topMargin=2.2 * cm, bottomMargin=2 * cm)
    st = [
        Paragraph(project_name, H1),
        Paragraph("招　标　文　件", CENTER),
        Spacer(1, 0.6 * cm),
        Paragraph(f"招标编号：{tender_no}", CENTER),
        Paragraph("招标人：测试建设单位有限公司", CENTER),
        Paragraph("招标代理机构：测试招标代理有限公司", CENTER),
        PageBreak(),
        Paragraph("第一章　投标人须知", H2),
        Paragraph("1. 本次招标采用公开招标方式，合格的投标人均可参加投标。", BODY),
        Paragraph("2. 投标文件应包括投标函、法定代表人身份证明、投标报价表、"
                  "项目管理机构、施工组织设计及资格证明等内容，并加盖单位公章。", BODY),
        Paragraph("3. 投标报价为固定总价，应在投标函中以大写和小写同时表示。", BODY),
        Paragraph("4. 投标文件须由法定代表人或其授权代表签字并加盖单位公章，"
                  "否则按废标处理。", BODY),
        Paragraph("第二章　评标办法", H2),
        Paragraph("评标采用综合评估法，从报价、技术方案、项目业绩、人员配置等方面评审。", BODY),
        Paragraph("第三章　合同主要条款", H2),
        Paragraph("中标人应在中标通知书发出后 30 日内与招标人签订书面合同。", BODY),
    ]
    doc.build(st)


def build_bid_pdf(path, *, project_name, unit, price, contact, phone, address,
                  legal_rep, tech_body, author_meta,
                  has_bid_letter=True, has_signature=True, has_seal=True,
                  has_price_table=True):
    """生成一份投标文件 PDF；通过开关与字段注入瑕疵。"""
    doc = SimpleDocTemplate(
        path, pagesize=A4, title=f"{unit}投标文件",
        author=author_meta, subject=project_name,
        creator=author_meta, topMargin=2.2 * cm, bottomMargin=2 * cm)
    st = []
    # 封面
    st += [Spacer(1, 3 * cm), Paragraph(project_name, H1),
           Paragraph("投　标　文　件", CENTER), Spacer(1, 1 * cm),
           Paragraph(f"投标单位：{unit}", CENTER),
           Paragraph(f"投标日期：2026 年 06 月", CENTER), PageBreak()]

    # 投标函（check 场景可缺失）
    if has_bid_letter:
        st += [Paragraph("投　标　函", H2),
               Paragraph(f"致：测试建设单位有限公司", BODY),
               Paragraph(f"我方已仔细研究 {project_name} 招标文件全部内容，"
                         f"愿以投标总价 {_num_to_cn_money(price)}（小写：{price:,}元）"
                         f"承包本工程的施工。", BODY),
               Paragraph(f"投标单位：{unit}", BODY)]
        if has_signature:
            st += [Paragraph(f"法定代表人（签字）：{legal_rep}　【签字】", BODY)]
        else:
            st += [Paragraph("法定代表人（签字）：　　　　　", BODY)]
        if has_seal:
            st += [Paragraph("投标单位（盖章）：　【已加盖单位公章】", BODY)]
        else:
            st += [Paragraph("投标单位（盖章）：　　　　　", BODY)]
        st += [PageBreak()]

    # 投标报价表（check 场景可缺失）
    if has_price_table:
        data = [["序号", "项目名称", "金额（元）"],
                ["1", "分部分项工程费", f"{int(price*0.7):,}"],
                ["2", "措施项目费", f"{int(price*0.15):,}"],
                ["3", "其他项目费/规费/税金", f"{price-int(price*0.7)-int(price*0.15):,}"],
                ["", "投标总报价", f"{price:,}"]]
        tbl = Table(data, colWidths=[2 * cm, 8 * cm, 5 * cm])
        tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), CN), ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("ALIGN", (2, 0), (2, -1), "RIGHT")]))
        st += [Paragraph("投标报价表", H2), tbl, PageBreak()]

    # 项目管理机构 / 人员表（person 场景注入雷同）
    ppl = [["岗位", "姓名", "联系电话"],
           ["项目经理", legal_rep, phone],
           ["技术负责人", "王工", phone],
           ["项目联系人", contact, phone]]
    ptbl = Table(ppl, colWidths=[4 * cm, 5 * cm, 6 * cm])
    ptbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), CN), ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]))
    st += [Paragraph("项目管理机构", H2), ptbl,
           Paragraph(f"投标单位通讯地址：{address}", BODY),
           Paragraph(f"项目联系人：{contact}　联系电话：{phone}", BODY),
           PageBreak()]

    # 施工组织设计 / 技术方案（dup 场景注入雷同正文）
    st += [Paragraph("施工组织设计", H2)]
    for para in tech_body.split("\n"):
        if para.strip():
            st += [Paragraph(para.strip(), BODY)]
    doc.build(st)


# --------------------------------------------------------------- scenarios ---
BASE_PRICE = 9_800_000


def scenario_units(n):
    return [f"测试投标单位{chr(65+i)}（瑕疵）有限公司" for i in range(n)]


def gen_scenario(kind, out_dir, n_bidders):
    """生成单个场景目录: out_dir/<kind>/招标文件.pdf + 各家 <unit>的投标文件.pdf。"""
    proj_name = {
        "dup": "AUTO-DUP 投标文件查重轰炸测试项目（施工）",
        "person": "AUTO-PERSON 人员雷同轰炸测试项目（施工）",
        "meta": "AUTO-META 文件属性雷同轰炸测试项目（施工）",
        "price": "AUTO-PRICE 报价规律轰炸测试项目（施工）",
        "check": "AUTO-CHECK 投标文件校验轰炸测试项目（施工）",
    }[kind]
    sdir = os.path.join(out_dir, kind)
    os.makedirs(sdir, exist_ok=True)
    tender_path = os.path.join(sdir, "招标文件.pdf")
    build_tender_pdf(tender_path, proj_name, f"AUTO-{kind.upper()}-2026-001")

    units = scenario_units(n_bidders)
    bids = []  # (unit, path)
    for i, unit in enumerate(units):
        bdir = os.path.join(sdir, f"{unit}的投标文件")
        os.makedirs(bdir, exist_ok=True)
        bpath = os.path.join(bdir, f"{unit}投标文件.pdf")

        # 默认每家各不相同的"干净"取值
        price = BASE_PRICE + i * 137_000 + (i * i * 311)   # 非等差、带噪声
        contact = f"联系人{chr(65+i)}"
        phone = f"138{i:04d}{(i*7)%10000:04d}"
        address = f"山西省太原市测试区第{i+1}号院"
        legal_rep = f"法人{chr(65+i)}"
        author = f"投标编制员{chr(65+i)}"
        tech = UNIQUE_TECH.format(n=i + 1, kw=["深基坑", "高支模", "大体积混凝土",
                                               "钢结构", "幕墙", "机电安装",
                                               "装饰装修", "市政管网", "桩基",
                                               "土方"][i % 10])
        kw = dict(has_bid_letter=True, has_signature=True, has_seal=True,
                  has_price_table=True)

        if kind == "dup":
            # 多家共用同一整段技术方案正文 + 同一报价文字 → 查重命中
            tech = SHARED_TECH
            if i >= 1:
                price = BASE_PRICE  # 价格也雷同，强化"相同投标"
        elif kind == "person":
            # 前若干家共用同一联系人/电话/地址 → 人员雷同
            if i < max(3, n_bidders // 2):
                contact = "张建国"
                phone = "13800001111"
                address = "山西省太原市小店区雷同路1号"
                legal_rep = "张建国"
        elif kind == "meta":
            # 全部共用同一元数据(作者/创建者) → 文件属性雷同
            author = "统一编制人-赵主管"
        elif kind == "price":
            # 报价等差数列：9,800,000 / 9,900,000 / 10,000,000 ...
            price = BASE_PRICE + i * 100_000
        elif kind == "check":
            # 轮流缺失关键要件 → 投标文件校验需补正
            defect = i % 4
            if defect == 0:
                kw["has_signature"] = False      # 缺法人签字
            elif defect == 1:
                kw["has_seal"] = False           # 缺公章
            elif defect == 2:
                kw["has_price_table"] = False    # 缺投标报价表
            else:
                kw["has_bid_letter"] = False     # 缺投标函

        build_bid_pdf(bpath, project_name=proj_name, unit=unit, price=price,
                      contact=contact, phone=phone, address=address,
                      legal_rep=legal_rep, tech_body=tech, author_meta=author,
                      **kw)
        bids.append((unit, bpath))
    return proj_name, tender_path, bids


ALL_SCENARIOS = ["dup", "person", "meta", "price", "check"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="defect_out", help="输出目录")
    ap.add_argument("--bidders", type=int, default=8, help="每场景投标家数")
    ap.add_argument("--scenarios", default="", help="逗号分隔; 默认全部")
    args = ap.parse_args()

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    kinds = ([s.strip() for s in args.scenarios.split(",") if s.strip()]
             or ALL_SCENARIOS)
    print(f"输出目录: {out_dir}  每场景 {args.bidders} 家  场景: {kinds}")
    for kind in kinds:
        proj, tender, bids = gen_scenario(kind, out_dir, args.bidders)
        print(f"\n[{kind}] {proj}")
        print(f"  招标: {tender}")
        print(f"  投标: {len(bids)} 家 -> {os.path.dirname(os.path.dirname(bids[0][1]))}")
    print("\n生成完成。")


if __name__ == "__main__":
    main()
