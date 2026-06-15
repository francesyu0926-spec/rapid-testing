# -*- coding: utf-8 -*-
"""探测可能同步 TenderProject 的接口。"""
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
ac.ensure_login()
mgr = ac.mint_token(cfg["accounts"]["manager"]["uid"])
btok = ac.mint_token(cfg["accounts"]["bidders"][0]["uid"])
pid, sid, rid = 2028, 1848, 7717

api_paths = [
    ("GET", "/api/tender/index", {"project_id": pid}),
    ("GET", "/api/tender/list", {"project_id": pid}),
    ("POST", "/api/tender/create", {"project_id": pid, "section_id": sid}),
    ("POST", "/api/publicity/start", {"project_id": pid}),
    ("POST", "/api/publicity/open", {"project_id": pid}),
    ("POST", "/api/publicity/effective", {"project_id": pid}),
    ("POST", "/api/project_register/paySuccess", {"id": rid}),
    ("POST", "/api/project_register/sync", {"id": rid}),
    ("GET", "/api/project_register/paymentErrorHandler", {"registerId": rid}),
]
for method, path, data in api_paths:
    kw = {"headers": {"token": btok if "tender" in path or "register" in path else mgr},
          "verify": False, "timeout": 20}
    if method == "GET":
        r = requests.get(base + path, params=data, **kw)
    else:
        r = requests.post(base + path, data=data, **kw)
    try:
        body = r.json()
        brief = f"code={body.get('code')} msg={body.get('msg')}"
    except Exception:
        brief = f"status={r.status_code} text={(r.text or '')[:80]}"
    print(f"{method} {path} -> {brief}")

admin_paths = [
    "/PublicityProject/getList.html",
    "/PublicityProject/edit.html",
    "/ProjectRegister/getList.html",
    "/ProjectRegister/edit.html",
    "/TaskTimer/index.html",
]
for p in admin_paths:
    params = {"id": pid, "tableUniqueStr": "admin_publicityproject_index",
              "page": 1, "limit": 5}
    r = ac.session.get(ac._url(p), params=params, verify=False, timeout=20)
    text = r.text or ""
    for kw in ("tender", "Tender", "投标", "生效", "同步", "open", "start"):
        if kw.lower() in text.lower():
            print(f"admin {p} contains '{kw}'")
            break
