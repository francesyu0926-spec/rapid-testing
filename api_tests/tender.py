# -*- coding: utf-8 -*-
"""招标文件定位 + 从招标文件正文提取项目名称。

目录约定：<项目文件夹>/招标文件/招标文件/招标文件正文.pdf
项目名称取自正文首页（招标人/招标编号等标记行之前的标题行）。
"""

import os
import re
import glob


def find_tender_doc(project_dir: str) -> str:
    """在某项目文件夹下定位招标文件正文 PDF；找不到返回空串。"""
    # 优先标准路径
    std = os.path.join(project_dir, "招标文件", "招标文件", "招标文件正文.pdf")
    if os.path.exists(std):
        return std
    # 退而求其次：招标文件子树里名字含“招标文件正文/招标文件”的 pdf
    cands = glob.glob(os.path.join(project_dir, "招标文件", "**", "*.pdf"),
                      recursive=True)
    for kw in ("招标文件正文", "招标文件", "招标"):
        for c in cands:
            if kw in os.path.basename(c):
                return c
    return cands[0] if cands else ""


_NAME_BREAK = ("招标文件", "招标编号", "招标公告", "采购文件", "采购编号",
               "（招标", "(招标", "招标人", "采购人", "招标代理", "采购代理")


def extract_project_name(pdf_path: str, max_len: int = 120) -> str:
    """从招标文件正文首页提取项目名称（标记行之前的标题行拼接）。"""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as doc:
            txt = doc.pages[0].extract_text() or ""
    except Exception:
        return ""
    # 先按行去掉所有空白（正文常把标题排成“招 标 文 件”这种带空格的样式）
    lines = []
    for l in txt.splitlines():
        l2 = re.sub(r"\s+", "", l)
        l2 = re.sub(r"[\u3000\ufeff]", "", l2)
        if l2:
            lines.append(l2)
    picked = []
    for l in lines:
        if any(m in l for m in _NAME_BREAK):
            break
        picked.append(l)
    name = "".join(picked)
    # 去掉结尾残留的“招标文件/采购文件/招标/采购”等
    name = re.sub(r"(招标文件|采购文件|招标公告|采购公告|招标|采购)+$", "", name)
    return name[:max_len]


_TENDERER_KEYS = ("招标人", "采购人", "招标单位", "采购单位", "建设单位")
_TENDERER_SKIP = ("须知", "名称", "授权", "代表", "联系")


def extract_tenderer(pdf_path: str, max_pages: int = 3, max_len: int = 60) -> str:
    """从招标文件正文提取招标人(招标方/采购人)名称。

    正文里通常写成“招 标 人：XXX公司/XX局”，去空格后匹配“招标人：名称”。
    匹配不到返回空串。
    """
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as doc:
            pages = [doc.pages[i].extract_text() or ""
                     for i in range(min(max_pages, len(doc.pages)))]
    except Exception:
        return ""
    for txt in pages:
        for raw in txt.splitlines():
            l = re.sub(r"\s+", "", raw)
            l = re.sub(r"[\u3000\ufeff]", "", l)
            for key in _TENDERER_KEYS:
                m = re.search(key + r"[：:]([^：:，,。；;（(\)]+)", l)
                if not m:
                    continue
                name = m.group(1).strip()
                if len(name) < 3 or any(s in name for s in _TENDERER_SKIP):
                    continue
                return name[:max_len]
    return ""


def project_dirs(root: str):
    """按名称排序返回所有顶层项目文件夹绝对路径。"""
    return [os.path.join(root, d) for d in sorted(os.listdir(root))
            if os.path.isdir(os.path.join(root, d))]
