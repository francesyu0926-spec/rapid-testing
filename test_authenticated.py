# -*- coding: utf-8 -*-
"""登录后(已认证)功能测试 —— 使用会话复用, 跳过验证码.

前置:
  1) 先人工登录一次并导出登录态:
       python save_auth_state.py
     按提示在浏览器里完成账号/扫码 + 滑块验证码, 登录成功后回终端按回车.
  2) 运行本文件:
       pytest test_authenticated.py -v

原理:
  authenticated_driver fixture(见 conftest.py) 会先屏蔽微信/验证码第三方域(它们会
  拖死渲染进程), 再把 auth_state.json 里的 localStorage(含 JWT token, redux-persist)
  注入浏览器并重新加载, 使其直接处于"已登录"状态. 因此完全不需要在自动化里通过滑块.

说明:
  该站登录态是 localStorage 里的 token, 而非 Cookie, 故"是否已登录"的判据是
  "不再停留在 /login" + "localStorage 里有 token".
"""

import json
import re
import time

import pytest

from selenium.webdriver.common.by import By

TOKEN_LS_KEY = "persist:redux-state"


def _current_url(driver) -> str:
    """容错读取当前 URL(渲染进程偶发无响应时返回空串)."""
    try:
        return driver.current_url
    except Exception:
        return ""


def _wait_off_login(driver, timeout: int = 15) -> str:
    """轮询等待 URL 离开 /login, 返回最终 URL. 不用 readyState 以免被后台活动卡死."""
    deadline = time.time() + timeout
    url = _current_url(driver)
    while time.time() < deadline:
        url = _current_url(driver)
        if url and "/login" not in url:
            return url
        time.sleep(0.5)
    return url


def _redux_token(driver) -> str:
    """从 localStorage 的 redux-persist 中解析出 JWT token(取不到返回空串)."""
    try:
        raw = driver.execute_script(
            "return window.localStorage.getItem(arguments[0]);", TOKEN_LS_KEY
        )
        if not raw:
            return ""
        # persist:redux-state 是"每个 reducer 再 JSON 字符串化"的双层结构
        outer = json.loads(raw)
        global_state = json.loads(outer.get("global", "{}"))
        return global_state.get("token", "") or ""
    except Exception:
        return ""


@pytest.mark.auth
class TestAuthenticatedSession:
    """验证会话复用确实让浏览器进入了已登录状态."""

    def test_not_redirected_to_login(self, authenticated_driver):
        """用例21: 注入登录态后访问首页, 不应被重定向回 /login."""
        url = _wait_off_login(authenticated_driver, timeout=15)
        assert url and "/login" not in url, (
            f"仍停留在登录页, 登录态可能已过期, 请重新运行 save_auth_state.py. 当前: {url!r}"
        )

    def test_token_present_in_storage(self, authenticated_driver):
        """用例22: 已登录会话的 localStorage 中应存在有效 token."""
        token = _redux_token(authenticated_driver)
        assert token, "localStorage 中未解析到 token, 登录态注入可能失败或已过期"
        # JWT 形如 xxx.yyy.zzz
        assert token.count(".") == 2, f"token 格式异常: {token[:20]}..."

    def test_no_login_form_visible(self, authenticated_driver):
        """用例23: 已登录状态下不应再出现账号登录表单(#username)."""
        driver = authenticated_driver
        _wait_off_login(driver, timeout=15)
        login_inputs = driver.find_elements(By.ID, "username")
        assert not any(el.is_displayed() for el in login_inputs), "已登录却仍显示账号登录表单"


@pytest.mark.auth
class TestProjectListPage:
    """登录后默认落地页: 我的项目 / 项目列表 (/ai/my-projects/list).

    选择器与操作封装在 pages/project_page.py 的 ProjectPage; 这里通过 project_page
    fixture(已注入登录态)调用.
    """

    def test_lands_on_project_list(self, project_page):
        """用例24: 注入登录态后应自动进入项目列表页(/ai/my-projects/list, 标题"项目列表")."""
        assert project_page.on_project_list(timeout=20), (
            f"未跳转到项目列表页, 当前: {project_page.current_url()!r}"
        )
        assert project_page.wait_mounted(), "React 未挂载出内容"
        assert project_page.driver.title == "项目列表", (
            f"页面标题应为'项目列表', 实际: {project_page.driver.title!r}"
        )

    def test_sidebar_and_menu_visible(self, project_page):
        """用例25: 左侧导航栏与菜单应可见, 且包含一级菜单项.

        注: "快检项目"是"我的项目"子菜单下的项, 是否在 DOM 取决于子菜单展开状态,
        其存在性与可达性由用例27(点击跳转)单独保证, 这里只断言稳定的一级项.
        """
        project_page.wait_mounted()
        assert project_page.sider_visible(), "左侧导航栏不可见"
        assert project_page.menu_visible(), "根菜单不可见"
        texts = project_page.menu_texts()
        for expected in ("我的项目", "项目列表"):
            assert any(expected in t for t in texts), f"菜单缺少'{expected}', 实际: {texts}"

    def test_project_list_content_loaded(self, project_page):
        """用例26: 项目列表页内容应加载完成(有数据出分页, 无数据出空态)."""
        project_page.on_project_list(timeout=20)
        project_page.wait_mounted()
        assert project_page.list_content_loaded(timeout=20), (
            "项目列表页内容未加载(既无分页也无空态)"
        )

    def test_project_list_has_pagination(self, project_page):
        """用例27: 项目列表应有数据并渲染出分页组件(.ant-pagination).

        注: 本用例依赖该账号项目列表存在数据; 若列表为空(只有空态)会失败,
        这是有意为之的"有数据"校验. 仅校验页面框架请用用例26.
        """
        project_page.on_project_list(timeout=20)
        project_page.wait_mounted()
        assert project_page.has_pagination(timeout=20), (
            "项目列表未出现分页组件(可能该账号暂无项目数据)"
        )

    def test_navigate_to_quick_check(self, project_page):
        """用例28: 点击菜单"快检项目", 应跳转到 /ai/my-projects/quick-check."""
        project_page.wait_mounted()
        assert project_page.goto_quick_check(timeout=15), (
            f"点击后未跳转到快检项目页, 当前: {project_page.current_url()!r}"
        )


@pytest.mark.auth
class TestQuickCheckPage:
    """快检项目页 (/ai/my-projects/quick-check).

    选择器来自 discover_menu.py 对该页真实 DOM 的实测:
      - 与列表页共用左侧栏/菜单
      - 顶部有路由标签条 .ant-tabs-tab(项目列表 / 快检项目)
      - 右上角角色下拉 .ant-select(当前账号为"项目经理")
    """

    def test_enter_quick_check_and_title(self, project_page):
        """用例29: 进入快检项目页, URL 与文档标题应正确."""
        project_page.wait_mounted()
        assert project_page.goto_quick_check(timeout=15), (
            f"未能进入快检项目页, 当前: {project_page.current_url()!r}"
        )
        assert project_page.driver.title == "快检项目", (
            f"标题应为'快检项目', 实际: {project_page.driver.title!r}"
        )

    def test_router_tab_shows_quick_check(self, project_page):
        """用例30: 进入快检项目后, 顶部路由标签条应出现"快检项目"标签."""
        project_page.wait_mounted()
        project_page.goto_quick_check(timeout=15)
        tabs = project_page.router_tab_texts()
        assert any("快检项目" in t for t in tabs), f"路由标签条缺少'快检项目', 实际: {tabs}"

    def test_sidebar_persists_on_quick_check(self, project_page):
        """用例31: 切到快检项目页后, 左侧导航框架应持久存在(菜单仍含"项目列表")."""
        project_page.wait_mounted()
        project_page.goto_quick_check(timeout=15)
        assert project_page.sider_visible(), "快检项目页左侧导航栏不可见"
        assert project_page.menu_visible(), "快检项目页根菜单不可见"
        texts = project_page.menu_texts()
        assert any("项目列表" in t for t in texts), f"菜单缺少'项目列表', 实际: {texts}"

    def test_back_to_project_list(self, project_page):
        """用例32: 从快检项目页点"项目列表"菜单, 应跳回项目列表页."""
        project_page.wait_mounted()
        project_page.goto_quick_check(timeout=15)
        assert project_page.goto_project_list(timeout=15), (
            f"未能跳回项目列表页, 当前: {project_page.current_url()!r}"
        )

    def test_quick_check_has_data(self, project_page):
        """用例33: "快检项目"页有快检任务数据(该账号已建快检项目)."""
        assert project_page.ensure_quick_check_loaded(attempts=4, timeout=20), (
            "快检项目列表未加载出数据"
        )
        assert project_page.row_count() >= 1, "快检项目页无数据行(该账号可能暂无快检项目)"


@pytest.mark.auth
class TestQuickCheckList:
    """快检项目列表 (/ai/my-projects/quick-check) —— 校验点参照需求书 4.2 我的项目(自助快检).

    投标人可新建任务、上传招标/投标文件做规范校验等(需求书 4.2.1).
    """

    def test_quick_check_columns(self, project_page):
        """用例34: 快检项目列表表头应含 序号/项目名称/标段/招标方/校验任务状态/任务状态/创建时间/操作."""
        assert project_page.ensure_quick_check_loaded(attempts=4, timeout=20), "快检列表未加载"
        headers = project_page.table_headers()
        for col in project_page.EXPECTED_QC_COLUMNS:
            assert col in headers, f"快检列表缺少列'{col}', 实际表头: {headers}"

    def test_quick_check_new_project_button(self, project_page):
        """用例35: 快检项目页应提供"新建项目"入口(需求书 4.2.1 新建项目/上传文件自测)."""
        project_page.ensure_quick_check_loaded(attempts=4, timeout=20)
        assert project_page.has_new_project_button(), "快检项目页缺少'新建项目'按钮"

    def test_quick_check_search_controls(self, project_page):
        """用例36: 快检项目页应提供"搜索/重置"筛选控件."""
        project_page.ensure_quick_check_loaded(attempts=4, timeout=20)
        assert project_page.has_search_controls(), "快检项目页缺少搜索/重置按钮"

    def test_quick_check_row_actions(self, project_page):
        """用例37: 快检项目行操作列应含 编辑/执行 操作."""
        project_page.ensure_quick_check_loaded(attempts=4, timeout=20)
        assert project_page.has_action_buttons("编辑", "执行"), "快检项目行缺少'编辑/执行'操作按钮"


@pytest.mark.auth
class TestQuickCheckDetail:
    """快检详情(自助快检报告) —— 各审查项校验点参照需求说明书 3.2 / 3.3 / 4.2.

    通过 quick_check_detail_page fixture 进入某快检项目的快检详情页.
    """

    def test_enter_quick_check_detail(self, quick_check_detail_page):
        """用例38: 进入的应是快检详情(标题"快检详情", URL /quick-check/<id>)."""
        detail = quick_check_detail_page
        assert re.search(r"/ai/my-projects/quick-check/\d+", detail.current_url()), (
            f"URL 不是快检详情, 当前: {detail.current_url()!r}"
        )
        assert detail.driver.title == "快检详情", (
            f"详情页标题应为'快检详情', 实际: {detail.driver.title!r}"
        )

    def test_export_report_button(self, quick_check_detail_page):
        """用例39: 快检详情应提供"导出报告"按钮."""
        assert quick_check_detail_page.has_export_button(), "快检详情缺少'导出报告'按钮"

    def test_audit_sections_present(self, quick_check_detail_page):
        """用例40: 快检详情"本页目录"应含各审查区块(需求书 3.2/3.3)."""
        missing = quick_check_detail_page.missing_sections(
            quick_check_detail_page.QUICK_CHECK_SECTIONS
        )
        assert not missing, f"快检详情缺少审查区块: {missing}"

    def test_record_audit_headers(self, quick_check_detail_page):
        """用例41: 招标备案识别表头应含 一致数量/不一致数量/缺项数量(需求书 3.2.2 招标备案一致)."""
        assert quick_check_detail_page.has_headers(
            ["一致数量", "不一致数量", "缺项数量"]
        ), f"招标备案识别表头不符, 实际表头: {quick_check_detail_page.header_texts()}"

    def test_file_property_headers(self, quick_check_detail_page):
        """用例42: 文件属性校验表头应含 文件作者/最后修改人/计算机名称/所有者(需求书 3.3.4 / 4.3.2.9)."""
        assert quick_check_detail_page.has_headers(
            ["文件作者", "最后修改人", "计算机名称", "所有者"]
        ), f"文件属性校验表头不符, 实际表头: {quick_check_detail_page.header_texts()}"

    def test_same_bid_warning_rule(self, quick_check_detail_page):
        """用例43: 相同投标预警应体现"共同投标15次以上且合计中标5次以上"规则(需求书 3.3.6 / 4.3.2.4)."""
        assert quick_check_detail_page.text_contains("相同投标预警", "15次以上", "5次以上"), (
            "快检详情未体现相同投标预警规则(15次/5次)"
        )

    def test_bid_count_warning_rule(self, quick_check_detail_page):
        """用例44: 投标次数预警应体现"一年内投标20次以上且从未中标"规则(需求书 3.3.5)."""
        assert quick_check_detail_page.text_contains("投标次数预警", "20次以上"), (
            "快检详情未体现投标次数预警规则(20次以上/从未中标)"
        )

    def test_price_rule_headers(self, quick_check_detail_page):
        """用例45: 报价规律校验表头应含 报价/投标人均价/与最高限价占比 等报价对比列(需求书 3.3.10 / 4.3.2.10)."""
        assert quick_check_detail_page.has_headers(
            ["报价(元)", "投标人均价(元)", "与最高限价占比(%)"]
        ), f"报价规律校验表头不符, 实际表头: {quick_check_detail_page.header_texts()}"


@pytest.mark.auth
class TestProjectListTable:
    """项目列表表格 (/ai/my-projects/list) —— 校验点参照需求说明书.

    需求依据:
      - 项目信息列表(接口清单序号 71)
      - 项目经理对"未开标"(开标前)项目无权查看检测信息(需求书 2.3)
    """

    def test_list_columns(self, project_page):
        """用例46: 项目列表表头应包含需求约定的项目信息列."""
        assert project_page.ensure_list_loaded(attempts=4, timeout=20), "项目列表未加载出数据"
        headers = project_page.table_headers()
        for col in project_page.EXPECTED_LIST_COLUMNS:
            assert col in headers, f"项目列表缺少列'{col}', 实际表头: {headers}"

    def test_list_search_controls(self, project_page):
        """用例47: 项目列表应提供"搜索/重置"筛选控件."""
        project_page.ensure_list_loaded(attempts=4, timeout=20)
        assert project_page.has_search_controls(), "项目列表缺少搜索/重置按钮"

    def test_list_has_rows(self, project_page):
        """用例48: 项目列表应有数据行(依赖该账号存在项目)."""
        project_page.ensure_list_loaded(attempts=4, timeout=20)
        assert project_page.row_count() >= 1, "项目列表无数据行(该账号可能暂无项目)"

    def test_open_project_detail_via_name_link(self, project_page):
        """用例49: 点击列表中项目名称链接应进入项目详情页(标题"项目详情", URL /list/<id>)."""
        if not project_page.ensure_list_loaded(attempts=4, timeout=20):
            pytest.skip("项目列表未加载")
        if not project_page.first_row_status("开标中"):
            pytest.skip("列表中无'开标中'项目, 跳过")
        assert project_page.click_row_with_status("开标中", timeout=20), (
            "点击项目名称未进入详情页"
        )
        assert project_page.on_project_detail(), (
            f"URL 不是项目详情, 当前: {project_page.current_url()!r}"
        )
        assert project_page.driver.title == "项目详情", (
            f"详情页标题应为'项目详情', 实际: {project_page.driver.title!r}"
        )


@pytest.mark.auth
class TestProjectDetailOpenBid:
    """项目详情 - 开标中环节检查 —— 各审查项校验点参照需求说明书 3.3 / 4.3.2.

    通过 project_detail_page fixture 进入某"开标中"项目详情页(默认展示开标中环节).
    """

    def test_export_report_button(self, project_detail_page):
        """用例50: 详情页应提供"导出报告"按钮."""
        assert project_detail_page.has_export_button(), "详情页缺少'导出报告'按钮"

    def test_stage_steps(self, project_detail_page):
        """用例51: 详情页应含开标前/开标中/评标中/评标后四个阶段步骤(需求书 4.3 结构)."""
        missing = project_detail_page.missing_stage_steps()
        assert not missing, f"详情页缺少阶段步骤: {missing}"

    def test_audit_sections_present(self, project_detail_page):
        """用例52: 开标中阶段应包含各审查区块(需求书 3.3 / 4.3.2)."""
        missing = project_detail_page.missing_sections(
            project_detail_page.OPEN_BID_SECTIONS
        )
        assert not missing, f"开标中环节缺少审查区块: {missing}"

    def test_bid_ip_audit_headers(self, project_detail_page):
        """用例53: 投标IP校验表头应含 报名/下载/上传 IP(需求书 4.3.2.7, 3.3.8)."""
        assert project_detail_page.has_headers(
            ["报名IP", "下载招标文件IP", "上传投标文件IP"]
        ), f"投标IP校验表头不符, 实际表头: {project_detail_page.header_texts()}"

    def test_file_property_audit_headers(self, project_detail_page):
        """用例54: 文件属性校验表头应含 文件作者/最后修改人/计算机名称/所有者(需求书 4.3.2.9)."""
        assert project_detail_page.has_headers(
            ["文件作者", "最后修改人", "计算机名称", "所有者"]
        ), f"文件属性校验表头不符, 实际表头: {project_detail_page.header_texts()}"

    def test_bid_count_warning_rule(self, project_detail_page):
        """用例55: 投标次数预警应体现"一年内投标20次以上且从未中标"规则(需求书 3.3.5)."""
        assert project_detail_page.text_contains("投标次数预警", "20次以上"), (
            "详情页未体现投标次数预警规则(20次以上/从未中标)"
        )

    def test_price_rule_deviation(self, project_detail_page):
        """用例56: 报价规律校验应体现等差规律及"10%"偏差说明(需求书 4.3.2.10)."""
        assert project_detail_page.text_contains("报价规律", "10%"), (
            "详情页未体现报价规律等差偏差(10%)说明"
        )


@pytest.mark.auth
class TestProjectDetailPreBid:
    """项目详情 - 开标前环节校验 —— 校验点参照需求说明书 3.2 / 4.3.1.

    通过 prebid_detail_page fixture 进入某"开标前"项目详情页(默认展示开标前环节校验).
    """

    def test_prebid_sections_present(self, prebid_detail_page):
        """用例57: 开标前阶段应含 招标文件识别/招标备案识别/招标成员关系分析(需求书 3.2 / 4.3.1)."""
        missing = prebid_detail_page.missing_sections(
            prebid_detail_page.PREBID_SECTIONS
        )
        assert not missing, f"开标前环节缺少审查区块: {missing}"

    def test_prebid_has_stage_and_export(self, prebid_detail_page):
        """用例58: 开标前项目详情同样含四阶段步骤与"导出报告"按钮."""
        assert not prebid_detail_page.missing_stage_steps(), (
            f"缺少阶段步骤: {prebid_detail_page.missing_stage_steps()}"
        )
        assert prebid_detail_page.has_export_button(), "缺少'导出报告'按钮"
