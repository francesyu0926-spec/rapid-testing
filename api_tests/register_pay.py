# -*- coding: utf-8 -*-
"""对【已创建】的项目跑后续流程：投标人报名 -> (免审核) -> 补单缴费。

不重新发布项目（招标文件上传慢），只针对已有 project_id 跑报名+补单。

用法：
  python register_pay.py                      # 演练：列出最新项目+打印将要做的事，不写入
  python register_pay.py --latest 2           # 取最新 2 个项目
  python register_pay.py --ids 2050,2051      # 指定 project_id
  python register_pay.py --latest 2 --allow-writes   # 真实报名+补单
"""

import sys, argparse, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml

from client import log
from flow import TenderSimulator
from admin_client import AdminClient
from run import build_client


def newest_project_ids(manager, n):
    res = manager.publicity_my_projects(page=1, limit=max(n, 10))
    rows = TenderSimulator._rows(res)
    out = []
    for r in rows:
        pid = r.get("project_id") or r.get("id")
        title = r.get("title") or r.get("name") or ""
        if pid:
            out.append((pid, title))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--ids", default="", help="指定 project_id（逗号分隔）")
    ap.add_argument("--latest", type=int, default=2, help="取最新 N 个项目（未指定 --ids 时）")
    ap.add_argument("--allow-writes", action="store_true", help="真实报名+补单")
    args = ap.parse_args()

    cfg = yaml.safe_load(open(args.config, encoding="utf-8")) or {}
    base_url = cfg["base_url"].rstrip("/")
    api_prefix = cfg.get("api_prefix", "/api")
    opts = cfg.get("options", {})
    if args.allow_writes:
        opts["allow_writes"] = True
    cfg["options"] = opts
    dry_run = not bool(opts.get("allow_writes", False))
    if dry_run:
        log("【演练模式】写操作只打印不发送；确认后加 --allow-writes 真实执行。")

    adm = cfg.get("admin") or {}
    admin = AdminClient(base_url, adm.get("prefix", ""), adm.get("php_session", ""),
                        timeout=opts.get("timeout", 30), verify_ssl=opts.get("verify_ssl", True),
                        username=adm.get("username", ""), password=adm.get("password", ""))

    accounts = cfg.get("accounts", {})
    manager = build_client(accounts.get("manager"), base_url, api_prefix, opts,
                           "项目经理", dry_run, admin)
    if manager is None:
        log("项目经理登录失败，无法继续。"); sys.exit(1)
    bidders = []
    for i, acct in enumerate(accounts.get("bidders") or [], 1):
        api = build_client(acct, base_url, api_prefix, opts,
                           acct.get("name") or f"投标人{i}", dry_run, admin)
        if api:
            bidders.append(api)
    log(f"角色就绪：项目经理 OK  投标人×{len(bidders)}")

    # 解析目标项目
    if args.ids.strip():
        target_ids = [int(x) for x in args.ids.split(",") if x.strip()]
        targets = [(pid, "") for pid in target_ids]
    else:
        listed = newest_project_ids(manager, args.latest)
        log("项目经理最新项目：")
        for pid, title in listed:
            log(f"  project_id={pid}  {title}", indent=1)
        targets = listed[:args.latest]
    if not targets:
        log("未找到目标项目。"); return

    sim = TenderSimulator(manager, None, bidders, [], cfg)
    for pid, title in targets:
        log("=" * 64)
        log(f"项目 project_id={pid} {title}")
        log("=" * 64)
        # 重置上下文
        sim.ctx = {"project_id": pid, "section_id": None, "registers": {},
                   "tender_files": {}, "leader_uid": None}
        info = manager.publicity_project_info(pid)
        sid = sim._first_section_id(info)
        sim.ctx["section_id"] = sid or 0
        log(f"section_id={sim.ctx['section_id']}", indent=1)
        sim.step_bidders_register()
        sim.step_manager_audit_register()
        sim.step_bidders_pay()
    sim._summary()


if __name__ == "__main__":
    main()
