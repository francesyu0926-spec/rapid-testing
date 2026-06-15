# -*- coding: utf-8 -*-
"""抓取快检详情页结果 -> 产出 ai_report.json（供 diff_report.py 做盲测比对）。

流程：进快检列表 -> 轮询目标项目状态至"已完成" -> 进详情 -> 按 8 个审查区块
抓表格行 -> 按投标人单位名把命中行归位到各家 -> 写 ai_report.json + 原始 qc_raw.json。

用法：
  python scrape_quickcheck.py                       # 抓 GT 三个项目
  python scrape_quickcheck.py --wait 1200           # 最长等 20 分钟到已完成
  python scrape_quickcheck.py --projects P2-AIATTACK
"""
import argparse
import functools
import json
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pages.project_page import ProjectPage
from pages.project_detail_page import ProjectDetailPage
from batch_create_execute import make_driver, inject_auth, BASE, AUTH

TERMINAL = ("已完成", "校验异常", "检测异常", "已结束", "校验失败", "失败", "异常")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}")


def core_name(unit):
    """单位名去掉常见后缀，得到便于匹配的核心串。"""
    s = re.sub(r"\s", "", unit)
    for suf in ("建设工程有限公司", "建设有限公司", "工程有限公司", "有限公司", "公司"):
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def scrape_project(page: ProjectPage, detail: ProjectDetailPage, gt_proj):
    name = gt_proj["name"]
    units = [fr["unit"] for fr in gt_proj["files"] if fr.get("format") == "pdf"]
    if not page.enter_quick_check_detail_by_name(name, timeout=15):
        return None, f"无法进入详情: {name}"
    detail.wait_loaded(timeout=20)
    detail.wait_content(markers=("本页目录",) + ProjectDetailPage.QUICK_CHECK_SECTIONS,
                        timeout=25)
    blob = page.quick_check_detail_blob(settle=4)

    raw = {"name": name, "url": page.current_url(), "sections": {}}
    # 每家单位归集命中文本
    unit_text = {u: [] for u in units}
    cores = {u: core_name(u) for u in units}

    for sec in ProjectDetailPage.QUICK_CHECK_SECTIONS:
        tb = detail.section_table(sec)
        rows = []
        for row in tb.get("rows", []):
            rows.append(row)
        raw["sections"][sec] = {"found": tb.get("found"),
                                "empty": tb.get("empty"),
                                "headers": tb.get("headers"), "rows": rows}
        # 把含某家单位名的行，文本归到该家
        for row in rows:
            rtext = " ".join(str(c) for c in row)
            for u in units:
                if cores[u] and cores[u] in rtext.replace(" ", ""):
                    unit_text[u].append(f"[{sec}] {rtext}")

    files = []
    for u in units:
        # 该家文本 = 命中的各区块行；再兜底附上全文(用于关键词命中，不影响误报判定)
        txt = "\n".join(unit_text[u])
        files.append({"unit": u, "verdict": "",
                      "matched_codes": [],
                      "text": txt, "items": [],
                      "_full_blob_contains_unit": bool(cores[u] and cores[u] in blob.replace(" ", ""))})
    return {"id": gt_proj["id"], "name": name, "files": files,
            "_blob_len": len(blob)}, raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default="gt_out/ground_truth.json")
    ap.add_argument("--projects", default="")
    ap.add_argument("--out", default="ai_report.json")
    ap.add_argument("--raw", default="qc_raw.json")
    ap.add_argument("--wait", type=int, default=900, help="等待已完成的最长秒数")
    args = ap.parse_args()

    gt = json.load(open(args.gt, encoding="utf-8"))
    want = [s.strip() for s in args.projects.split(",") if s.strip()]
    targets = [p for p in gt["projects"]
               if p["id"] != "STRESS" and (not want or p["id"] in want)]
    names = {p["name"]: p["id"] for p in targets}

    state = json.loads(Path(AUTH).read_text(encoding="utf-8"))
    d = make_driver()
    report = {"projects": []}
    raws = {}
    try:
        inject_auth(d, state)
        page = ProjectPage(d, BASE)
        detail = ProjectDetailPage(d, BASE)

        # 1) 轮询到全部目标项目终态
        deadline = time.time() + args.wait
        done = set()
        while time.time() < deadline:
            page.ensure_quick_check_loaded(attempts=2, timeout=15)
            rows = page.qc_list_rows()
            cur = {}
            for r in rows:
                rn = re.sub(r"\s", "", r.get("name", ""))
                for nm, pid in names.items():
                    if re.sub(r"\s", "", nm)[:20] in rn:
                        cur[pid] = r.get("status", "")
            log(f"状态: {cur}")
            done = {pid for pid, st in cur.items()
                    if any(t in st for t in TERMINAL)}
            if len(done) >= len(targets):
                break
            time.sleep(20)

        # 2) 逐项目抓取
        for p in targets:
            if p["id"] not in done:
                log(f"[{p['id']}] 未达终态，仍尝试抓取当前内容")
            page.ensure_quick_check_loaded(attempts=2, timeout=15)
            try:
                rep, raw = scrape_project(page, detail, p)
            except Exception as e:
                rep, raw = None, f"异常 {type(e).__name__}: {e}"
            if rep:
                report["projects"].append(rep)
                raws[p["id"]] = raw
                nfound = sum(1 for f in rep["files"] if f["text"])
                log(f"[{p['id']}] 抓取完成：{len(rep['files'])}家，"
                    f"{nfound}家命中检出文本")
            else:
                log(f"[{p['id']}] 抓取失败：{raw}")
    finally:
        d.quit()

    json.dump(report, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    json.dump(raws, open(args.raw, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\nAI报告: {args.out}\n原始抓取: {args.raw}")


if __name__ == "__main__":
    main()
