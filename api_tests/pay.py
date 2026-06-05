# -*- coding: utf-8 -*-
"""项目缴费补单工具。

链路：
  后台列项目 -> 后台列某项目报名人员(取 registerId) -> 调 /api 补单接口完成缴费

用法：
  python pay.py                              # 列出公示项目
  python pay.py -p 2010                       # 列出项目 2010 的报名人员(registerId/状态)
  python pay.py -p 2010 --pay                 # 对项目 2010 全部报名人员补单(需 --allow-writes 真实执行)
  python pay.py -r 7706 --pay                 # 仅对 registerId=7706 补单
  python pay.py -p 2010 --pay --only-unpaid   # 只对"待缴费"状态的报名补单
  python pay.py ... --allow-writes            # 真实发送补单请求(否则演练: 只打印)
"""

import argparse
import os
import sys

import yaml

from client import ApiClient, log
from admin_client import AdminClient


# 报名行字段：status_name=审核状态, pay_state_name=缴费状态
_PAY_KEYS = ("pay_state_name", "pay_state", "pay_status")
_UNPAID_HINTS = ("待缴费", "待缴", "未缴费", "未支付", "部分缴费", "未缴")


def _row_summary(row: dict) -> str:
    rid = row.get("id") or row.get("register_id")
    name = (row.get("company_name") or row.get("companyName")
            or row.get("user_name") or row.get("nickname") or row.get("name") or "")
    review = row.get("status_name") or row.get("status") or ""
    pay = row.get("pay_state_name") or row.get("pay_state") or ""
    pid = row.get("project_id")
    return f"registerId={rid}  project_id={pid}  审核={review}  缴费={pay}  单位/姓名={name}"


def _is_unpaid(row: dict) -> bool:
    blob = " ".join(str(row.get(k, "")) for k in _PAY_KEYS)
    return any(h in blob for h in _UNPAID_HINTS)


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        log(f"未找到配置文件 {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_admin(cfg: dict) -> AdminClient:
    adm = cfg.get("admin", {})
    if not adm.get("php_session"):
        log("配置缺少 admin.php_session，无法访问后台列表接口。")
        sys.exit(1)
    opts = cfg.get("options", {})
    return AdminClient(cfg["base_url"], adm.get("prefix", "/zjgj230214"),
                       adm["php_session"], timeout=opts.get("timeout", 30),
                       verify_ssl=opts.get("verify_ssl", True))


def do_list_projects(admin: AdminClient, page, limit):
    payload = admin.list_projects(page, limit)
    rows = admin.rows(payload)
    if not rows:
        log(f"未取到项目（可能 PHPSESSID 过期）。原始返回：{str(payload)[:300]}")
        return
    log(f"公示项目（第 {page} 页，共 {payload.get('count', '?')} 条）：")
    if rows:
        log(f"（首行字段：{list(rows[0].keys())}）", indent=1)
    for r in rows:
        pid = r.get("id") or r.get("project_id")
        nm = (r.get("project_name") or r.get("name") or r.get("title")
              or r.get("publicity_name") or r.get("project_title") or "")
        st = r.get("status_name") or r.get("status_text") or r.get("status") or ""
        log(f"  项目id={pid}  状态={st}  {nm}", indent=1)


def get_latest_project_id(admin: AdminClient):
    """取最新项目 id（项目列表按创建时间倒序，第一条即最新）。"""
    payload = admin.list_projects(page=1, limit=1)
    rows = admin.rows(payload)
    if not rows:
        log(f"无法获取最新项目（PHPSESSID 可能过期）。原始返回：{str(payload)[:300]}")
        return None
    r = rows[0]
    pid = r.get("id") or r.get("project_id")
    title = r.get("title") or r.get("project_name") or r.get("name") or ""
    log(f"最新项目：id={pid}  {title}")
    return pid


def do_list_registers(admin: AdminClient, project_id):
    payload = admin.list_registers(project_id)
    rows = admin.rows(payload)
    if not rows:
        log(f"项目 {project_id} 无报名人员或取数失败。原始返回：{str(payload)[:300]}")
        return []
    log(f"项目 {project_id} 报名人员（共 {payload.get('count', len(rows))} 条）：")
    if rows:
        log(f"（首行字段：{list(rows[0].keys())}）", indent=1)
    for r in rows:
        log("  " + _row_summary(r), indent=1)
    return rows


def do_pay(cfg, register_ids):
    sup = (cfg.get("payment") or {}).get("supplement") or {}
    token = (sup.get("api_token") or "").strip()
    path = (sup.get("path") or "").strip()
    param_name = sup.get("param_name", "registerId")
    method = (sup.get("method") or "GET").upper()
    if not token or not path:
        log("配置缺少 payment.supplement.api_token 或 path，无法补单。")
        return
    allow = bool(cfg.get("options", {}).get("allow_writes"))
    client = ApiClient(cfg["base_url"], cfg.get("api_prefix", "/api"),
                       token=token, timeout=cfg.get("options", {}).get("timeout", 30),
                       verify_ssl=cfg.get("options", {}).get("verify_ssl", True),
                       label="补单", dry_run=not allow)
    log(f"开始补单（{'真实执行' if allow else '演练: 只打印'}），共 {len(register_ids)} 条")
    ok = 0
    for rid in register_ids:
        params = {param_name: rid}
        if method == "POST":
            res = client.request("POST", path, data=params, is_write=True)
        else:
            res = client.request("GET", path, params=params, is_write=True)
        status = "成功" if res.ok else "失败"
        if res.ok:
            ok += 1
        log(f"  registerId={rid} -> {status}  {res.brief()}", indent=1)
    log(f"补单完成：成功 {ok}/{len(register_ids)}")


def main():
    ap = argparse.ArgumentParser(description="项目缴费补单工具")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("-p", "--project-id", help="项目 id：列出其报名人员，配合 --pay 对全部补单")
    ap.add_argument("--latest", action="store_true",
                    help="取最新项目（项目列表第一条）作为 project_id")
    ap.add_argument("-r", "--register-id", help="直接指定 registerId 补单")
    ap.add_argument("--pay", action="store_true", help="执行补单（否则仅列出）")
    ap.add_argument("--only-unpaid", action="store_true", help="只对'待缴费'状态补单")
    ap.add_argument("--allow-writes", action="store_true", help="真实发送补单请求")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.allow_writes:
        cfg.setdefault("options", {})["allow_writes"] = True

    # 直接对单个 registerId 补单
    if args.register_id:
        if not args.pay:
            log("提供了 --register-id；如需补单请加 --pay")
            return
        do_pay(cfg, [args.register_id])
        return

    admin = build_admin(cfg)

    # 取最新项目 id
    if args.latest:
        latest = get_latest_project_id(admin)
        if not latest:
            return
        args.project_id = latest

    # 列项目
    if not args.project_id:
        do_list_projects(admin, args.page, args.limit)
        return

    # 列某项目报名人员（可补单）
    rows = do_list_registers(admin, args.project_id)
    if args.pay:
        if args.only_unpaid:
            rows = [r for r in rows if _is_unpaid(r)]
            log(f"筛选'待缴费'后剩 {len(rows)} 条")
        ids = [r.get("id") or r.get("register_id") for r in rows]
        ids = [i for i in ids if i]
        if not ids:
            log("无可补单的 registerId")
            return
        do_pay(cfg, ids)


if __name__ == "__main__":
    main()
