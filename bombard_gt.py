# -*- coding: utf-8 -*-
"""把黄金标准数据集(gt_out/ground_truth.json)的各快检项目提交到线上平台：
新建快检项目 -> 上传招标+各家投标(PDF) -> 点执行 -> 轮询状态。

非 PDF(docx/zip)与 STRESS 组默认跳过(快检投标上传通常只收 PDF)；用 --include-nonpdf 强试。

用法：
  python bombard_gt.py                       # 提交 P1/P2/P3, 执行并轮询
  python bombard_gt.py --projects P1-COMPLIANCE
  python bombard_gt.py --no-execute          # 只创建不执行
"""
import argparse
import functools
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pages.project_page import ProjectPage
from batch_create_execute import make_driver, inject_auth, BASE, AUTH
from bombard_quickcheck import create_one, find_row, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default="gt_out/ground_truth.json")
    ap.add_argument("--projects", default="", help="逗号分隔的项目ID, 默认全部(除STRESS)")
    ap.add_argument("--upload-timeout", type=int, default=240)
    ap.add_argument("--no-execute", action="store_true")
    ap.add_argument("--include-nonpdf", action="store_true")
    ap.add_argument("--poll", type=int, default=240)
    args = ap.parse_args()

    gt = json.load(open(args.gt, encoding="utf-8"))
    want = [s.strip() for s in args.projects.split(",") if s.strip()]
    projs = []
    for p in gt["projects"]:
        if p["id"] == "STRESS":
            continue
        if want and p["id"] not in want:
            continue
        tender = p.get("tender")
        bidders = []
        for fr in p["files"]:
            if fr.get("format") != "pdf" and not args.include_nonpdf:
                continue
            bidders.append((fr["unit"], fr["file"]))
        if tender and bidders:
            projs.append((p["id"], p["name"], tender, bidders))

    for pid, name, tender, bidders in projs:
        log(f"待提交 [{pid}] {name}  招标=1 投标={len(bidders)}家")

    state = json.loads(Path(AUTH).read_text(encoding="utf-8"))
    d = make_driver()
    results = {}
    try:
        inject_auth(d, state)
        page = ProjectPage(d, BASE)
        for pid, name, tender, bidders in projs:
            log(f"=== 提交 [{pid}] {name} ===")
            try:
                r = create_one(page, name, tender, bidders,
                               args.upload_timeout, not args.no_execute)
            except Exception as e:
                r = f"异常({type(e).__name__}: {e})"
                try:
                    page.cancel_modal()
                except Exception:
                    pass
            results[pid] = r
            log(f"  -> {r}")

        if args.poll > 0:
            log(f"轮询状态({args.poll}s)...")
            end = time.time() + args.poll
            while time.time() < end:
                page.ensure_quick_check_loaded(attempts=2, timeout=15)
                snap = {}
                for pid, name, _, _ in projs:
                    row = find_row(page, name)
                    snap[pid] = ((row or {}).get("任务状态")
                                 or (row or {}).get("状态") or "?")
                log(f"  状态: {snap}")
                time.sleep(20)
    finally:
        d.quit()

    print("\n" + "=" * 60)
    print("GT 数据集提交结果：")
    ok = 0
    for pid, name, _, _ in projs:
        r = results.get(pid, "?")
        if r.startswith("成功"):
            ok += 1
        print(f"  [{pid}] {r}")
    print(f"\n成功 {ok}/{len(projs)}")


if __name__ == "__main__":
    main()
