# -*- coding: utf-8 -*-
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
url = "/uploads/20260609/1fd34d456e5001cefc42378a0c6414e8.pdf"
files_val = json.dumps([{"name": "bid.pdf", "url": url, "tempFilePath": url}],
                       ensure_ascii=False)
common = {"section_id": 1848, "apply_id": 7717, "amount": "990000",
          "password": "123456", "password_confirm": "123456",
          "address": "山西省太原市", "mobile": "13800000000",
          "deadline": "90天", "files": files_val}

# 1988 可对比：先找报名 id
ml = requests.get(base + "/api/project_register/myList", headers={"token": btok},
                  params={"page": 1, "limit": 50}, verify=False).json()
rows = ml.get("data", {}).get("list", []) if isinstance(ml.get("data"), dict) else []
for pid in [1988, 2028]:
    row = next((r for r in rows if str(r.get("project_id")) == str(pid)), None)
    print(f"reg {pid}", row.get("id") if row else None, row.get("sections") if row else None)

# 多种 id 字段组合
for label, extra in [
    ("tender_id=2028", {"tender_id": 2028}),
    ("tender_id=1035", {"tender_id": 1035}),
    ("tender_id=1040", {"tender_id": 1040}),
    ("project_id=2028", {"project_id": 2028}),
    ("resubmit", {}),
]:
    path = "/api/tender/resubmitTenderFile" if label == "resubmit" else "/api/tender/submitFile"
    data = {**common, **extra}
    if label == "resubmit":
        data = {"tender_id": 2028, "section_id": 1848, "files": files_val, "amount": "990000"}
    r = requests.post(base + path, headers={"token": btok}, data=data, verify=False, timeout=30).json()
    print(label, "->", r.get("code"), r.get("msg"))
