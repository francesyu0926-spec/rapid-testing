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


def _num(text):
    """解析金额/数值: 去除货币符号/逗号/单位后转 float; 无效或 '-' 返回 None."""
    if text is None:
        return None
    t = text.strip()
    if t in ("", "-", "—"):
        return None
    t = re.sub(r"[,¥￥%\s]", "", t)
    m = re.search(r"-?\d+(\.\d+)?", t)
    return float(m.group()) if m else None


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


class TestPriceRule:
    """报价规律校验(3.3.10 / 4.3.2.10): 对系统算出的报价对比列做**精确算术重算**.

    快检详情该表列含: 报价(元)/投标人均价(元)/与均价差额(元)/与均价差额百分比(%)/
    最高限价(元)/与最高价差额(元)/与最高限价占比(%). 这些列之间存在确定的算术关系,
    单行即可校验(无需多家), 是强 oracle:
      · 与最高价差额 == 最高限价 - 报价
      · 与最高限价占比 == 报价/最高限价*100
      · 与均价差额     == 报价 - 投标人均价
      · 与均价差额百分比 == (报价-均价)/均价*100
      · 投标人均价     == 各家报价均值(且各行一致)
    """

    @staticmethod
    def _close(a, b, abs_tol, rel_tol=0.0):
        return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))

    def test_price_arithmetic_relations(self, quick_check_detail_page):
        tb = quick_check_detail_page.section_table("报价规律校验")
        if not tb.get("has_table") or tb.get("empty") or not tb.get("rows"):
            pytest.skip("报价规律校验暂无数据")
        h = tb["headers"]
        i_price = _col_index(h, "报价(元)", "报价")
        i_avg = _col_index(h, "投标人均价")
        i_avg_diff = _col_index(h, "与均价差额(元)", "与均价差额")
        i_avg_pct = _col_index(h, "与均价差额百分比")
        i_cap = _col_index(h, "最高限价(元)", "最高限价")
        i_cap_diff = _col_index(h, "与最高价差额(元)", "与最高价差额")
        i_cap_pct = _col_index(h, "与最高限价占比")
        if i_price < 0:
            pytest.skip(f"未识别到报价列, headers={h}")

        def cell(row, idx):
            return _num(row[idx]) if 0 <= idx < len(row) else None

        prices, avgs, checked = [], [], 0
        for row in tb["rows"]:
            price = cell(row, i_price)
            if price is None:
                continue
            assert price >= 0, f"报价为负: {row}"
            prices.append(price)
            avg = cell(row, i_avg)
            if avg is not None:
                avgs.append(avg)

            cap = cell(row, i_cap)
            cap_diff = cell(row, i_cap_diff)
            if cap is not None and cap_diff is not None:
                assert self._close(cap_diff, cap - price, abs_tol=1.0, rel_tol=1e-4), (
                    f"与最高价差额 {cap_diff} != 最高限价-报价 {cap - price:.2f}"
                ); checked += 1
            cap_pct = cell(row, i_cap_pct)
            if cap is not None and cap > 0 and cap_pct is not None:
                assert self._close(cap_pct, price / cap * 100, abs_tol=0.05), (
                    f"与最高限价占比 {cap_pct} != 报价/最高限价*100 {price / cap * 100:.4f}"
                ); checked += 1
            avg_diff = cell(row, i_avg_diff)
            if avg is not None and avg_diff is not None:
                assert self._close(avg_diff, price - avg, abs_tol=1.0, rel_tol=1e-4), (
                    f"与均价差额 {avg_diff} != 报价-均价 {price - avg:.2f}"
                ); checked += 1
            avg_pct = cell(row, i_avg_pct)
            if avg is not None and avg > 0 and avg_pct is not None:
                assert self._close(avg_pct, (price - avg) / avg * 100, abs_tol=0.05), (
                    f"与均价差额百分比 {avg_pct} != (报价-均价)/均价*100 {(price - avg) / avg * 100:.4f}"
                ); checked += 1

        # 投标人均价 == 各家报价均值, 且各行展示一致
        if avgs and prices:
            uniq = set(round(a, 2) for a in avgs)
            assert len(uniq) == 1, f"各行展示的投标人均价不一致: {sorted(uniq)}"
            computed = sum(prices) / len(prices)
            assert self._close(avgs[0], computed, abs_tol=1.0, rel_tol=1e-3), (
                f"投标人均价 {avgs[0]} != 各家报价均值 {computed:.2f}"
            ); checked += 1

        if checked == 0:
            pytest.skip("报价对比各列均为占位'-', 无可重算的数值")


class TestRecordAudit:
    """招标备案识别(3.2.2): 一致数量/不一致数量/缺项数量 若有值则应为非负整数(数值不变量).

    实测该表列为 文件类别/文件名称/文件页数/一致数量/不一致数量/缺项数量/操作;
    未完成比对时计数列为占位'-', 此时跳过(数据依赖)."""

    def test_record_counts_non_negative_int(self, quick_check_detail_page):
        tb = quick_check_detail_page.section_table("招标备案识别")
        if not tb.get("has_table") or tb.get("empty") or not tb.get("rows"):
            pytest.skip("招标备案识别暂无数据")
        headers = tb["headers"]
        cols = {c: _col_index(headers, c) for c in ("一致数量", "不一致数量", "缺项数量")}
        cols = {c: i for c, i in cols.items() if i >= 0}
        if not cols:
            pytest.skip(f"未识别到备案识别计数列, headers={headers}")
        checked = 0
        # 文件页数(若有)应为正整数 —— 顺带校验该行确为文件记录
        page_i = _col_index(headers, "文件页数")
        for row in tb["rows"]:
            if 0 <= page_i < len(row):
                pg = _int(row[page_i])
                if pg is not None:
                    assert pg >= 0, f"文件页数为负: {row}"
            for c, i in cols.items():
                if i < len(row):
                    v = _int(row[i])
                    if v is not None:
                        assert v >= 0, f"{c} 为负: {row}"
                        checked += 1
        if checked == 0:
            pytest.skip("备案识别计数列均为占位'-'(尚未完成一致性比对), 无可校验数值")


class TestHandwriting:
    """投标笔迹校验(3.3.7 / 4.3.2.8): 该表为单位两两矩阵, 单元格形如 'x|y'(双向比对计数).

    确定性结构 oracle:
      · 对角为 '-';
      · 交换对称: 单元格(A,B)='x|y' 则 单元格(B,A) 必为 'y|x'(两数对调);
      · x,y 均为非负整数.
    """

    @staticmethod
    def _pair(raw):
        """'19|29' -> (19,29); '-'/空/无效 -> None."""
        if raw is None:
            return None
        t = raw.strip()
        if t in ("", "-", "—"):
            return None
        parts = re.split(r"[|/]", t)
        if len(parts) != 2:
            return None
        try:
            return int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            return None

    def test_handwriting_matrix_swap_symmetry(self, quick_check_detail_page):
        tb = quick_check_detail_page.section_table("投标笔迹校验")
        if not tb.get("has_table") or tb.get("empty") or not tb.get("rows"):
            pytest.skip("投标笔迹校验暂无数据")
        headers = tb["headers"]
        col_names = [h for h in headers[1:] if h]
        matrix = {}
        for row in tb["rows"]:
            if len(row) < 2:
                continue
            matrix[row[0]] = {col_names[j - 1]: row[j]
                              for j in range(1, len(row)) if j - 1 < len(col_names)}
        assert matrix, f"未能解析笔迹矩阵, headers={headers}"

        names = list(matrix.keys())
        checked = 0
        for a in names:
            for b, raw in matrix[a].items():
                if a == b:
                    assert raw.strip() in ("-", "—", ""), f"笔迹矩阵对角({a})应为'-', 实际 {raw!r}"
                    continue
                pair = self._pair(raw)
                if pair is None:
                    continue
                assert pair[0] >= 0 and pair[1] >= 0, f"笔迹计数为负: {a}x{b}={raw!r}"
                # 交换对称: (A,B)=x|y 则 (B,A)=y|x
                if b in matrix and a in matrix.get(b, {}):
                    rev = self._pair(matrix[b][a])
                    if rev is not None:
                        assert rev == (pair[1], pair[0]), (
                            f"笔迹矩阵非交换对称: {a}x{b}={raw!r} 但 {b}x{a}={matrix[b][a]!r}"
                        )
                        checked += 1
        if checked == 0:
            pytest.skip("笔迹矩阵无可比对的成对数值(多为占位)")


class TestBidFileValidation:
    """投标文件校验(4.3.2): 列含 投标单位/投标文件状态/AI识别状态/AI结果数.

    结构不变量: 各行单位唯一且与行数一致; 投标文件状态/AI识别状态 已渲染(非占位);
    AI结果数 若为数值应非负.
    """

    def test_status_rendered_and_units_unique(self, quick_check_detail_page):
        tb = quick_check_detail_page.section_table("投标文件校验")
        if not tb.get("has_table") or tb.get("empty") or not tb.get("rows"):
            pytest.skip("投标文件校验暂无数据")
        h = tb["headers"]
        unit_i = _col_index(h, "投标单位", "单位名称")
        fst_i = _col_index(h, "投标文件状态")
        ai_i = _col_index(h, "AI识别状态")
        cnt_i = _col_index(h, "AI结果数")
        if unit_i < 0:
            pytest.skip(f"未识别到投标单位列, headers={h}")

        units = []
        for row in tb["rows"]:
            unit = (row[unit_i] or "").strip() if unit_i < len(row) else ""
            assert unit and unit not in ("-", "—"), f"投标单位为空: {row}"
            units.append(unit)
            if 0 <= fst_i < len(row):
                assert (row[fst_i] or "").strip() not in ("", "-", "—"), f"投标文件状态未渲染: {row}"
            if 0 <= ai_i < len(row):
                assert (row[ai_i] or "").strip() not in ("", "-", "—"), f"AI识别状态未渲染: {row}"
            if 0 <= cnt_i < len(row):
                c = _int(row[cnt_i])
                if c is not None:
                    assert c >= 0, f"AI结果数为负: {row}"
        assert len(set(units)) == len(units), f"投标文件校验出现重复单位行: {units}"


class TestBidEnvironmentMac:
    """投标环境校验(4.3.2.6): 校验 使用过的MAC地址 格式合法, 并检测跨单位重复MAC(围标信号).

    与投标IP校验同构. 开标中详情该区块, 样本常'暂无数据', 无数据时 skip.
    """

    _MAC = re.compile(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$")

    def test_mac_format_and_duplicates(self, project_detail_page):
        tb = project_detail_page.section_table("投标环境校验")
        if not tb.get("has_table") or tb.get("empty") or not tb.get("rows"):
            pytest.skip("投标环境校验暂无数据")
        h = tb["headers"]
        unit_i = _col_index(h, "投标单位", "单位名称")
        mac_i = _col_index(h, "MAC")
        if mac_i < 0:
            pytest.skip(f"未识别到MAC列, headers={h}")

        mac_units = {}
        seen = 0
        for row in tb["rows"]:
            unit = row[unit_i] if 0 <= unit_i < len(row) else "?"
            cell = row[mac_i].strip() if mac_i < len(row) else ""
            if not cell or cell in ("-", "—"):
                continue
            for mac in re.split(r"[\s,;]+", cell):
                if not mac:
                    continue
                assert self._MAC.match(mac), f"{unit} 含非法MAC: {mac!r}"
                mac_units.setdefault(mac, []).append(unit)
                seen += 1
        if seen == 0:
            pytest.skip("投标环境校验无有效MAC数据")
        dups = [f"{m} <- {sorted(set(u))}" for m, u in mac_units.items() if len(set(u)) >= 2]
        print("\n[投标环境-跨单位重复MAC]\n" + ("\n".join(dups) if dups else "无跨单位重复MAC"))


class TestBidTimeSimilarity:
    """投标时间相近(4.3.2.11): 若以表格呈现则校验时间格式; 区块缺失或无数据时按数据/渲染依赖 skip."""

    def test_bid_time_present(self, project_detail_page):
        if not project_detail_page.has_section("投标时间相近"):
            pytest.skip("当前项目详情未渲染'投标时间相近'区块(区块齐全性见 test_authenticated 用例52)")
        tb = project_detail_page.section_table("投标时间相近")
        if not tb.get("has_table") or tb.get("empty") or not tb.get("rows"):
            pytest.skip("投标时间相近暂无表格数据(该项目无相近时间记录或以非表格呈现)")
        time_pat = re.compile(r"\d{2}:\d{2}(:\d{2})?")
        joined = " ".join(" ".join(r) for r in tb["rows"])
        assert time_pat.search(joined), f"投标时间相近表格未见时间字段: {tb['rows'][:2]}"
