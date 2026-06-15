# -*- coding: utf-8 -*-
import os, sys, json, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml, requests
requests.packages.urllib3.disable_warnings()
from admin_client import AdminClient

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
base = cfg["base_url"].rstrip("/"); adm = cfg["admin"]
ac = AdminClient(base, adm["prefix"], adm.get("php_session", ""), timeout=60,
                 verify_ssl=False, username=adm.get("username", ""),
                 password=adm.get("password", ""))
ac.mint_token(cfg["accounts"]["manager"]["uid"])  # warm/relogin

small = r"D:\文件\测试项目资料\项目001-工程施建\中冶天工集团有限公司的投标文件\投标函.pdf"
variants = [
    "/uploads/uploadFile.html",
    "/Uploads/uploadFile.html",
    "/uploads/uploadImage.html",
    "/uploads/uploadFile",
    base.replace("https://www.bidding", "https://www.bidding") + "/api/uploads/uploadFile",  # placeholder
]
import time
for path in variants[:4]:
    url = ac._url(path)
    try:
        with open(small, "rb") as f:
            r = ac.session.post(url, files={"file": (os.path.basename(small), f, "application/pdf")},
                                verify=False, timeout=120)
        try:
            body = json.dumps(r.json(), ensure_ascii=False)[:300]
        except Exception:
            body = "non-json:" + (r.text or "")[:120].replace("\n", " ")
        print(f"{path} -> {r.status_code} {body}")
    except Exception as e:
        print(f"{path} -> EXC {type(e).__name__}")
    time.sleep(1)
