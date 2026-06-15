# -*- coding: utf-8 -*-
"""盲测 Diff：把快检 AI 的审查报告与 Ground Truth 预期矩阵逐项比对，
算 漏报率(AI 没发现)与 误报率(无问题硬说有问题)。

AI 报告 ai_report.json 的规范（由线上抓取脚本产出，或人工整理）：
{
  "projects": [
    {"id": "P1-COMPLIANCE",
     "files": [
        {"unit": "资质硬伤丙建设有限公司",
         "verdict": "废标",                       # 可选：AI 给的总结论
         "matched_codes": ["QUAL-EXPIRED"],       # 可选：若抓取脚本已能对齐编号
         "text": "……AI 报告全文/要点拼接……",     # 推荐：用于关键词匹配
         "items": [{"category":"资质","desc":"安全生产许可证过期","severity":"废标"}]
        }, ...
     ]}
  ]
}

匹配优先级：matched_codes > items/text 关键词命中。

用法：
  python diff_report.py --make-template            # 按 GT 产出空模板 ai_report.template.json
  python diff_report.py --gt gt_out/ground_truth.json --ai ai_report.json
"""
import argparse
import functools
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)

# 每个雷点编号 -> 命中关键词（AI 报告文本含任一即视为"检出"）
KEYWORDS = {
    "QUAL-EXPIRED": ["安全生产许可证", "过期", "失效", "有效期"],
    "QUAL-MISSING": ["系统集成", "缺少", "缺失", "资质证书"],
    "QUAL-SCOPE": ["经营范围", "不符", "范围"],
    "FIN-LOSS": ["亏损", "净利润", "连续三年"],
    "FIN-REV": ["营业额", "营业收入", "不达标", "低于"],
    "PERF-PMYEARS": ["项目经理", "年限", "从业", "不足"],
    "BIZ-PRICE-WORD": ["大写", "小写", "金额", "不一致"],
    "BIZ-SUBTOTAL": ["总价", "分项", "合计", "不等于"],
    "BIZ-NODEPOSIT": ["保证金"],
    "BIZ-NOSIGN": ["签字", "法定代表人", "未签"],
    "BIZ-NOSEAL": ["公章", "盖章", "未盖章"],
    "BIZ-NOLETTER": ["投标函"],
    "BIZ-NOPRICETBL": ["报价表"],
    "RESP-PARAM": ["技术参数", "公称压力", "未响应", "偏离"],
    "RESP-DELIVERY": ["交货期", "工期"],
    "RESP-WARRANTY": ["质保", "售后", "保修"],
    "ATK-NEEDLE": ["罚款", "违约", "不接受", "偏离"],
    "ATK-INJECT": ["注入", "忽略", "提示词", "越狱", "直接通过"],
    "ATK-IMG": ["图片", "扫描", "OCR", "影像"],
    "ATK-TINY": ["小字", "字号", "字体过小"],
    "ATK-TRAD": ["繁体"],
    "ATK-2COL": ["双栏", "分栏", "排版"],
    "ATK-WM": ["水印"],
    "ATK-ENCRYPT": ["加密", "口令", "密码", "无法解析"],
    "COL-DUP": ["雷同", "查重", "相同", "重复", "相似"],
    "COL-TYPO": ["错别字", "雷同", "相同错"],
    "COL-META": ["作者", "最后修改", "文件属性", "修改人"],
    "COL-PERSON": ["联系人", "电话", "人员", "雷同"],
    "NEG-JV": ["联合体", "协议"],
    "NEG-RELATED": ["关联", "股权", "高管", "回避"],
}


def detected(finding, ai_file):
    """判断某个 GT 雷点是否被 AI 报告检出（关键词法，仅在无 raw 证据时回退）。"""
    code = finding["code"]
    if code in (ai_file.get("matched_codes") or []):
        return True
    hay = ai_file.get("text", "") or ""
    for it in ai_file.get("items", []) or []:
        hay += " " + str(it.get("desc", "")) + " " + str(it.get("category", ""))
    kws = KEYWORDS.get(code, [])
    return any(k in hay for k in kws)


# 按"实际表格证据"判定是否检出（比关键词法准确，避免命中区块标题而误判为检出）
_PERBID = {  # 这些雷点应体现在"投标文件校验"的 AI评审结果(合格=未检出)
    "QUAL-EXPIRED", "QUAL-MISSING", "QUAL-SCOPE", "FIN-LOSS", "FIN-REV",
    "PERF-PMYEARS", "BIZ-PRICE-WORD", "BIZ-SUBTOTAL", "BIZ-NODEPOSIT",
    "BIZ-NOSIGN", "BIZ-NOSEAL", "BIZ-NOLETTER", "BIZ-NOPRICETBL",
    "RESP-PARAM", "RESP-DELIVERY", "RESP-WARRANTY", "ATK-NEEDLE",
    "ATK-INJECT", "ATK-IMG", "ATK-TINY", "ATK-TRAD", "ATK-2COL", "ATK-WM",
    "NEG-JV", "NEG-RELATED",
}
_OK_VERDICTS = ("合格", "通过", "符合", "-", "")


def _core(unit):
    s = re.sub(r"\s", "", unit)
    for suf in ("建设工程有限公司", "建设有限公司", "工程有限公司", "有限公司", "公司"):
        if s.endswith(suf):
            return s[:-len(suf)]
    return s


def _rows(raw_proj, sec):
    s = (raw_proj or {}).get("sections", {}).get(sec, {})
    return s.get("rows") or [], s.get("headers") or []


def _validation_for(raw_proj, unit):
    """返回该单位在'投标文件校验'里的 (文件状态, AI识别状态, AI评审结果)。"""
    core = _core(unit)
    rows, _ = _rows(raw_proj, "投标文件校验")
    for r in rows:
        if core and core in "".join(str(c) for c in r).replace(" ", ""):
            # [序号,投标单位,投标文件状态,AI识别状态,AI评审结果,操作,'']
            return (r[2] if len(r) > 2 else "", r[3] if len(r) > 3 else "",
                    r[4] if len(r) > 4 else "")
    return ("", "", "")


def _dup_hit(raw_proj, unit):
    core = _core(unit)
    rows, _ = _rows(raw_proj, "投标文件查重")
    for r in rows:
        if not r:
            continue
        if core and core in str(r[0]).replace(" ", ""):
            for cell in r[1:]:
                m = re.match(r"^\s*([0-9.]+)\s*%", str(cell))
                if m and float(m.group(1)) > 0:
                    return True
    # 相同投标预警非空且含本单位
    rows2, _ = _rows(raw_proj, "相同投标预警")
    for r in rows2:
        if core and core in "".join(str(c) for c in r).replace(" ", ""):
            return True
    return False


def _section_has_unit(raw_proj, sec, unit):
    core = _core(unit)
    rows, _ = _rows(raw_proj, sec)
    for r in rows:
        if core and core in "".join(str(c) for c in r).replace(" ", ""):
            return True
    return False


def detected_evidence(finding, raw_proj, unit):
    """基于真实表格证据判定检出（有 qc_raw 时优先用此法）。"""
    code = finding["code"]
    fstat, aistat, verdict = _validation_for(raw_proj, unit)
    if code == "ATK-ENCRYPT":
        blob = f"{fstat}{aistat}{verdict}"
        return ("失败" in blob) or ("异常" in blob) or ("无法" in blob)
    if code in ("COL-DUP", "COL-TYPO"):
        return _dup_hit(raw_proj, unit)
    if code == "COL-META":
        return _section_has_unit(raw_proj, "文件属性校验", unit)
    if code == "COL-PERSON":
        return False  # 快检无"人员雷同筛查"区块
    if code in _PERBID:
        # 体现在投标文件校验结论：非"合格"才算检出该问题
        return verdict not in _OK_VERDICTS
    return False


def make_template(gt, out_path):
    tpl = {"projects": []}
    for p in gt["projects"]:
        tpl["projects"].append({
            "id": p["id"],
            "files": [{"unit": fr["unit"], "verdict": "", "matched_codes": [],
                       "text": "", "items": []} for fr in p["files"]],
        })
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(tpl, f, ensure_ascii=False, indent=2)
    print(f"已写出模板: {out_path}（填入线上 AI 报告文本/要点后再跑比对）")


def index_ai(ai):
    idx = {}
    for p in ai.get("projects", []):
        for fr in p.get("files", []):
            idx[(p.get("id"), fr.get("unit"))] = fr
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default="gt_out/ground_truth.json")
    ap.add_argument("--ai", default="ai_report.json")
    ap.add_argument("--raw", default="qc_raw.json",
                    help="结构化抓取(优先按表格证据判定检出)")
    ap.add_argument("--out", default="diff_report.md")
    ap.add_argument("--make-template", action="store_true")
    args = ap.parse_args()

    gt = json.load(open(args.gt, encoding="utf-8"))
    if args.make_template:
        make_template(gt, "ai_report.template.json")
        return

    if not os.path.exists(args.ai):
        print(f"未找到 AI 报告 {args.ai}。先 --make-template 生成模板，"
              f"或运行线上抓取脚本产出。")
        return
    ai = json.load(open(args.ai, encoding="utf-8"))
    ai_idx = index_ai(ai)
    raw = {}
    use_evidence = os.path.exists(args.raw)
    if use_evidence:
        raw = json.load(open(args.raw, encoding="utf-8"))
        print(f"(采用结构化表格证据判定检出: {args.raw})")

    rows = []
    n_expected = n_hit = n_miss = 0
    n_false = n_ai_items = 0
    for p in gt["projects"]:
        # 仅评估实际提交并抓取到结果的项目(避免把未上线的 STRESS 组计入漏报)
        if use_evidence and p["id"] not in raw:
            continue
        raw_proj = raw.get(p["id"]) if use_evidence else None
        for fr in p["files"]:
            key = (p["id"], fr["unit"])
            aif = ai_idx.get(key, {})
            n_ai_items += len(aif.get("items", []) or []) or (
                1 if aif.get("text") else 0)
            # 漏报：仅统计应被检出的雷点
            for fd in fr["findings"]:
                if not fd.get("expect_detect", True):
                    continue
                n_expected += 1
                ok = (detected_evidence(fd, raw_proj, fr["unit"])
                      if use_evidence else detected(fd, aif))
                if ok:
                    n_hit += 1
                else:
                    n_miss += 1
                    rows.append((p["id"], fr["unit"], fd["code"], fd["severity"],
                                 fd["desc"], "漏报"))
            # 误报：完全合格件却报出问题
            if not fr["findings"] and (aif.get("items") or aif.get("matched_codes")):
                n_false += 1
                rows.append((p["id"], fr["unit"], "-", "-",
                             "合格件被报出异常", "误报"))

    miss_rate = n_miss / n_expected if n_expected else 0
    print("=" * 60)
    print("盲测 Diff 结果：")
    print(f"  应检出雷点(可检测)：{n_expected}")
    print(f"  命中：{n_hit}　漏报：{n_miss}　漏报率：{miss_rate:.1%}")
    print(f"  合格件误报：{n_false}　AI报告条目计：{n_ai_items}")

    lines = ["# 快检 AI 盲测 Diff 报告", "",
             f"- 应检出雷点（可检测）：**{n_expected}**",
             f"- 命中：**{n_hit}**，漏报：**{n_miss}**，漏报率：**{miss_rate:.1%}**",
             f"- 合格件误报：**{n_false}**", "",
             "## 漏报 / 误报明细", "",
             "| 项目 | 文件 | 雷点编号 | 严重度 | 说明 | 类型 |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in r) + " |")
    if not rows:
        lines.append("| — | — | — | — | 全部命中且无误报 | — |")
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  明细已写出: {args.out}")


if __name__ == "__main__":
    main()
