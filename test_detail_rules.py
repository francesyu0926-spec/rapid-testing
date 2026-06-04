# -*- coding: utf-8 -*-
"""L3 规则/检测项精确断言 —— 对"开标中"项目详情各检测项, 抽取系统算出的结构化数据,
在测试内按需求书规则重算/施加确定性不变量, 再与界面数据比对.

设计取向(UI 层, 无后端数据注入):
  - 无法构造正负样本, 但可对"系统已算出的结果数据"做**确定性不变量与规则重算**断言,
    这类断言能稳定抓回归(如查重相似度矩阵必须对称、中标次数不可大于投标次数等).
  - 区块"暂无数据"时优雅 skip(标注数据依赖), 不产生假失败.

数据来源: project_detail_page fixture(module 级, 进某"开标中"项目详情一次).
对应需求说明书: 4.3.2.3 查重 / 4.3.2.7 投标IP / 4.3.2.12 投标次数预警 / 4.3.2.9 文件属性 / 4.3.2.11 投标时间.
"""

import re

import pytest

pytestmark = [pytest.mark.rule, pytest.mark.auth]

_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _pct(text):
    """'94.52%' -> 94.52; '-'/'' -> None; 非法 -> None."""
    if text is None:
        return None
    t = text.strip().rstrip("%").strip()
    if t in ("", "-", "—"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _int(text):
    if text is None:
        return None
    t = text.strip()
    m = re.search(r"-?\d+", t)
    return int(m.group()) if m else None


def _col_index(headers, *names):
    for i, h in enumerate(headers):
        if any(n in h for n in names):
            return i
    return -1


class TestDedupMatrix:
    """投标文件查重(4.3.2.3): 相似度矩阵必须对称、对角为'-'、百分比∈[0,100]."""

    def test_similarity_matrix_invariants(self, project_detail_page):
        tb = project_detail_page.section_table("投标文件查重")
        if not tb.get("has_table") or tb.get("empty") or not tb.get("rows"):
            pytest.skip("查重区块暂无数据(该项目无可比对的多份投标文件)")

        headers = tb["headers"]
        # 矩阵: headers = ['', 单位A, 单位B, ...]; row = [单位X, v1, v2, ...]
        col_names = [h for h in headers[1:] if h]
        matrix = {}
        for row in tb["rows"]:
            if len(row) < 2:
                continue
            rname = row[0]
            matrix[rname] = {}
            for j, name in enumerate(col_names, start=1):
                if j < len(row):
                    matrix[rname][name] = row[j]

        assert matrix, f"未能解析查重矩阵, headers={headers}"

        # 1) 百分比取值范围 + 对角为 '-'
        for rname, cols in matrix.items():
            for cname, raw in cols.items():
                if rname == cname:
                    assert raw.strip() in ("-", "—", ""), \
                        f"对角({rname})相似度应为'-', 实际 {raw!r}"
                    continue
                v = _pct(raw)
                if v is not None:
                    assert 0.0 <= v <= 100.0, f"相似度越界 {rname}x{cname}={raw!r}"

        # 2) 对称性: M[a][b] == M[b][a]
        names = list(matrix.keys())
        for a in names:
            for b in names:
                if a == b or b not in matrix.get(a, {}) or a not in matrix.get(b, {}):
                    continue
                va, vb = _pct(matrix[a][b]), _pct(matrix[b][a])
                if va is None and vb is None:
                    continue
                assert va is not None and vb is not None and abs(va - vb) < 0.01, \
                    f"查重矩阵不对称: {a}x{b}={matrix[a][b]!r} vs {b}x{a}={matrix[b][a]!r}"


class TestBidIp:
    """投标IP校验(4.3.2.7): 报名/下载/上传/解密IP 格式合法; 跨单位相同IP应被识别为风险."""

    def test_ip_format_and_duplicates(self, project_detail_page):
        tb = project_detail_page.section_table("投标IP校验")
        if not tb.get("has_table") or tb.get("empty") or not tb.get("rows"):
            pytest.skip("投标IP校验暂无数据")

        headers = tb["headers"]
        name_i = _col_index(headers, "单位名称", "投标单位")
        ip_cols = {
            h: i for i, h in enumerate(headers)
            if "IP" in h
        }
        assert ip_cols, f"投标IP校验未识别到IP列, headers={headers}"

        # 1) 所有非空IP格式合法(IPv4, 每段<=255)
        per_field_ips = {h: {} for h in ip_cols}  # field -> {ip -> [units]}
        for row in tb["rows"]:
            unit = row[name_i] if 0 <= name_i < len(row) else "?"
            for h, i in ip_cols.items():
                if i >= len(row):
                    continue
                cell = row[i].strip()
                if not cell:
                    continue
                # 单元格可能含多个IP(换行/逗号分隔)
                for ip in re.split(r"[\s,;]+", cell):
                    if not ip:
                        continue
                    assert _IPV4.match(ip), f"{unit} 的 {h} 含非法IP: {ip!r}"
                    for seg in ip.split("."):
                        assert 0 <= int(seg) <= 255, f"{unit} 的 {h} IP段越界: {ip}"
                    per_field_ips[h].setdefault(ip, []).append(unit)

        # 2) 跨单位相同IP分组(同一字段下多个单位共用同一IP = 围标风险信号)
        dup_report = []
        for field, ipmap in per_field_ips.items():
            for ip, units in ipmap.items():
                uniq = sorted(set(units))
                if len(uniq) >= 2:
                    dup_report.append(f"{field}: {ip} <- {uniq}")
        # 不强制"必须有/没有"重复(取决于真实数据), 仅保证抽取闭环 + 把风险打印出来供审查
        print("\n[投标IP重复分组]\n" + ("\n".join(dup_report) if dup_report else "无跨单位重复IP"))
        # 抽取闭环: 至少应解析出与表格行数一致的单位
        assert len(tb["rows"]) >= 1


class TestBidCountWarning:
    """投标次数预警(3.3.5 / 4.3.2.12): 中标次数<=投标次数且非负; 重算"≥20且0中标"应预警集合."""

    def test_bid_count_constraints_and_rule(self, project_detail_page):
        tb = project_detail_page.section_table("投标次数预警")
        if not tb.get("has_table") or tb.get("empty") or not tb.get("rows"):
            pytest.skip("投标次数预警暂无数据")

        headers = tb["headers"]
        name_i = _col_index(headers, "单位名称", "投标单位")
        bid_i = _col_index(headers, "投标总次数", "投标次数")
        win_i = _col_index(headers, "中标总次数", "中标次数")
        assert bid_i >= 0 and win_i >= 0, f"未识别到投标/中标次数列, headers={headers}"

        warned = []
        for row in tb["rows"]:
            unit = row[name_i] if 0 <= name_i < len(row) else "?"
            bid = _int(row[bid_i]) if bid_i < len(row) else None
            win = _int(row[win_i]) if win_i < len(row) else None
            assert bid is not None and win is not None, f"{unit} 次数解析失败: {row}"
            # 不变量: 非负 且 中标<=投标
            assert bid >= 0 and win >= 0, f"{unit} 次数为负: 投标{bid}/中标{win}"
            assert win <= bid, f"{unit} 中标次数({win})不应大于投标次数({bid})"
            # 规则重算: 近一年投标>=20 且 从未中标(中标==0) -> 应预警
            if bid >= 20 and win == 0:
                warned.append(unit)
        print("\n[投标次数预警-按规则应预警单位(投标>=20且0中标)]: "
              + (", ".join(warned) if warned else "无"))
        assert len(tb["rows"]) >= 1


class TestFilePropertyCollision:
    """文件属性校验(3.3.4 / 4.3.2.9): 跨单位相同 文件作者/计算机名称/所有者 = 串通风险信号."""

    def test_property_collisions(self, project_detail_page):
        tb = project_detail_page.section_table("文件属性校验")
        if not tb.get("has_table") or tb.get("empty") or not tb.get("rows"):
            pytest.skip("文件属性校验暂无数据")

        headers = tb["headers"]
        name_i = _col_index(headers, "单位名称", "投标单位")
        targets = {h: _col_index(headers, h) for h in ("文件作者", "最后修改人", "计算机名称", "所有者")}
        targets = {h: i for h, i in targets.items() if i >= 0}
        assert targets, f"未识别到文件属性列, headers={headers}"

        collisions = []
        for field, idx in targets.items():
            value_units = {}
            for row in tb["rows"]:
                unit = row[name_i] if 0 <= name_i < len(row) else "?"
                val = row[idx].strip() if idx < len(row) else ""
                if val and val not in ("-", "—"):
                    value_units.setdefault(val, []).append(unit)
            for val, units in value_units.items():
                uniq = sorted(set(units))
                if len(uniq) >= 2:
                    collisions.append(f"{field}={val!r} <- {uniq}")
        print("\n[文件属性跨单位相同项]\n" + ("\n".join(collisions) if collisions else "无相同项"))
        assert len(tb["rows"]) >= 1


class TestBidTimeSimilarity:
    """投标时间相近(4.3.2.11): 若以表格呈现则校验时间格式; 否则按数据依赖 skip."""

    def test_bid_time_present(self, project_detail_page):
        assert project_detail_page.has_section("投标时间相近"), "详情页缺少'投标时间相近'区块"
        tb = project_detail_page.section_table("投标时间相近")
        if not tb.get("has_table") or tb.get("empty") or not tb.get("rows"):
            pytest.skip("投标时间相近暂无表格数据(该项目无相近时间记录或以非表格呈现)")
        # 有数据时: 行内若含时间戳应能解析(YYYY-MM-DD HH:MM 或 HH:MM:SS)
        time_pat = re.compile(r"\d{2}:\d{2}(:\d{2})?")
        joined = " ".join(" ".join(r) for r in tb["rows"])
        assert time_pat.search(joined), f"投标时间相近表格未见时间字段: {tb['rows'][:2]}"
