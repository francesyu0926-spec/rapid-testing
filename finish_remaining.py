# -*- coding: utf-8 -*-
"""单账号串行收尾: 重建并执行未建成的项目, 并对"已建未执行"的项目补点执行.

并发批量后, 个别项目因高负载抖动未建成(未打开抽屉)或建成后未点到执行;
本脚本用单账号串行(无并发抖动)收尾, 最稳.

用法:
  python finish_remaining.py
  python finish_remaining.py --auth auth_state_1.json \
      --create 项目002-工程施建 项目006-工程施建 \
      --exec 项目014-货物采购 项目016-工程施建
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pages.project_page import ProjectPage
from batch_create_execute import (BASE, MAT, make_driver, inject_auth, resolve,
                                   extract_project_name, process_one)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def find_folder(prefix: str) -> Path | None:
    for p in sorted(MAT.iterdir()):
        if p.is_dir() and p.name == prefix:
            return p
    for p in sorted(MAT.iterdir()):
        if p.is_dir() and p.name.startswith(prefix):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth", default="auth_state_1.json")
    ap.add_argument("--bidders", type=int, default=3)
    ap.add_argument("--upload-timeout", type=int, default=900)
    ap.add_argument("--create", nargs="*",
                    default=["项目002-工程施建", "项目006-工程施建"])
    ap.add_argument("--exec", nargs="*", dest="execute",
                    default=["项目014-货物采购", "项目016-工程施建"])
    args = ap.parse_args()

    auth = Path(args.auth)
    if not auth.exists():
        print(f"[错误] 登录态文件不存在: {auth}")
        return
    state = json.loads(auth.read_text(encoding="utf-8"))

    results = {}
    d = make_driver()
    try:
        inject_auth(d, state)
        page = ProjectPage(d, BASE)
        if not page.ensure_quick_check_loaded(attempts=4, timeout=25):
            print("[错误] 快检列表未加载(登录态可能失效)")
            return

        # 1) 重建 + 执行
        for prefix in args.create:
            proj = find_folder(prefix)
            log(f"=== 重建 {prefix} ===")
            if not proj:
                results[prefix] = "失败(未找到项目文件夹)"
                log(f"-> {results[prefix]}")
                continue
            try:
                r = process_one(page, proj, args.bidders, args.upload_timeout, logf=log)
            except Exception as e:
                r = f"异常({type(e).__name__}: {e})"
                try:
                    page.cancel_modal()
                except Exception:
                    pass
            results[prefix] = r
            log(f"-> {prefix}: {r}")

        # 2) 仅补点执行(项目已建好)
        for prefix in args.execute:
            proj = find_folder(prefix)
            log(f"=== 补点执行 {prefix} ===")
            if not proj:
                results[prefix] = "失败(未找到项目文件夹)"
                log(f"-> {results[prefix]}")
                continue
            tender, _ = resolve(proj, args.bidders)
            name = extract_project_name(tender) if tender else prefix
            page.ensure_quick_check_loaded(attempts=3, timeout=20)
            ok = page.click_execute(name, timeout=25)
            results[prefix] = "成功(已点执行)" if ok else "失败(未点到执行)"
            log(f"-> {prefix}: {results[prefix]}  (匹配名: {name[:30]})")
    finally:
        try:
            d.quit()
        except Exception:
            pass

    print("\n" + "=" * 60, flush=True)
    print("收尾结果:", flush=True)
    for k, v in results.items():
        print(f"  {k}: {v}", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
