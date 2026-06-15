# -*- coding: utf-8 -*-
import sys, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml
from admin_client import AdminClient

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
base = cfg["base_url"].rstrip("/"); adm = cfg["admin"]
ac = AdminClient(base, adm["prefix"], adm.get("php_session", ""), timeout=40,
                 verify_ssl=False, username=adm.get("username", ""),
                 password=adm.get("password", ""))
pid = 2028
paths = [
    f"/PublicityProject/publish.html?id={pid}",
    f"/PublicityProject/open.html?id={pid}",
    f"/PublicityProject/start.html?id={pid}",
    f"/PublicityProject/toTender.html?id={pid}",
    f"/PublicityProject/confirm.html?id={pid}",
    "/PublicityProject/publish.html",
    "/PublicityProject/openTender.html",
]
for p in paths:
    r = ac.session.get(ac._url(p.split("?")[0]), params={"id": pid} if "?" not in p else None,
                       verify=False, timeout=15, allow_redirects=False)
    print(p, "->", r.status_code, len(r.text))

posts = [
    ("/PublicityProject/publish.html", {"id": pid}),
    ("/PublicityProject/open.html", {"id": pid}),
    ("/PublicityProject/save.html", {"id": pid, "status": 2}),
]
for path, data in posts:
    r = ac.session.post(ac._url(path), data=data, verify=False, timeout=15)
    try:
        print("POST", path, r.json())
    except Exception:
        print("POST", path, r.status_code, (r.text or "")[:80])
