# -*- coding: utf-8 -*-
"""L1 业务流程 E2E —— 投标人侧"我的任务/新建项目"全链路.

对应需求说明书 投标人(投标人员)角色: 切角色 -> 我的任务 -> 新建项目(项目名 + 单个投标文件PDF) -> 创建.
与快检"新建项目"(招标+备案+多家投标)不同, 投标人表单只需项目名 + 1 个投标文件.

复用 bidder_create.py 中经过实战打磨的交互(角色切换/打开表单/上传/创建), 避免重复实现.

安全取向:
  - 默认只做"打开表单 + 选文件 + 文件名出现 + 取消", 不真正上传/创建, 不产生数据;
  - 加 --do-submit 才真实上传并创建一个项目(会产生正式数据并触发后端检测);
  - fixture teardown 把角色切回"项目经理", 避免污染同一会话内后续(默认项目经理)用例.

用法:
  pytest test_bidder_e2e.py -v                 # 仅安全用例(选文件+取消)
  pytest test_bidder_e2e.py -v --do-submit     # 额外真实创建一个投标人项目
"""
import time
from pathlib import Path

import pytest
from selenium.webdriver.common.by import By

import bidder_create as bc
from pages.project_page import ProjectPage

pytestmark = [pytest.mark.e2e, pytest.mark.auth]


def _smallest_bid_pdf(materials_dir: Path, limit_mb: int = 5):
    """在材料目录里找一个尽量小(<= limit_mb)的投标 PDF, 用于安全用例快速选文件."""
    if not materials_dir.exists():
        return None
    best = None
    cap = limit_mb * 1024 * 1024
    for proj in sorted(p for p in materials_dir.iterdir() if p.is_dir())[:6]:
        for pdf in proj.rglob("*.pdf"):
            try:
                sz = pdf.stat().st_size
            except OSError:
                continue
            if 0 < sz <= cap and (best is None or sz < best[0]):
                best = (sz, pdf)
    return best[1] if best else None


@pytest.fixture
def bidder_driver(authenticated_driver):
    """已登录并切到"投标人员"角色的 driver(停在我的任务页, "新建项目"可用).

    teardown 切回"项目经理", 避免影响同一 pytest 会话内后续默认角色用例.
    """
    d = authenticated_driver
    # 注入登录态后需等应用外壳渲染, 再做角色切换
    ProjectPage(d, bc.BASE).wait_app_chrome(timeout=40)
    time.sleep(2)
    if not bc.switch_to_bidder(d):
        pytest.skip("未能切换到投标人员角色(登录态可能过期或角色渲染异常)")
    yield d
    # 还原角色, 避免污染后续用例
    try:
        bc._select_role(d, "项目经理")
        time.sleep(1.5)
    except Exception:
        pass


class TestBidderNewProject:
    def test_e2e01_open_form_controls(self, bidder_driver):
        """E2E-01: 投标人"新建项目"表单可打开, 含项目名输入与文件上传控件."""
        d = bidder_driver
        assert bc.open_form(d, timeout=15), "未能打开投标人'新建项目'表单"
        try:
            names = [e for e in d.find_elements(*bc.NAME_INPUT) if e.is_displayed()]
            files = d.find_elements(*bc.FILE_INPUT)
            assert names, "表单缺少项目名称输入框"
            assert files, "表单缺少文件上传控件(input[type=file])"
        finally:
            bc.cancel(d)

    def test_e2e02_fill_select_and_cancel(self, bidder_driver, materials_dir):
        """E2E-02(安全): 填项目名 + 选一个投标PDF, 文件名/上传触发出现后取消, 不创建."""
        d = bidder_driver
        pdf = _smallest_bid_pdf(materials_dir)
        if pdf is None:
            pytest.skip(f"材料目录无可用的小投标PDF: {materials_dir}")

        assert bc.open_form(d, timeout=15), "未能打开投标人'新建项目'表单"
        closed = False
        try:
            inputs = [e for e in d.find_elements(*bc.NAME_INPUT) if e.is_displayed()]
            assert inputs, "无项目名称输入框"
            inputs[0].clear()
            inputs[0].send_keys("E2E自动化-投标人新建(待取消)")

            files = d.find_elements(*bc.FILE_INPUT)
            assert files, "无文件上传控件"
            files[0].send_keys(str(pdf))
            time.sleep(2)

            # 选文件后应出现"点击上传"触发器(说明文件已暂存, 表单链路通)
            triggers = d.find_elements(*bc.UPLOAD_TRIGGER)
            body = d.find_elements(By.CSS_SELECTOR, ".ant-drawer-body, .ant-modal-body")
            body_text = body[0].text if body else ""
            assert triggers or (pdf.name in body_text), (
                f"选文件后未见'点击上传'触发器, 也未在表单中看到文件名 {pdf.name}"
            )
        finally:
            bc.cancel(d)
            time.sleep(1)
            closed = not bc.form_open(d)
        assert closed, "取消后表单未关闭"

    def test_e2e03_real_create(self, bidder_driver, materials_dir, do_submit):
        """E2E-03(--do-submit): 真实上传单个投标文件并创建, 断言抽屉关闭(创建被接受)."""
        if not do_submit:
            pytest.skip("默认不真实创建; 加 --do-submit 才执行")
        d = bidder_driver
        projs = sorted(p for p in materials_dir.iterdir() if p.is_dir())
        if not projs:
            pytest.skip(f"材料目录无项目: {materials_dir}")
        # 取第一个能解析出投标文件的项目
        chosen = None
        for proj in projs:
            unit, pdf = bc.pick_bid_pdf(proj)
            if pdf:
                chosen = (proj, pdf)
                break
        if not chosen:
            pytest.skip("材料目录中未找到可上传的投标PDF")
        proj, pdf = chosen
        name = bc.project_name(proj)
        result = bc.create_one(d, name, pdf, upload_timeout=600)
        assert result.startswith("成功"), f"投标人创建未成功: {result}"
