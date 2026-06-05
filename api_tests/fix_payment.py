# -*- coding: utf-8 -*-
"""把报名记录的支付状态直接改为已支付（测试环境无真实微信支付时用）。

前端 paymentErrorHandler 只对接真实微信订单，测试数据不会更新 pay_state；
故用后台 ProjectRegister/save 原地把 pay_state 置为已支付并补 pay_time。

用法：
  python fix_payment.py 7708            # 演练
  python fix_payment.py 7708 --do       # 真实
  python fix_payment.py 7708,7709 --do --paid 2
"""
import sys, json, datetime, argparse, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml, requests
requests.packages.urllib3.disable_warnings()
from admin_client import AdminClient

SAVE_FIELDS = ["id", "uid", "project_id", "sections", "company_name",
               "company_address", "legal_name", "contact", "contact_phone",
               "email", "images", "total_deposit", "total_file_price",
               "total_platform_price", "status", "pay_state", "pay_time",
               "sn", "remark_2", "admin_id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids")
    ap.add_argument("--do", action="store_true")
    ap.add_argument("--paid", type=int, default=2, help="已支付对应的 pay_state 值")
    ap.add_argument("--ctx", type=int, default=2026, help="admin getList 会话项目(取行数据用)")
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.split(",") if x.strip()]

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    base = cfg["base_url"].rstrip("/"); adm = cfg["admin"]
    ac = AdminClient(base, adm["prefix"], adm.get("php_session", ""), timeout=30,
                     verify_ssl=False, username=adm.get("username", ""),
                     password=adm.get("password", ""))
    bidtok = {}  # uid -> token，用于前端复核
    mgr = ac.mint_token(cfg["accounts"]["manager"]["uid"])

    rows = {r.get("id"): r for r in ac.rows(ac.list_registers(args.ctx))}

    def verify(rid, uid):
        tok = bidtok.get(uid)
        if not tok:
            tok = ac.mint_token(uid); bidtok[uid] = tok
        r = requests.get(base + "/api/project_register/info", headers={"token": tok},
                         params={"id": rid}, verify=False, timeout=30).json()
        d = r.get("data") or {}
        return d.get("pay_state"), d.get("pay_state_name")

    for rid in ids:
        row = rows.get(rid)
        if not row:
            print(f"[{rid}] admin getList(ctx={args.ctx}) 未取到行数据，跳过"); continue
        uid = row.get("uid")
        ps, psn = verify(rid, uid)
        print(f"\n[{rid}] uid={uid} 改前 pay_state={ps}({psn})")
        if not args.do:
            print("  [演练] 未加 --do，不写入"); continue
        payload = {k: row.get(k) for k in SAVE_FIELDS if row.get(k) is not None}
        if not isinstance(payload.get("images"), str):
            payload["images"] = json.dumps(payload.get("images") or [], ensure_ascii=False)
        payload["id"] = rid
        payload["pay_state"] = args.paid
        payload["pay_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        r = ac.session.post(ac._url("/ProjectRegister/save.html"), data=payload,
                            verify=False, timeout=30,
                            headers={"referer": ac._url(f"/ProjectRegister/edit.html?id={rid}")})
        try:
            res = r.json(); print(f"  save: code={res.get('code')} msg={res.get('msg')}")
        except Exception:
            print(f"  save 非JSON: {r.status_code} {r.text[:160]}")
        ps2, psn2 = verify(rid, uid)
        print(f"  改后 pay_state={ps2}({psn2})")


if __name__ == "__main__":
    main()
