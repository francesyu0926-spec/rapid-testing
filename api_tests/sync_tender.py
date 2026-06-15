# -*- coding: utf-8 -*-
"""把已支付报名同步进投标阶段（tender/myList）。

正确链路（测试环境微信支付不可用）：
  1. open_bidding：file_end 调到过去
  2. 每条报名：后台置 pay_state=0 -> paymentErrorHandler(registerId) -> TaskTimer

用法：
  python sync_tender.py 2027,2028,2029,2030,2031           # 演练
  python sync_tender.py 2027,2028,2029,2030,2031 --do
"""
import sys, json, argparse, functools, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml, requests
requests.packages.urllib3.disable_warnings()
from admin_client import AdminClient

DEFAULT_IDS = [2027, 2028, 2029, 2030, 2031]
SAVE_KEYS = [
    "id", "uid", "project_id", "sections", "company_name", "company_address",
    "legal_name", "contact", "contact_phone", "email", "images",
    "total_deposit", "total_file_price", "total_platform_price", "status",
]


def reset_unpaid(ac, base, btok, rid):
    chk = requests.get(base + "/api/project_register/info", headers={"token": btok},
                       params={"id": rid}, verify=False, timeout=30).json().get("data") or {}
    payload = {k: chk.get(k) for k in SAVE_KEYS if chk.get(k) is not None}
    payload["pay_state"] = 0
    payload["pay_time"] = ""
    payload["sn"] = ""
    if not isinstance(payload.get("images"), str):
        payload["images"] = json.dumps(payload.get("images") or [], ensure_ascii=False)
    return ac.session.post(ac._url("/ProjectRegister/save.html"), data=payload,
                           verify=False, timeout=30,
                           headers={"referer": ac._url(f"/ProjectRegister/edit.html?id={rid}")})


def supplement(base, btok, rid):
    return requests.get(base + "/api/project_register/paymentErrorHandler",
                        headers={"token": btok}, params={"registerId": rid},
                        verify=False, timeout=30)


def tender_map(base, btok):
    tl = requests.get(base + "/api/tender/myList", headers={"token": btok},
                      params={"page": 1, "limit": 100}, verify=False).json()
    rows = tl.get("data", {}).get("list", []) if isinstance(tl.get("data"), dict) else []
    return {str(r.get("project_id")): r for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="?", default=",".join(map(str, DEFAULT_IDS)))
    ap.add_argument("--do", action="store_true")
    args = ap.parse_args()
    ids = {int(x) for x in args.ids.split(",") if x.strip()}

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    base = cfg["base_url"].rstrip("/"); adm = cfg["admin"]
    ac = AdminClient(base, adm["prefix"], adm.get("php_session", ""), timeout=40,
                     verify_ssl=False, username=adm.get("username", ""),
                     password=adm.get("password", ""))
    ac.ensure_login()

    jobs = []
    for b in cfg["accounts"]["bidders"]:
        btok = ac.mint_token(b["uid"])
        ml = requests.get(base + "/api/project_register/myList", headers={"token": btok},
                          params={"page": 1, "limit": 50}, verify=False).json()
        for row in (ml.get("data", {}).get("list", []) if isinstance(ml.get("data"), dict) else []):
            if row.get("project_id") in ids:
                jobs.append((b.get("name", b["uid"]), b["uid"], btok, row["id"], row["project_id"]))

    print(f"待同步 {len(jobs)} 条报名")
    if not args.do:
        for j in jobs:
            print(f"  [演练] {j[0]} project={j[4]} register={j[3]}")
        return

    ok = 0
    for label, uid, btok, rid, pid in jobs:
        before = tender_map(base, btok).get(str(pid))
        if before:
            print(f"  {label} pid={pid} 已在 tender/myList tender_id={before.get('tender_id')}")
            ok += 1
            continue
        r1 = reset_unpaid(ac, base, btok, rid)
        r2 = supplement(base, btok, rid).json()
        info = requests.get(base + "/api/project_register/info", headers={"token": btok},
                            params={"id": rid}, verify=False).json().get("data") or {}
        # handler 须把 pay_state 置为 2；若仍为 0 说明补单未生效（勿重复调用）
        if r2.get("code") == 1 and str(info.get("pay_state")) != "2":
            chk_keys = ["id", "uid", "project_id", "sections", "company_name",
                        "company_address", "legal_name", "contact", "contact_phone",
                        "email", "images", "total_deposit", "total_file_price",
                        "total_platform_price", "status"]
            payload = {k: info.get(k) for k in chk_keys if info.get(k) is not None}
            payload["pay_state"] = 2
            payload["pay_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if not isinstance(payload.get("images"), str):
                payload["images"] = json.dumps(payload.get("images") or [], ensure_ascii=False)
            ac.session.post(ac._url("/ProjectRegister/save.html"), data=payload,
                              verify=False, timeout=30,
                              headers={"referer": ac._url(f"/ProjectRegister/edit.html?id={rid}")})
        for p in ("/TaskTimer/autoStart.html", "/TaskTimer/autoEffective.html"):
            ac.session.get(ac._url(p), verify=False, timeout=120)
        after = tender_map(base, btok).get(str(pid))
        info2 = requests.get(base + "/api/project_register/info", headers={"token": btok},
                             params={"id": rid}, verify=False).json().get("data") or {}
        print(f"  {label} rid={rid} reset={r1.json().get('code')} "
              f"handler={r2.get('code')} pay={info2.get('pay_state')} "
              f"tender={'tid='+str(after.get('tender_id')) if after else 'NO'}")
        if after:
            ok += 1

    print(f"\n完成：{ok}/{len(jobs)} 条出现在 tender/myList（以投标人A复核）")
    btok0 = ac.mint_token(cfg["accounts"]["bidders"][0]["uid"])
    for pid in sorted(ids):
        tr = tender_map(base, btok0).get(str(pid))
        print(f"  pid={pid}: {'tender_id='+str(tr.get('tender_id')) if tr else '缺失'}")


if __name__ == "__main__":
    main()
