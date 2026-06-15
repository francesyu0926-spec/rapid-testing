# -*- coding: utf-8 -*-
"""延长已建项目的开标时间（后台 save 原地更新）。

注意：若目标是开启投标递交，请用 open_bidding.py（会把 file_end 调到过去）。
本脚本默认把 file_end 设到明天，仅适用于延长报名期，不适用于投标阶段。
"""
import sys, datetime, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml, requests
requests.packages.urllib3.disable_warnings()
from admin_client import AdminClient

SAVE_FIELDS = ["id", "uid", "company_id", "project_no", "title", "is_audit",
               "cate_id", "username", "address", "pattern_id", "start_time",
               "file_start_time", "file_end_time", "price", "deposit",
               "file_price", "platform_price", "is_bid_section", "intro",
               "images", "is_min"]


def main():
    ids = [int(x) for x in sys.argv[1].split(",")] if len(sys.argv) > 1 else \
        [2027, 2028, 2029, 2030, 2031]
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    base = cfg["base_url"].rstrip("/"); adm = cfg["admin"]
    ac = AdminClient(base, adm["prefix"], adm.get("php_session", ""), timeout=40,
                     verify_ssl=False, username=adm.get("username", ""),
                     password=adm.get("password", ""))
    mgr = ac.mint_token(cfg["accounts"]["manager"]["uid"])
    now = datetime.datetime.now()
    tomorrow = now + datetime.timedelta(days=1)
    fmt = "%Y-%m-%d %H:%M:%S"
    file_start = now - datetime.timedelta(minutes=10)
    file_end = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
    open_time = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
    print(f"新时间: 获取 {file_start.strftime(fmt)} ~ {file_end.strftime(fmt)}; 开标 {open_time.strftime(fmt)}")

    for pid in ids:
        info = requests.get(base + "/api/publicity/projectInfo", headers={"token": mgr},
                            params={"project_id": pid}, verify=False, timeout=30).json()
        d = info.get("data") or {}
        payload = {k: d.get(k) for k in SAVE_FIELDS if d.get(k) is not None}
        payload["id"] = pid
        payload["file_start_time"] = file_start.strftime(fmt)
        payload["file_end_time"] = file_end.strftime(fmt)
        payload["start_time"] = open_time.strftime(fmt)
        r = ac.session.post(ac._url("/PublicityProject/save.html"), data=payload,
                            verify=False, timeout=30,
                            headers={"referer": ac._url(f"/PublicityProject/edit.html?id={pid}")})
        res = r.json()
        print(f"[{pid}] {d.get('title','')[:30]} save={res.get('code')} {res.get('msg')}")


if __name__ == "__main__":
    main()
