# -*- coding: utf-8 -*-
"""从"测试项目资料"目录解析单个项目, 映射到"新建项目"表单所需文件.

资料目录结构(实测):
  测试项目资料/
    项目001-工程施建/
      招标文件/招标文件正文.pdf           -> 表单"②招标文件"
      备案文件/...                          -> 表单"③备案文件"(本期跳过)
      <公司A>的投标文件/<公司A>投标文件.pdf  -> 表单"④投标文件"(每家一个)
      <公司B>的投标文件/...
      评标报告/...                          -> 非上传项, 官方评标结论(可人工对照)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


BID_SUFFIX = "的投标文件"


@dataclass
class Bidder:
    company: str
    pdf: Path
    size: int


@dataclass
class ProjectMaterials:
    name: str
    folder: Path
    tender_pdf: Optional[Path]
    bidders: List[Bidder]


def _tender_pdf(folder: Path) -> Optional[Path]:
    """招标文件: 优先 招标文件/招标文件正文.pdf, 否则该目录下最大的 pdf."""
    tender_dir = folder / "招标文件"
    if not tender_dir.is_dir():
        return None
    main = tender_dir / "招标文件正文.pdf"
    if main.is_file():
        return main
    pdfs = [p for p in tender_dir.glob("*.pdf") if p.is_file()]
    if not pdfs:
        return None
    return max(pdfs, key=lambda p: p.stat().st_size)


def _bidder_main_pdf(bidder_dir: Path, company: str) -> Optional[Path]:
    """投标单位主文件: 优先 <公司>投标文件.pdf, 否则该目录下最大的 pdf."""
    main = bidder_dir / f"{company}投标文件.pdf"
    if main.is_file():
        return main
    pdfs = [p for p in bidder_dir.glob("*.pdf") if p.is_file()]
    if not pdfs:
        return None
    return max(pdfs, key=lambda p: p.stat().st_size)


def load_project(materials_root, project_name: Optional[str] = None) -> Optional[ProjectMaterials]:
    """加载一个项目的上传素材.

    project_name 为空时取目录下第一个项目文件夹. 找不到返回 None.
    bidders 按文件大小升序排列, 方便挑"最小的几家"跑通端到端.
    """
    root = Path(materials_root)
    if not root.is_dir():
        return None

    if project_name:
        folder = root / project_name
        if not folder.is_dir():
            return None
    else:
        dirs = sorted([p for p in root.iterdir() if p.is_dir()])
        if not dirs:
            return None
        folder = dirs[0]

    bidders: List[Bidder] = []
    for sub in sorted(folder.iterdir()):
        if not sub.is_dir() or not sub.name.endswith(BID_SUFFIX):
            continue
        company = sub.name[: -len(BID_SUFFIX)]
        pdf = _bidder_main_pdf(sub, company)
        if pdf is not None:
            bidders.append(Bidder(company=company, pdf=pdf, size=pdf.stat().st_size))

    bidders.sort(key=lambda b: b.size)
    return ProjectMaterials(
        name=folder.name,
        folder=folder,
        tender_pdf=_tender_pdf(folder),
        bidders=bidders,
    )
