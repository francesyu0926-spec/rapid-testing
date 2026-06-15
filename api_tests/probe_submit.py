# -*- coding: utf-8 -*-
"""暴力探测 submitFile 的「服务期限」字段名。"""
import sys, json, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml, requests
requests.packages.urllib3.disable_warnings()
from admin_client import AdminClient

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
base = cfg["base_url"].rstrip("/"); adm = cfg["admin"]
ac = AdminClient(base, adm["prefix"], adm.get("php_session", ""), timeout=40,
                 verify_ssl=False, username=adm.get("username", ""),
                 password=adm.get("password", ""))
btok = ac.mint_token(cfg["accounts"]["bidders"][0]["uid"])
url = "/uploads/20260609/8e58fc29414235a46d37f4a604878014.pdf"
files_val = json.dumps([{"name": "test.pdf", "url": url, "tempFilePath": url}],
                       ensure_ascii=False)
base_data = {"tender_id": 2029, "section_id": 1849, "files": files_val,
             "apply_id": 7720, "amount": "990000", "password": "Test123456",
             "address": "山西省太原市", "mobile": "13800000000"}

words = [
    "limit", "period", "day", "days", "time", "date", "term", "service",
    "work", "construction", "completion", "delivery", "validity", "deadline",
    "cycle", "duration", "schedule", "plan", "finish", "end", "start",
    "qixian", "fuwu", "gongqi", "gongqi_day", "limit_day", "limit_days",
    "limit_date", "limit_time", "time_limit", "day_limit", "period_day",
    "period_days", "period_time", "service_day", "service_days", "service_date",
    "service_time", "service_limit", "service_period", "work_period",
    "work_time", "work_day", "work_days", "construction_period",
    "construction_time", "construction_day", "project_period", "project_time",
    "tender_period", "tender_time", "bid_period", "offer_period",
    "valid_time", "valid_day", "valid_days", "valid_period",
    "completion_time", "completion_day", "completion_period",
    "delivery_time", "delivery_day", "delivery_period",
    "execute_time", "execute_period", "perform_time", "perform_period",
    "contract_period", "contract_time", "limit_period", "sever_limit",
]
vals = ["90", "90天", "90日历天", "合同签订后90天内", "2026-12-31"]
found = []
for k in words:
    for v in vals:
        data = {**base_data, k: v}
        r = requests.post(base + "/api/tender/submitFile", headers={"token": btok},
                          data=data, verify=False, timeout=15).json()
        msg = r.get("msg") or ""
        if "服务期限" not in msg:
            found.append((k, v, r.get("code"), msg))
            print(f"** {k}={v!r} -> {r.get('code')} {msg}")
            break
print("\nfound", len(found))
