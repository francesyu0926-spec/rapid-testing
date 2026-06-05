# -*- coding: utf-8 -*-
"""L4 角色/阶段可见性边界。

两类边界(均经稳定会话实测确认):

1) 阶段可见性(需求 3.2 / 4.3.1 开标前检测项; 3.3 / 4.3.2 开标中检测项):
   项目经理可进入"开标前"项目详情, 且只看到该阶段应有的检测项 —— 招标侧
   (招标文件识别 / 招标备案识别 / 招标成员关系分析); 投标侧检测项(投标文件查重 /
   校验 / IP / 报价规律 / 笔迹)在"开标前"尚未产生, 应不出现; 进入"开标中"详情后
   投标侧检测项才出现。
   注: 早前曾误判"项目经理无权查看开标前详情", 实为页面异步加载未完成的假象;
   实测项目经理可查看开标前详情, 该处不是角色权限边界, 而是阶段可见性。

2) 角色权限边界(需求 2.3 / 4.2): 投标人员只能在"我的任务"内作业, 无权进入项目
   经理的"我的项目/项目列表/项目详情(检测信息)", 直接导航会被重定向回"我的任务"。
"""
import re

import pytest

pytestmark = [pytest.mark.auth, pytest.mark.permission]

_DETAIL_URL_RE = re.compile(r"/list/\d+")

# 招标侧(开标前)检测项标题
PREBID_AUDIT_MARKERS = ("招标文件识别", "招标备案识别", "招标成员关系分析")
# 投标侧检测项标题(开标后才产生; 开标前不应出现)
BID_AUDIT_MARKERS = (
    "投标文件查重", "投标文件校验", "投标IP校验",
    "投标次数预警", "报价规律", "投标笔迹校验",
)


class TestManagerPrebidPhaseVisibility:
    """项目经理进入'开标前'项目详情: 可见招标侧检测项, 但投标侧检测项尚未出现(阶段可见性)。"""

    def test_perm01_prebid_detail_reachable(self, manager_prebid_detail):
        """开标前详情对项目经理可达(URL=/list/<id>, 标题'项目详情')。"""
        ctx = manager_prebid_detail
        assert _DETAIL_URL_RE.search(ctx["url"]), (
            f"开标前项目未跳转到详情URL(/list/<id>): {ctx['url']}"
        )
        assert "项目详情" in ctx["title"], f"详情页标题异常: {ctx['title']!r}"

    def test_perm02_prebid_shows_tender_side_audit(self, manager_prebid_detail):
        """开标前详情应渲染招标侧检测项(需求 3.2/4.3.1)。"""
        body = manager_prebid_detail["body"]
        present = [m for m in PREBID_AUDIT_MARKERS if m in body]
        assert present, (
            f"开标前详情未见任何招标侧检测项{PREBID_AUDIT_MARKERS}; 正文片段: {body[:160]!r}"
        )

    def test_perm03_prebid_hides_bid_side_audit(self, manager_prebid_detail):
        """阶段门: 开标前(投标文件尚未开启)不应出现投标侧检测项。"""
        body = manager_prebid_detail["body"]
        leaked = [m for m in BID_AUDIT_MARKERS if m in body]
        assert not leaked, (
            f"开标前详情过早出现了投标侧检测项(应开标后才有): {leaked}"
        )


class TestManagerOpenbidShowsBidAudit:
    """对照: 项目经理进入'开标中'项目详情, 投标侧检测项出现, 印证阶段推进带来可见性变化。"""

    def test_perm04_openbid_shows_bid_side_audit(self, project_detail_page):
        body = project_detail_page.body_text()
        present = [m for m in BID_AUDIT_MARKERS if m in body]
        assert present, "开标中详情未见任何投标侧检测项, 阶段可见性对照失败"

    def test_perm05_openbid_has_audit_tables(self, project_detail_page):
        cnt = len(project_detail_page.driver.find_elements("css selector", ".ant-table"))
        assert cnt > 0, "开标中详情未渲染任何审查表格, 对照失败"


class TestBidderScopedToTasks:
    """投标人员视角: 只能在"我的任务"内作业, 无权进入项目经理的项目列表/项目详情(检测信息)。"""

    def test_perm07_bidder_lands_on_my_tasks(self, bidder_context):
        """切到投标人员后应落在'我的任务'(/my-tasks), 而非项目经理的'我的项目'(/my-projects)。"""
        home = bidder_context["home"]
        url = home["url"]
        assert "/my-tasks" in url, f"投标人员未落到'我的任务'页: {url}"
        assert "/my-projects" not in url, f"投标人员落到了项目经理'我的项目'页: {url}"

    def test_perm08_bidder_can_create_own_task(self, bidder_context):
        """正向: 投标人员在'我的任务'拥有'新建项目'能力(本职权限)。"""
        assert bidder_context["home"]["new_project_btn"], (
            "投标人员'我的任务'未见'新建项目'按钮(本职能力缺失)"
        )

    def test_perm09_bidder_menu_excludes_manager_project_area(self, bidder_context):
        """投标人员菜单应聚焦'我的任务', 不应出现项目经理的'我的项目'菜单。"""
        menus = bidder_context["home"]["menus"]
        joined = " | ".join(menus)
        assert any("任务" in m for m in menus), f"投标人员菜单未见'任务'相关项: {menus}"
        assert "我的项目" not in joined, (
            f"投标人员菜单不应出现项目经理的'我的项目': {menus}"
        )

    def test_perm10_bidder_cannot_open_manager_project_list(self, bidder_context):
        """投标人员直接导航到项目经理'项目列表'应被重定向回'我的任务'。"""
        url = bidder_context["manager_list"]["url"]
        assert "/my-projects" not in url, (
            f"投标人员竟停留在项目经理'我的项目/项目列表': {url}"
        )
        assert "/my-tasks" in url, f"投标人员未被重定向回'我的任务': {url}"

    def test_perm11_bidder_cannot_view_manager_project_detail(self, bidder_context):
        """投标人员直接导航到项目经理项目详情应被拦截: 重定向回'我的任务', 且不渲染任何检测信息。"""
        md = bidder_context["manager_detail"]
        assert "/my-projects" not in md["url"], (
            f"投标人员竟进入了项目经理项目详情URL: {md['url']}"
        )
        assert not md["audit_markers"], (
            f"投标人员看到了不应可见的检测区块: {md['audit_markers']}"
        )


class TestReviewerReadOnlyProjects:
    """评审专家视角(需求 2.3 角色权限): 面向项目/评标的只读评审角色。

    与投标人员对照: 评审专家可进入项目列表/项目详情(投标人员被拦截);
    与项目经理对照: 评审专家无'新建项目'能力(不可发起项目)。
    """

    def test_perm12_reviewer_role_and_landing(self, reviewer_context):
        """切到评审专家: 角色名正确, 落地项目经理同侧'我的项目'(非投标人员'我的任务')。"""
        home = reviewer_context["home"]
        assert "评审专家" in home["role"], f"角色未切到评审专家: {home['role']!r}"
        assert "/my-projects" in home["url"], f"评审专家未落到'我的项目'页: {home['url']}"
        assert "/my-tasks" not in home["url"], f"评审专家落到了投标人员'我的任务'页: {home['url']}"

    def test_perm13_reviewer_cannot_create_project(self, reviewer_context):
        """评审专家为只读评审定位, 不应拥有'新建项目'能力(区别于项目经理)。"""
        assert not reviewer_context["home"]["new_project_btn"], (
            "评审专家不应出现'新建项目'按钮(其为评审而非发起角色)"
        )

    def test_perm14_reviewer_menu_is_project_oriented(self, reviewer_context):
        """评审专家菜单面向项目('我的项目/项目列表'), 不应是投标人员的'我的任务'。"""
        menus = reviewer_context["home"]["menus"]
        joined = " | ".join(menus)
        assert any("项目" in m for m in menus), f"评审专家菜单未见'项目'相关项: {menus}"
        assert "我的任务" not in joined, f"评审专家菜单不应出现投标人员的'我的任务': {menus}"

    def test_perm15_reviewer_can_open_project_detail(self, reviewer_context):
        """评审专家可进入项目详情(与投标人员被拦截相对照)。"""
        detail = reviewer_context["detail"]
        if not detail.get("entered"):
            pytest.skip("项目列表无可进入的项目行, 无法验证评审专家详情可达")
        assert _DETAIL_URL_RE.search(detail["url"]), (
            f"评审专家点击项目未进入详情URL(/list/<id>): {detail['url']}"
        )
        assert "/my-tasks" not in detail["url"] and "/login" not in detail["url"], (
            f"评审专家进入项目详情被异常重定向: {detail['url']}"
        )
