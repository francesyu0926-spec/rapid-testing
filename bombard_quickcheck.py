# -*- coding: utf-8 -*-
"""快检项目「瑕疵标书轰炸」runner：把 defect_bids.py 生成的多场景瑕疵标书，
逐场景在线上平台新建快检项目 -> 上传招标+N家投标 -> 点击执行，最后轮询任务状态汇总。

每个场景对应一个快检项目（含一类特定瑕疵），用于压测平台对应检测项。

用法：
  python bombard_quickcheck.py                       # 全场景, 每场景8家, 生成并提交执行
  python bombard_quickcheck.py --bidders 10
  python bombard_quickcheck.py --scenarios dup,price
  python bombard_quickcheck.py --no-regen            # 复用已生成的 defect_out
  python bombard_quickcheck.py --no-execute          # 只创建不点执行
"""
import argparse
import functools
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pages.project_page import ProjectPage
import defect_bids
from batch_create_execute import make_driver, inject_auth, BASE, AUTH

import json


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def create_one(page: ProjectPage, name, tender, bidders, upload_timeout, execute):
    if not page.ensure_quick_check_loaded(attempts=4, timeout=25):
        return "失败(快检列表未加载)"
    if not page.open_new_project_modal(timeout=15):
        return "失败(未打开新建抽屉)"

    def _cb(done, total, percents):
        log(f"    上传 {done}/{total} 完成 percents={percents}")

    log(f"    逐个上传：招标 + {len(bidders)} 家投标 ...")
    ok = page.fill_and_upload_sequential(
        name, tender, bidders, record_pdf=None,
        per_file_timeout=upload_timeout, progress_cb=_cb)
    if not ok:
        page.cancel_modal()
        return f"失败(上传超时/异常 进度={page.upload_percents()})"
    if not page.submit_new_project():
        page.cancel_modal()
        return "失败(无提交按钮)"
    end = time.time() + 120
    while time.time() < end and page.new_project_form_open():
        time.sleep(2)
    if page.new_project_form_open():
        page.cancel_modal()
        return "失败(提交后抽屉未关闭)"
    if not execute:
        return "成功(已创建, 未点执行)"
    page.ensure_quick_check_loaded(attempts=3, timeout=20)
    if page.click_execute(name, timeout=25):
        return "成功(已创建+已点执行)"
    return "部分(已创建, 未点到执行)"


def find_row(page: ProjectPage, name):
    key = "".join(name.split())[:16]
    for r in page.table_rows_as_dicts():
        joined = "".join("".join(str(v).split()) for v in r.values())
        if key and key in joined:
            return r
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="defect_out")
    ap.add_argument("--bidders", type=int, default=8)
    ap.add_argument("--scenarios", default="")
    ap.add_argument("--upload-timeout", type=int, default=180)
    ap.add_argument("--no-regen", action="store_true", help="复用已生成的PDF")
    ap.add_argument("--no-execute", action="store_true", help="只创建不点执行")
    ap.add_argument("--poll", type=int, default=180, help="结束后轮询状态总秒数")
    args = ap.parse_args()

    out_dir = str(Path(args.out).resolve())
    kinds = ([s.strip() for s in args.scenarios.split(",") if s.strip()]
             or defect_bids.ALL_SCENARIOS)

    # 1) 生成/复用瑕疵标书
    scenarios = {}  # kind -> (name, tender, bidders)
    for kind in kinds:
        if args.no_regen:
            sdir = Path(out_dir) / kind
            tender = str(sdir / "招标文件.pdf")
            bids = []
            for d in sorted(sdir.glob("*的投标文件")):
                unit = d.name[:-len("的投标文件")]
                p = d / f"{unit}投标文件.pdf"
                if p.exists():
                    bids.append((unit, str(p)))
            # 项目名复用生成器里的定义
            proj_name = {
                "dup": "AUTO-DUP 投标文件查重轰炸测试项目（施工）",
                "person": "AUTO-PERSON 人员雷同轰炸测试项目（施工）",
                "meta": "AUTO-META 文件属性雷同轰炸测试项目（施工）",
                "price": "AUTO-PRICE 报价规律轰炸测试项目（施工）",
                "check": "AUTO-CHECK 投标文件校验轰炸测试项目（施工）",
            }[kind]
            scenarios[kind] = (proj_name, tender, bids)
        else:
            scenarios[kind] = defect_bids.gen_scenario(kind, out_dir, args.bidders)
        nm, td, bd = scenarios[kind]
        log(f"场景 {kind}: {nm}  招标=1 投标={len(bd)}家")

    # 2) 起浏览器、注入登录态、逐场景提交
    state = json.loads(Path(AUTH).read_text(encoding="utf-8"))
    d = make_driver()
    results = {}
    try:
        inject_auth(d, state)
        page = ProjectPage(d, BASE)
        for kind in kinds:
            name, tender, bidders = scenarios[kind]
            log(f"=== 轰炸场景 [{kind}] {name} ===")
            try:
                r = create_one(page, name, tender, bidders,
                               args.upload_timeout, not args.no_execute)
            except Exception as e:
                r = f"异常({type(e).__name__}: {e})"
                try:
                    page.cancel_modal()
                except Exception:
                    pass
            results[kind] = r
            log(f"  -> {r}")

        # 3) 轮询状态
        if args.poll > 0:
            log(f"轮询快检列表状态（{args.poll}s）...")
            end = time.time() + args.poll
            while time.time() < end:
                page.ensure_quick_check_loaded(attempts=2, timeout=15)
                snap = {}
                for kind in kinds:
                    nm = scenarios[kind][0]
                    row = find_row(page, nm)
                    snap[kind] = (row or {}).get("任务状态") or (row or {}).get("状态") or "?"
                log(f"  状态: {snap}")
                if all(v in ("已完成", "校验异常", "?") for v in snap.values()):
                    pass
                time.sleep(20)
    finally:
        d.quit()

    print("\n" + "=" * 64)
    print("瑕疵标书轰炸结果汇总：")
    desc = {
        "dup": "投标文件查重/相同投标(3.3.1/3.3.6)",
        "person": "人员雷同筛查(3.3.2)",
        "meta": "文件属性校验(3.3.4)",
        "price": "报价规律校验(3.3.10)",
        "check": "投标文件校验(3.2.6)",
    }
    ok = 0
    for kind in kinds:
        r = results.get(kind, "?")
        if r.startswith("成功"):
            ok += 1
        print(f"  [{kind}] {desc.get(kind,'')}: {r}")
    print(f"\n成功创建 {ok}/{len(kinds)} 个轰炸场景。")


if __name__ == "__main__":
    main()
