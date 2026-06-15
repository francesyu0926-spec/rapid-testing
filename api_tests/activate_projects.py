# -*- coding: utf-8 -*-
"""把公示项目 state 置为可投标状态（参照可递交项目 state=6）。"""
import sys, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml, requests
requests.packages.urllib3.disable_warnings()
from admin_client import AdminClient

SAVE_FIELDS = ["id", "uid", "company_id", "project_no", "title", "is_audit",
               "cate_id", "username", "address", "pattern_id", "start_time",
               "file_start_time", "file_end_time", "price", "deposit",
               "file_price", "platform_price", "is_bid_section", "intro",
               "images", "is_min", "status", "state"]


def main():
    ids = [int(x) for x in sys.argv[1].split(",")] if len(sys.argv) > 1 else \
        [2027, 2028, 2029, 2030, 2031]
    target_state = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    base = cfg["base_url"].rstrip("/"); adm = cfg["admin"]
    ac = AdminClient(base, adm["prefix"], adm.get("php_session", ""), timeout=40,
                     verify_ssl=False, username=adm.get("username", ""),
                     password=adm.get("password", ""))
    mgr = ac.mint_token(cfg["accounts"]["manager"]["uid"])
    for pid in ids:
        info = requests.get(base + "/api/publicity/projectInfo", headers={"token": mgr},
                            params={"project_id": pid}, verify=False, timeout=30).json()
        d = info.get("data") or {}
        payload = {k: d.get(k) for k in SAVE_FIELDS if d.get(k) is not None}
        payload["id"] = pid
        payload["state"] = target_state
        r = ac.session.post(ac._url("/PublicityProject/save.html"), data=payload,
                            verify=False, timeout=30,
                            headers={"referer": ac._url(f"/PublicityProject/edit.html?id={pid}")})
        res = r.json()
        info2 = requests.get(base + "/api/publicity/projectInfo", headers={"token": mgr},
                             params={"project_id": pid}, verify=False, timeout=30).json()
        print(f"[{pid}] save={res.get('code')} state->{(info2.get('data') or {}).get('state')}")


if __name__ == "__main__":
    main()
