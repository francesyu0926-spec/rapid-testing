# -*- coding: utf-8 -*-
import json, sys, functools
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
btok = ac.mint_token(cfg["accounts"]["bidders"][0]["uid"])

rows = ac.rows(ac.list_projects(page=1, limit=200))
want = {1988, 1987, 1922, 2027, 2028, 2029, 2030, 2031}
tl = requests.get(base + "/api/tender/myList", headers={"token": btok},
                  params={"page": 1, "limit": 50}, verify=False).json()
tpids = {str(x.get("project_id")) for x in (tl.get("data", {}).get("list", []) or [])}

print("id  status status_name  state  in_tender  title")
for r in rows:
    pid = r.get("id")
    if pid not in want:
        continue
    print(f"{pid}  {r.get('status')}  {r.get('status_name')}  {r.get('state')}  "
          f"{str(pid) in tpids}  {(r.get('title') or '')[:35]}")
