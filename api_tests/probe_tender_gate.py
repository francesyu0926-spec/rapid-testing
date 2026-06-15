# -*- coding: utf-8 -*-
"""探测 tender/myList 出现条件：对比已支付报名 vs 文件获取截止时间。"""
import sys, functools
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
mgr = ac.mint_token(cfg["accounts"]["manager"]["uid"])
btok = ac.mint_token(cfg["accounts"]["bidders"][0]["uid"])

ml = requests.get(base + "/api/project_register/myList", headers={"token": btok},
                  params={"page": 1, "limit": 50}, verify=False).json()
rrows = ml.get("data", {}).get("list", []) if isinstance(ml.get("data"), dict) else []
tl = requests.get(base + "/api/tender/myList", headers={"token": btok},
                  params={"page": 1, "limit": 50}, verify=False).json()
trows = tl.get("data", {}).get("list", []) if isinstance(tl.get("data"), dict) else []
tpids = {str(x.get("project_id")) for x in trows}

print("bidder paid registers vs tender list:")
for r in rrows[:15]:
    pid = r.get("project_id")
    info = requests.get(base + "/api/publicity/projectInfo", headers={"token": mgr},
                        params={"project_id": pid}, verify=False).json().get("data") or {}
    fe = info.get("file_end_time")
    st = info.get("start_time")
    in_t = str(pid) in tpids
    print(f"  pid={pid} pay={r.get('pay_state_name')} file_end={fe} open={st} in_tender={in_t}")
