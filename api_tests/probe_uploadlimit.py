# -*- coding: utf-8 -*-
"""探测 /api/uploads/uploadImage 服务端最大上传体积。"""
import os, sys, re, functools
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
tok = ac.mint_token(cfg["accounts"]["bidders"][0]["uid"])
print("token:", (tok or "")[:12])

tests = [
    (12223, r"D:\文件\测试项目资料\项目002-工程施建\上海洁岩环保科技有限公司的投标文件\近年完成的类似业绩.pdf"),
    (18550, r"D:\文件\测试项目资料\项目003-工程施建\山西天地衡建设工程项目管理有限公司的投标文件\山西天地衡建设工程项目管理有限公司投标文件.pdf"),
    (22470, r"D:\文件\测试项目资料\项目002-工程施建\宁波海辰天力机械制造有限公司的投标文件\宁波海辰天力机械制造有限公司投标文件.pdf"),
    (30844, r"D:\文件\测试项目资料\项目001-工程施建\山西建筑工程集团有限公司的投标文件\山西建筑工程集团有限公司投标文件.pdf"),
]

for sz, p in tests:
    if not os.path.exists(p):
        print(f"{sz:>6}KB  MISSING"); continue
    real = os.path.getsize(p) // 1024
    with open(p, "rb") as f:
        r = requests.post(base + "/api/uploads/uploadImage", headers={"token": tok},
                          files={"file": (os.path.basename(p), f, "application/pdf")},
                          verify=False, timeout=600)
    try:
        j = r.json()
        url = (j.get("data") or {}).get("url", "")
        print(f"{real:>6}KB  {os.path.basename(p)[:30]}  ->  code={j.get('code')} msg={j.get('msg')}")
    except Exception:
        t = (r.text or "").replace("\n", " ")
        m = re.search(r"<title>(.*?)</title>", t)
        print(f"{real:>6}KB  {os.path.basename(p)[:30]}  ->  HTTP{r.status_code} {m.group(1) if m else t[:60]}")
