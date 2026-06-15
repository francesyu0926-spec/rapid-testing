# -*- coding: utf-8 -*-
import json, sys, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml
from admin_client import AdminClient

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
adm = cfg["admin"]
ac = AdminClient(cfg["base_url"], adm["prefix"], adm.get("php_session", ""), timeout=40,
                 verify_ssl=False, username=adm.get("username", ""),
                 password=adm.get("password", ""))
ac.ensure_login()
rows = {r["id"]: r for r in ac.rows(ac.list_projects(page=1, limit=200))}
for pid in [2027, 2028, 2029, 2030, 2031]:
    r = rows.get(pid, {})
    print(f"\n=== {pid} ===")
    for k in sorted(r.keys()):
        if k not in ("images", "intro"):
            print(f"  {k}: {r.get(k)}")
