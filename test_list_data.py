# -*- coding: utf-8 -*-
"""列表数据完整性 —— 对项目列表/快检列表展示数据做确定性不变量与逻辑断言.

列表数据对该账号总是存在, 是最可靠的回归断言来源(不依赖详情页渲染/后端计算).
对应需求说明书: 项目信息列表 / 4.2 我的项目(自助快检)列表.

断言均为可确定性校验的"事实/逻辑", 例如:
  · 序号在本页连续递增;
  · 招标发布时间/开标时间/创建时间 为合法时间且格式统一;
  · 开标时间 >= 招标发布时间(逻辑约束);
  · 项目状态/任务状态 为非数字短标签(枚举);
  · 快检"校验任务状态"可解析为非负计数, 且任务已完成时未执行数为 0.
"""

import re
from datetime import datetime

import pytest

pytestmark = [pytest.mark.consistency, pytest.mark.auth]

_DT = "%Y-%m-%d %H:%M:%S"


def _parse_dt(text):
    if not text:
        return None
    t = text.strip()
    try:
        return datetime.strptime(t, _DT)
    except ValueError:
        return None


def _seq_indices(rows, key="序号"):
    out = []
    for r in rows:
        m = re.search(r"\d+", r.get(key, ""))
        if m:
            out.append(int(m.group()))
    return out


class TestProjectListData:
    """项目列表(/ai/my-projects/list)数据完整性."""

    def test_index_sequential(self, project_list_data):
        idx = _seq_indices(project_list_data["rows"])
        assert idx, "未解析到任何序号"
        assert idx == list(range(idx[0], idx[0] + len(idx))), f"序号非连续递增: {idx}"

    def test_name_and_tenderer_nonempty(self, project_list_data):
        for r in project_list_data["rows"]:
            assert r.get("项目名称", "").strip(), f"项目名称为空: {r}"
            assert r.get("招标方", "").strip(), f"招标方为空: {r}"

    def test_publish_and_open_time_valid_and_ordered(self, project_list_data):
        checked = 0
        for r in project_list_data["rows"]:
            pub = _parse_dt(r.get("招标发布时间"))
            opn = _parse_dt(r.get("开标时间"))
            assert r.get("招标发布时间", "").strip(), f"招标发布时间为空: {r}"
            assert pub is not None, f"招标发布时间格式非法: {r.get('招标发布时间')!r}"
            assert opn is not None, f"开标时间格式非法: {r.get('开标时间')!r}"
            # 逻辑约束: 开标时间不应早于招标发布时间
            assert opn >= pub, (
                f"开标时间 {r.get('开标时间')} 早于招标发布时间 {r.get('招标发布时间')}"
            )
            checked += 1
        assert checked >= 1, "无可校验的时间行"

    def test_status_is_enum_label(self, project_list_data):
        allowed = {"开标前", "开标中", "开标后", "评标中", "评标后", "已结束", "待开标", "流标", "已归档"}
        seen = set()
        for r in project_list_data["rows"]:
            st = r.get("项目状态", "").strip()
            assert st, f"项目状态为空: {r}"
            assert not any(c.isdigit() for c in st), f"项目状态不应含数字: {st!r}"
            seen.add(st)
        unknown = seen - allowed
        assert not unknown, f"出现未知项目状态(请确认是否需要纳入枚举): {unknown}"


class TestQuickCheckListData:
    """快检列表(/ai/my-projects/quick-check)数据完整性."""

    def test_index_sequential(self, quick_check_list_data):
        idx = _seq_indices(quick_check_list_data["rows"])
        assert idx, "未解析到任何序号"
        assert idx == list(range(idx[0], idx[0] + len(idx))), f"序号非连续递增: {idx}"

    def test_create_time_valid(self, quick_check_list_data):
        checked = 0
        for r in quick_check_list_data["rows"]:
            ct = r.get("创建时间", "")
            assert ct.strip(), f"创建时间为空: {r}"
            assert _parse_dt(ct) is not None, f"创建时间格式非法: {ct!r}"
            checked += 1
        assert checked >= 1

    def test_check_status_counts(self, quick_check_list_data):
        """校验任务状态可解析为'已完成:a 未执行:b'(非负); 任务状态已完成 => 未执行为0."""
        checked = 0
        for r in quick_check_list_data["rows"]:
            cs = r.get("校验任务状态", "")
            done_m = re.search(r"已完成[：:]\s*(\d+)", cs)
            todo_m = re.search(r"未执行[：:]\s*(\d+)", cs)
            if not (done_m and todo_m):
                continue
            done, todo = int(done_m.group(1)), int(todo_m.group(1))
            assert done >= 0 and todo >= 0, f"校验任务计数为负: {cs!r}"
            task = r.get("任务状态", "").strip()
            if task == "已完成":
                assert todo == 0, f"任务状态已完成但未执行数={todo}(应为0): {r}"
            checked += 1
        if checked == 0:
            pytest.skip("快检列表'校验任务状态'未呈现可解析计数")

    def test_task_status_enum(self, quick_check_list_data):
        allowed = {"已完成", "执行中", "未执行", "排队中", "部分完成", "执行失败", "待执行"}
        seen = {r.get("任务状态", "").strip() for r in quick_check_list_data["rows"]}
        seen.discard("")
        assert seen, "未读取到任何任务状态"
        unknown = seen - allowed
        assert not unknown, f"出现未知任务状态(请确认是否需纳入枚举): {unknown}"

    def test_row_actions_present(self, quick_check_list_data):
        for r in quick_check_list_data["rows"]:
            op = r.get("操作", "")
            assert "编辑" in op and "执行" in op, f"快检行操作缺少 编辑/执行: {op!r}"
