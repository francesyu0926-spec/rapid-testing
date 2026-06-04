# -*- coding: utf-8 -*-
"""L0 冒烟测试: 登录态有效性 + 三角色切换落地正确 + 各角色菜单可达.

对应测试计划 3.1(SM-01) / 3.2(RL-01~04). 依赖会话复用(authenticated_driver),
不依赖构造后端数据, 作为整系统回归基线. 需先运行 save_auth_state.py 生成 auth_state.json.

设计上把"三角色切换"合并到单个用例里在同一会话内完成(角色仅会话内生效, 避免反复注入登录态),
其余冒烟项各自独立断言。
"""

import pytest

from pages.project_page import ProjectPage

pytestmark = [pytest.mark.smoke, pytest.mark.auth]


@pytest.fixture
def project_page_sm(authenticated_driver, base_url):
    page = ProjectPage(authenticated_driver, base_url)
    page.wait_mounted()
    page.wait_app_chrome(timeout=40)
    return page


class TestSmoke:
    def test_sm01_session_authenticated(self, project_page_sm):
        """SM-01: 注入登录态后不被重定向到登录页, 且进入业务页(出现侧栏/菜单)."""
        url = project_page_sm.current_url()
        assert "/login" not in url, f"会话复用失败, 被重定向到登录页: {url}"
        assert project_page_sm.sider_visible() or project_page_sm.menu_visible(), \
            "登录后未渲染出侧栏/导航菜单"

    def test_rl_switch_all_roles(self, project_page_sm):
        """RL-01/02/03: 在同一会话内依次切到 投标人员/项目经理, 校验落地页与关键元素."""
        page = project_page_sm

        # 投标人员 -> my-tasks/list 且出现"新建项目"
        assert page.switch_role("投标人员"), "切换到投标人员失败"
        assert page.MY_TASKS_PATH in page.current_url(), \
            f"投标人员未落地我的任务页: {page.current_url()}"
        assert page.has_new_project_button(), "投标人员任务页未出现'新建项目'按钮"

        # 项目经理 -> my-projects/list, 菜单含"快检项目"
        assert page.switch_role("项目经理"), "切换到项目经理失败"
        assert page.PROJECT_LIST_PATH in page.current_url() or "my-projects" in page.current_url(), \
            f"项目经理未落地我的项目页: {page.current_url()}"
        menus = page.menu_texts()
        assert any("快检项目" in m or "项目列表" in m for m in menus), \
            f"项目经理菜单缺少 项目列表/快检项目: {menus}"

    def test_rl04_project_manager_menus(self, project_page_sm):
        """RL-04: 项目经理角色左侧菜单包含需求功能架构的核心项."""
        page = project_page_sm
        assert page.switch_role("项目经理"), "切换到项目经理失败"
        menus = page.menu_texts()
        assert menus, "未读取到任何左侧菜单项"
        # 至少包含"我的项目"及其下"项目列表/快检项目"
        joined = " ".join(menus)
        assert "我的项目" in joined, f"菜单缺少'我的项目': {menus}"
        assert ("项目列表" in joined) and ("快检项目" in joined), \
            f"菜单缺少 项目列表/快检项目: {menus}"
