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

for p, params in [
    ("/TaskTimer/getList.html", {"page": 1, "limit": 50, "tableUniqueStr": "admin_tasktimer_index"}),
    ("/PublicityProject/getList.html", {"page": 1, "limit": 5, "tableUniqueStr": "admin_publicityproject_index", "keyword": "2028"}),
]:
    r = ac.get(p, params=params)
    print(p, json.dumps(r, ensure_ascii=False)[:800])
