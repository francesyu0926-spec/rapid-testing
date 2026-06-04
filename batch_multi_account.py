# -*- coding: utf-8 -*-
"""多账号并发: 用 N 个账号同时创建并执行快检项目, 项目取自 D:\\文件\\测试项目资料.

- 每个账号一个独立浏览器(独立登录态), 各自串行处理"自己分到的那批项目"(避免重复创建);
- 项目按轮转(round-robin)分配给各账号, 集合互不相交;
- 单个项目内部仍是逐个文件上传(招标+前K家投标), 复用 batch_create_execute.process_one;
- 账号间真正并发(线程池), 单项目失败不影响其它.

前置: 先用不同账号分别保存登录态(各登录一次, 通过验证码):
  python save_auth_state.py --out auth_state_1.json
  python save_auth_state.py --out auth_state_2.json
  python save_auth_state.py --out auth_state_3.json
  python save_auth_state.py --out auth_state_4.json

用法:
  python batch_multi_account.py                                  # 自动发现 auth_state_*.json, 共20项目
  python batch_multi_account.py --accounts auth_state_1.json auth_state_2.json auth_state_3.json auth_state_4.json --count 20
  python batch_multi_account.py --count 20 --bidders 3 --start 0
"""
import argparse
import glob
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pages.project_page import ProjectPage
from batch_create_execute import (BASE, MAT, make_driver, inject_auth, process_one)

_print_lock = threading.Lock()


def log(tag, msg):
    with _print_lock:
        print(f"[{time.strftime('%H:%M:%S')}][{tag}] {msg}", flush=True)


def discover_accounts() -> list:
    here = Path(__file__).resolve().parent
    files = sorted(glob.glob(str(here / "auth_state_*.json")))
    # 退化: 若没有编号文件, 用单个 auth_state.json
    if not files and (here / "auth_state.json").exists():
        files = [str(here / "auth_state.json")]
    return files


def worker(acc_idx: int, acc_file: str, projs: list, bidders: int, upload_timeout: int) -> dict:
    """单账号: 建驱动+注入登录态, 串行处理分到的项目."""
    tag = f"账号{acc_idx}"
    results = {}
    try:
        state = json.loads(Path(acc_file).read_text(encoding="utf-8"))
    except Exception as e:
        log(tag, f"读取登录态失败 {acc_file}: {e}")
        return {p.name: "失败(登录态文件无法读取)" for p in projs}

    def lf(m):
        log(tag, m)

    log(tag, f"启动, 登录态={Path(acc_file).name}, 分到 {len(projs)} 个项目: "
             f"{[p.name for p in projs]}")
    d = make_driver()
    try:
        inject_auth(d, state)
        page = ProjectPage(d, BASE)
        if not page.ensure_quick_check_loaded(attempts=4, timeout=25):
            log(tag, "快检列表未加载(登录态可能失效, 请对该账号重跑 save_auth_state.py)")
            return {p.name: "失败(登录态失效/列表未加载)" for p in projs}
        for proj in projs:
            log(tag, f"=== 处理 {proj.name} ===")
            try:
                r = process_one(page, proj, bidders, upload_timeout, logf=lf)
            except Exception as e:
                r = f"异常({type(e).__name__}: {e})"
                try:
                    page.cancel_modal()
                except Exception:
                    pass
            results[proj.name] = r
            log(tag, f"-> {proj.name}: {r}")
    finally:
        try:
            d.quit()
        except Exception:
            pass
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", nargs="*", default=None,
                    help="登录态文件列表; 缺省自动发现 auth_state_*.json")
    ap.add_argument("--count", type=int, default=20, help="总项目数")
    ap.add_argument("--bidders", type=int, default=3, help="每项目前K家投标")
    ap.add_argument("--start", type=int, default=0, help="项目起始下标(0基)")
    ap.add_argument("--upload-timeout", type=int, default=900, help="单文件上传超时(秒)")
    args = ap.parse_args()

    accounts = args.accounts or discover_accounts()
    if not accounts:
        print("[错误] 未找到任何登录态文件. 请先用不同账号执行:")
        print("  python save_auth_state.py --out auth_state_1.json  (依次 _2/_3/_4)")
        return
    missing = [a for a in accounts if not Path(a).exists()]
    if missing:
        print(f"[错误] 登录态文件不存在: {missing}")
        return

    projs = sorted([p for p in MAT.iterdir() if p.is_dir()])[args.start:args.start + args.count]
    n = len(accounts)
    # 轮转分配, 各账号项目集合互不相交
    buckets = {i: [] for i in range(n)}
    for idx, proj in enumerate(projs):
        buckets[idx % n].append(proj)

    print("=" * 64, flush=True)
    print(f"多账号并发: {n} 个账号, 共 {len(projs)} 个项目, 每项目前 {args.bidders} 家投标", flush=True)
    for i, a in enumerate(accounts, start=1):
        print(f"  账号{i} <- {Path(a).name}: {len(buckets[i-1])} 个 "
              f"{[p.name for p in buckets[i-1]]}", flush=True)
    print("=" * 64, flush=True)

    all_results = {}
    with ThreadPoolExecutor(max_workers=n) as ex:
        futs = {ex.submit(worker, i + 1, accounts[i], buckets[i], args.bidders,
                          args.upload_timeout): i + 1 for i in range(n)}
        for fut in as_completed(futs):
            acc = futs[fut]
            try:
                all_results.update(fut.result())
            except Exception as e:
                log(f"账号{acc}", f"线程异常: {type(e).__name__}: {e}")

    print("\n" + "=" * 64, flush=True)
    print("并发批量结果汇总:", flush=True)
    ok = 0
    for proj in projs:
        r = all_results.get(proj.name, "未处理")
        if str(r).startswith("成功"):
            ok += 1
        print(f"  {proj.name}: {r}", flush=True)
    print(f"\n成功 {ok}/{len(projs)}", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
