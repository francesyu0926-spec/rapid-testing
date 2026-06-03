# -*- coding: utf-8 -*-
"""快检"新建项目"上传功能用例.

默认(安全): 打开抽屉 -> 填项目名/招标/2家投标 -> 校验文件名出现 -> 取消, 不产生数据.
加 --do-submit: 用真实主投标文件实跑提交, 断言提交被接受(抽屉关闭 + 项目出现在列表).

说明:
  - 备案文件按需求不上传.
  - 自动化验证的是"功能/流程"是否正确(能填、能传、能提交、项目入列),
    并不验证 AI 检测结果(围标/串标判定)的算法准确性 —— 那需要带标注的标准答案逐项比对.

用法:
  pytest test_upload.py -v                      # 仅安全用例(填表+取消)
  pytest test_upload.py -v --do-submit          # 额外真实提交一次(产生正式数据)
  pytest test_upload.py -v --materials-dir "D:\\路径"
"""
import re
import time
from pathlib import Path

import pytest

from pages.project_page import ProjectPage

PROJECT_DIR_NAME = "项目001-工程施建"
SMALL_BID_CANDIDATES = ["投标函.pdf", "封面.pdf", "投标报价汇总表.pdf"]


def extract_project_name(tender_pdf: str) -> str:
    """从招标文件首页标题(在"招标文件/招标编号"之前的标题行)提取项目名称."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(tender_pdf)
        text = reader.pages[0].extract_text() or ""
    except Exception:
        return ""
    out = []
    for line in text.splitlines():
        s = re.sub(r"\s", "", line)
        if not s:
            continue
        if "招标文件" in s or "招标编号" in s or "招标公告" in s:
            break
        out.append(line)
    name = re.sub(r"\s+", "", "".join(out))
    return name[:80]


def _resolve_project(materials_dir: Path, use_full_bid: bool, max_bidders: int = 2):
    """从测试资料里解析: 项目名, 招标文件路径, [(单位名, 投标文件路径), ...]."""
    proj = materials_dir / PROJECT_DIR_NAME
    if not proj.exists():
        return None
    cand = list((proj / "招标文件").rglob("招标文件正文.pdf"))
    if not cand:
        cand = list((proj / "招标文件").rglob("*.pdf"))
    if not cand:
        return None
    tender = cand[0]

    bidders = []
    for d in sorted(proj.iterdir()):
        if not (d.is_dir() and d.name.endswith("的投标文件")):
            continue
        unit = d.name[: -len("的投标文件")]
        if use_full_bid:
            main = d / f"{unit}投标文件.pdf"
            pdf = main if main.exists() else next(iter(sorted(d.glob("*投标文件.pdf"))), None)
        else:
            pdf = None
            for name in SMALL_BID_CANDIDATES:
                if (d / name).exists():
                    pdf = d / name
                    break
            if pdf is None:
                pdfs = sorted(d.glob("*.pdf"), key=lambda p: p.stat().st_size)
                pdf = pdfs[0] if pdfs else None
        if pdf and pdf.exists():
            bidders.append((unit, str(pdf)))
        if len(bidders) >= max_bidders:
            break
    if len(bidders) < 2 or not tender.exists():
        return None
    return proj.name, str(tender), bidders


@pytest.fixture
def quick_check_page(project_page: ProjectPage):
    """进入快检列表并确保"新建项目"按钮可用."""
    assert project_page.ensure_quick_check_loaded(attempts=4, timeout=20), "快检列表未能加载"
    return project_page


@pytest.mark.auth
class TestNewProjectUpload:
    """用例59-61: 新建快检项目上传."""

    def test_59_open_new_project_drawer(self, quick_check_page: ProjectPage):
        """用例59: 点击"新建项目"能打开抽屉, 且含 招标/备案/投标 上传控件."""
        assert quick_check_page.open_new_project_modal(timeout=12), "未能打开新建项目抽屉"
        try:
            files = quick_check_page.driver.find_elements(
                *ProjectPage.MODAL_FILE_INPUTS)
            names = quick_check_page.driver.find_elements(
                *ProjectPage.UNIT_NAME_INPUTS)
            # 招标[0]+备案[1]+默认2家投标 = 至少 4 个文件输入, 2 个单位名称输入
            assert len(files) >= 4, f"文件上传控件数量异常: {len(files)}"
            assert len(names) >= 2, f"投标单位名称输入数量异常: {len(names)}"
        finally:
            quick_check_page.cancel_modal()

    def test_60_fill_form_and_cancel(self, quick_check_page: ProjectPage, materials_dir: Path):
        """用例60: 填项目名+招标+2家投标(不传备案), 校验文件名出现后取消, 不提交."""
        info = _resolve_project(materials_dir, use_full_bid=False)
        if info is None:
            pytest.skip(f"测试资料缺失或不完整: {materials_dir / PROJECT_DIR_NAME}")
        _, tender, bidders = info
        # 项目名称从招标文件中取(不乱输入)
        proj_name = extract_project_name(tender) or Path(tender).stem
        assert proj_name, "未能从招标文件提取项目名称"

        assert quick_check_page.open_new_project_modal(timeout=12), "未能打开新建项目抽屉"
        try:
            quick_check_page.fill_new_project(
                proj_name, tender, bidders, record_pdf=None, submit=False)
            time.sleep(3)
            shown = quick_check_page.modal_filenames()
            joined = " ".join(shown)
            assert Path(tender).name in joined, f"招标文件未出现在抽屉: {shown}"
            for _, bid in bidders:
                assert Path(bid).name in joined, f"投标文件 {Path(bid).name} 未出现: {shown}"
            # 备案文件未上传: 不应出现备案相关文件名(此处仅做弱校验, 文件名各异)
        finally:
            closed = quick_check_page.cancel_modal(timeout=10)
        # 取消后抽屉应关闭(antd Drawer 关闭后元素仍在 DOM, 用可见性判断)
        assert closed, "取消后抽屉未关闭"

    def test_61_submit_creates_project(self, quick_check_page: ProjectPage,
                                       materials_dir: Path, do_submit: bool):
        """用例61: 真实提交(招标+2家真实投标文件), 断言提交被接受且项目入列.

        默认跳过; 加 --do-submit 才执行(会产生正式数据并触发后端检测).
        """
        if not do_submit:
            pytest.skip("默认不真实提交; 加 --do-submit 才执行")
        info = _resolve_project(materials_dir, use_full_bid=True)
        if info is None:
            pytest.skip(f"测试资料缺失或不完整: {materials_dir / PROJECT_DIR_NAME}")
        _, tender, bidders = info
        # 项目名称从招标文件中取(不乱输入)
        proj_name = extract_project_name(tender)
        assert proj_name, "未能从招标文件提取项目名称"

        assert quick_check_page.open_new_project_modal(timeout=12), "未能打开新建项目抽屉"
        # 1) 选择文件
        quick_check_page.fill_new_project(proj_name, tender, bidders, record_pdf=None, submit=False)
        # 2) 点击"点击上传"真正上传, 并等所有进度条到 100%(招标+各家投标)
        n = quick_check_page.trigger_uploads()
        assert n >= 1 + len(bidders), f"点击上传控件数异常: {n}"
        expected = 1 + len(bidders)  # 招标 + 投标(不含备案)
        ok = quick_check_page.wait_uploads_complete(expected, timeout=600)
        if not ok:
            quick_check_page.cancel_modal()
            pytest.fail(f"上传未在 10 分钟内完成, 进度: {quick_check_page.upload_percents()}")

        # 3) 提交
        assert quick_check_page.submit_new_project(), "未找到提交按钮"

        # 抽屉关闭视为提交被接受
        closed = False
        end = time.time() + 90
        while time.time() < end:
            if not quick_check_page.new_project_form_open():
                closed = True
                break
            time.sleep(2)
        assert closed, "提交后抽屉未关闭, 可能校验未通过或提交失败"

        # 项目应出现在快检列表(列表通常按最新在前)
        found = False
        for _ in range(8):
            quick_check_page.ensure_quick_check_loaded(attempts=2, timeout=15)
            if proj_name in (quick_check_page.driver.page_source or ""):
                found = True
                break
            time.sleep(3)
        assert found, f"提交后未在快检列表中找到新项目: {proj_name}"
