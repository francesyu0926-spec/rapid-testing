# -*- coding: utf-8 -*-
"""L2 自洽性 —— 详情页展示的"事实"应自洽, 且(在有材料 oracle 时)与上传文件一致.

分两类, 均只校验**可确定性比对的事实**, 不评判 AI 的围标/串标结论:

A. 跨区块自洽性(TestDetailCrossSection): 同一"已完成"项目详情里, 各检测区块列出的
   投标单位集合应当一致 —— 投标IP校验 / 投标次数预警 / 投标文件查重(矩阵) 涉及的单位
   应为同一批、家数相同. 该类不依赖外部文件, 对任何有数据的完成项目都成立, 是核心回归项.

B. 与上传文件一致(TestQuickCheckVsFiles): 若当前账号快检列表中存在与测试资料目录匹配的
   "已完成"项目, 则校验详情页如实呈现该项目的项目名/投标单位/家数. 无匹配项目时 skip
   (例如材料项目是在其它账号下创建的).
"""

import pytest

pytestmark = [pytest.mark.consistency, pytest.mark.auth]


def _section_units(detail, section, name_cols=("单位名称", "投标单位")):
    """从普通表格区块(每行一个单位)抽取单位名集合; 无数据返回 (set(), False)."""
    tb = detail.section_table(section)
    if not tb.get("has_table") or tb.get("empty") or not tb.get("rows"):
        return set(), False
    headers = tb.get("headers", [])
    idx = -1
    for i, h in enumerate(headers):
        if any(n in h for n in name_cols):
            idx = i
            break
    if idx < 0:
        return set(), False
    units = set()
    for row in tb["rows"]:
        if idx < len(row):
            v = (row[idx] or "").strip()
            if v and v not in ("-", "—", "暂无数据"):
                units.add(v)
    return units, bool(units)


def _matrix_units(detail, section="投标文件查重"):
    """从查重矩阵抽取单位名集合(取自表头与行首列); 无数据返回 (set(), False)."""
    tb = detail.section_table(section)
    if not tb.get("has_table") or tb.get("empty") or not tb.get("rows"):
        return set(), False
    units = set(h.strip() for h in tb.get("headers", [])[1:] if h and h.strip())
    for row in tb["rows"]:
        if row and row[0].strip():
            units.add(row[0].strip())
    units.discard("")
    return units, bool(units)


class TestDetailCrossSection:
    """跨区块自洽: 同一完成项目里各检测区块涉及的投标单位应一致(核心回归项)."""

    def test_bidder_set_consistent_across_sections(self, project_detail_page):
        d = project_detail_page
        ip_units, ip_ok = _section_units(d, "投标IP校验")
        cnt_units, cnt_ok = _section_units(d, "投标次数预警")
        file_units, file_ok = _section_units(d, "投标文件校验")
        mtx_units, mtx_ok = _matrix_units(d, "投标文件查重")
        hw_units, hw_ok = _matrix_units(d, "投标笔迹校验")

        present = [(n, u) for n, u, ok in
                   (("投标IP校验", ip_units, ip_ok),
                    ("投标次数预警", cnt_units, cnt_ok),
                    ("投标文件校验", file_units, file_ok),
                    ("投标文件查重", mtx_units, mtx_ok),
                    ("投标笔迹校验", hw_units, hw_ok)) if ok]
        if len(present) < 2:
            pytest.skip(f"有数据的可比对区块不足2个(实得{[n for n,_ in present]}), 无法做跨区块自洽比对")

        ref_name, ref_units = present[0]
        for name, units in present[1:]:
            assert units == ref_units, (
                f"投标单位集合在区块间不一致: [{ref_name}]={sorted(ref_units)} "
                f"vs [{name}]={sorted(units)}"
            )

    def test_bidder_count_consistent_across_sections(self, project_detail_page):
        d = project_detail_page
        sizes = {}
        for name in ("投标IP校验", "投标次数预警", "投标文件校验"):
            units, ok = _section_units(d, name)
            if ok:
                sizes[name] = len(units)
        for name in ("投标文件查重", "投标笔迹校验"):
            units, ok = _matrix_units(d, name)
            if ok:
                sizes[name] = len(units)
        if len(sizes) < 2:
            pytest.skip(f"有数据的区块不足2个(实得{list(sizes)}), 无法比对家数")
        uniq = set(sizes.values())
        assert len(uniq) == 1, f"各区块投标家数不一致: {sizes}"


class TestQuickCheckVsFiles:
    """与上传文件一致: 详情页如实呈现取自材料目录的项目名/投标单位/家数(无匹配项目时 skip)."""

    def test_project_name_shown(self, consistency_context):
        ctx = consistency_context
        assert ctx["name_hit"], (
            f"详情页未出现期望项目名 '{ctx['expected']['name'][:30]}' "
            f"(在线名='{ctx['online_name']}', blob长度={ctx['blob_len']})"
        )

    def test_all_uploaded_bidders_shown(self, consistency_context):
        ctx = consistency_context
        assert ctx["units_total"] > 0, "期望投标单位为空, 无法比对(材料解析问题)"
        assert ctx["units_found"] == ctx["units_total"], (
            f"投标单位命中 {ctx['units_found']}/{ctx['units_total']}, 缺失={ctx['units_missing']}"
        )
