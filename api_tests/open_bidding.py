# -*- coding: utf-8 -*-
"""开启投标阶段：把 file_end 调到过去 + 触发定时任务，使已支付报名进入 tender/myList。

根因：投标人只能对 tender/myList 中的项目 submitFile；该列表通常在
「获取文件截止(file_end)已过 + 已支付」后由 TaskTimer 同步生成 TenderProject。

用法：
  python open_bidding.py                    # 演练
  python open_bidding.py --do               # 对默认 5 个项目执行
  python open_bidding.py 2028 --do          # 单个项目
"""
import sys, datetime, argparse, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml, requests
requests.packages.urllib3.disable_warnings()
from admin_client import AdminClient

SAVE_FIELDS = [
    "id", "uid", "company_id", "project_no", "title", "is_audit",
    "cate_id", "username", "address", "pattern_id", "start_time",
    "file_start_time", "file_end_time", "price", "deposit",
    "file_price", "platform_price", "is_bid_section", "intro",
    "images", "is_min", "status", "state",
]
DEFAULT_IDS = [2027, 2028, 2029, 2030, 2031]
PAID = 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="?", default=",".join(map(str, DEFAULT_IDS)),
                    help="project_id 逗号分隔")
    ap.add_argument("--do", action="store_true")
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.split(",") if x.strip()]

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    base = cfg["base_url"].rstrip("/"); adm = cfg["admin"]
    ac = AdminClient(base, adm["prefix"], adm.get("php_session", ""), timeout=40,
                     verify_ssl=False, username=adm.get("username", ""),
                     password=adm.get("password", ""))
    ac.ensure_login()
    mgr = ac.mint_token(cfg["accounts"]["manager"]["uid"])
    bidder_uid = cfg["accounts"]["bidders"][0]["uid"]
    btok = ac.mint_token(bidder_uid)

    now = datetime.datetime.now()
    fmt = "%Y-%m-%d %H:%M:%S"
    file_start = now - datetime.timedelta(days=2)
    file_end = now - datetime.timedelta(minutes=30)   # 已截止获取文件
    open_time = now + datetime.timedelta(days=1)
    open_time = open_time.replace(hour=14, minute=0, second=0, microsecond=0)

    print(f"目标时间: 获取 {file_start.strftime(fmt)} ~ {file_end.strftime(fmt)}; "
          f"开标 {open_time.strftime(fmt)}")

    for pid in ids:
        info = requests.get(base + "/api/publicity/projectInfo", headers={"token": mgr},
                            params={"project_id": pid}, verify=False, timeout=30).json()
        d = info.get("data") or {}
        print(f"\n[{pid}] {d.get('title', '')[:40]}")
        if not args.do:
            print("  [演练] 未加 --do"); continue

        payload = {k: d.get(k) for k in SAVE_FIELDS if d.get(k) is not None}
        payload["id"] = pid
        payload["file_start_time"] = file_start.strftime(fmt)
        payload["file_end_time"] = file_end.strftime(fmt)
        payload["start_time"] = open_time.strftime(fmt)
        # 投标阶段常见 state=3/4；勿用 6（多为评标后状态）
        if int(payload.get("state") or 0) >= 6:
            payload["state"] = 3

        r = ac.session.post(ac._url("/PublicityProject/save.html"), data=payload,
                            verify=False, timeout=30,
                            headers={"referer": ac._url(f"/PublicityProject/edit.html?id={pid}")})
        print(f"  save publicity: {r.json()}")

    if not args.do:
        return

    for path in ("/TaskTimer/autoStart.html", "/TaskTimer/autoEffective.html"):
        res = ac.session.get(ac._url(path), verify=False, timeout=120).json()
        print(f"  {path}: {res}")

    # 恢复误改待支付的报名（若存在）
    for b in cfg["accounts"]["bidders"]:
        tok = ac.mint_token(b["uid"])
        ml = requests.get(base + "/api/project_register/myList", headers={"token": tok},
                          params={"page": 1, "limit": 50}, verify=False).json()
        for row in (ml.get("data", {}).get("list", []) if isinstance(ml.get("data"), dict) else []):
            if row.get("project_id") not in ids:
                continue
            if str(row.get("pay_state")) == str(PAID):
                continue
            rid = row["id"]
            chk = requests.get(base + "/api/project_register/info", headers={"token": tok},
                               params={"id": rid}, verify=False).json().get("data") or {}
            save = {
                "id": rid, "uid": chk.get("uid"), "project_id": chk.get("project_id"),
                "sections": chk.get("sections"), "company_name": chk.get("company_name"),
                "company_address": chk.get("company_address"), "legal_name": chk.get("legal_name"),
                "contact": chk.get("contact"), "contact_phone": chk.get("contact_phone"),
                "email": chk.get("email"), "images": chk.get("images"),
                "total_deposit": chk.get("total_deposit"),
                "total_file_price": chk.get("total_file_price"),
                "total_platform_price": chk.get("total_platform_price"),
                "status": chk.get("status", 2), "pay_state": PAID,
                "pay_time": now.strftime(fmt),
            }
            ac.session.post(ac._url("/ProjectRegister/save.html"), data=save, verify=False,
                            timeout=30,
                            headers={"referer": ac._url(f"/ProjectRegister/edit.html?id={rid}")})
            print(f"  恢复已支付 register_id={rid} project={chk.get('project_id')}")

    tl = requests.get(base + "/api/tender/myList", headers={"token": btok},
                      params={"page": 1, "limit": 50}, verify=False).json()
    trows = tl.get("data", {}).get("list", []) if isinstance(tl.get("data"), dict) else []
    for pid in ids:
        tr = next((r for r in trows if str(r.get("project_id")) == str(pid)), None)
        print(f"  tender/myList pid={pid}: "
              f"{'tender_id=' + str(tr.get('tender_id')) if tr else '未出现'}")


if __name__ == "__main__":
    main()
