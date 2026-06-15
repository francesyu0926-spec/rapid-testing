# -*- coding: utf-8 -*-
import re, sys, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml
from admin_client import AdminClient

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
base = cfg["base_url"].rstrip("/"); adm = cfg["admin"]
ac = AdminClient(base, adm["prefix"], adm.get("php_session", ""), timeout=40,
                 verify_ssl=False, username=adm.get("username", ""),
                 password=adm.get("password", ""))
ac.ensure_login()
pid = 2028
pages = [
    ("/PublicityProject/edit.html", {"id": pid}),
    ("/ProjectRegister/index.html", {"tableUniqueStr": "admin_publicityproject_index", "id": pid}),
    ("/TaskTimer/index.html", {}),
]
for path, params in pages:
    r = ac.session.get(ac._url(path), params=params, verify=False, timeout=30)
    text = r.text or ""
    print(f"\n=== {path} status={r.status_code} len={len(text)} ===")
    for m in re.finditer(r"[\w/]+\.html", text):
        s = m.group(0)
        if any(k in s.lower() for k in ("tender", "timer", "register", "publicity", "task")):
            pass
    urls = set(re.findall(r"['\"](/[^'\"]+?\.html[^'\"]*)['\"]", text))
    urls |= set(re.findall(r"url\s*:\s*['\"]([^'\"]+)['\"]", text))
    for u in sorted(urls):
        if any(k in u for k in ("投标", "tender", "Tender", "Timer", "timer", "生效", "open", "start", "sync")):
            print(" ", u)
    # lines containing 投标
    for i, line in enumerate(text.splitlines()):
        if "投标" in line and ("url" in line or "href" in line or ".html" in line):
            print(" LINE:", line.strip()[:200])
