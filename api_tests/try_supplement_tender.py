# -*- coding: utf-8 -*-
"""尝试用 paymentErrorHandler(registerId) 触发与真实支付相同的后续同步。"""
import sys, json, datetime, functools
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
ac.ensure_login()
uid = cfg["accounts"]["bidders"][0]["uid"]
btok = ac.mint_token(uid)
rid = 7717
fmt = "%Y-%m-%d %H:%M:%S"

def info():
    return requests.get(base + "/api/project_register/info", headers={"token": btok},
                        params={"id": rid}, verify=False).json().get("data") or {}

def tender_row():
    tl = requests.get(base + "/api/tender/myList", headers={"token": btok},
                      params={"page": 1, "limit": 50}, verify=False).json()
    rows = tl.get("data", {}).get("list", []) if isinstance(tl.get("data"), dict) else []
    return next((r for r in rows if r.get("project_id") == 2028), None)

chk = info()
print("before pay_state", chk.get("pay_state"), "sn", repr(chk.get("sn")))

# 1) 置未支付
save = {k: chk.get(k) for k in [
    "id", "uid", "project_id", "sections", "company_name", "company_address",
    "legal_name", "contact", "contact_phone", "email", "images",
    "total_deposit", "total_file_price", "total_platform_price", "status",
]}
save["pay_state"] = 0
save["pay_time"] = ""
save["sn"] = ""
if not isinstance(save.get("images"), str):
    save["images"] = json.dumps(save.get("images") or [], ensure_ascii=False)
print("reset", ac.session.post(ac._url("/ProjectRegister/save.html"), data=save,
                                verify=False, timeout=30).json())
print("after reset", info().get("pay_state"), info().get("pay_state_name"))

# 2) 补单
r = requests.get(base + "/api/project_register/paymentErrorHandler",
                 headers={"token": btok}, params={"registerId": rid},
                 verify=False, timeout=30).json()
print("paymentErrorHandler", r)
print("after handler pay", info().get("pay_state"), "sn", repr(info().get("sn")))

# 3) 定时任务
for p in ("/TaskTimer/autoStart.html", "/TaskTimer/autoEffective.html"):
    print(p, ac.session.get(ac._url(p), verify=False, timeout=120).json())

print("tender row", tender_row())
