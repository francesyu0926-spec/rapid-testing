# -*- coding: utf-8 -*-
"""上传 804KB 技术部分 PDF，分别用 投标人/项目经理 token，打印完整 500 报错。"""
import os, sys, functools, re
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

def mint(uid):
    for _ in range(8):
        t = ac.mint_token(uid)
        if t:
            return t
    return ""

F = r"D:\文件\测试项目资料\项目002-工程施建\上海洁岩环保科技有限公司的投标文件\投标文件技术部分.pdf"
print("file:", os.path.getsize(F)//1024, "KB")

def try_upload(who, tok):
    for _ in range(6):
        try:
            with open(F, "rb") as f:
                r = requests.post(base + "/api/uploads/uploadImage",
                                  headers={"token": tok},
                                  files={"file": (os.path.basename(F), f, "application/pdf")},
                                  verify=False, timeout=300)
            print(f"\n[{who}] HTTP {r.status_code} ctype={r.headers.get('content-type')}")
            try:
                print(f"[{who}] JSON:", r.json())
            except Exception:
                t = r.text or ""
                # ThinkPHP 错误页里的异常信息
                for pat in (r"<title>(.*?)</title>",
                            r'class="exception-msg">(.*?)<',
                            r'"message":"(.*?)"',
                            r'<h1[^>]*>(.*?)</h1>'):
                    m = re.search(pat, t, re.S)
                    if m:
                        print(f"[{who}] ERR<{pat[:12]}>:", re.sub(r"\s+", " ", m.group(1))[:300])
                print(f"[{who}] body[:500]:", re.sub(r"\s+", " ", t[:500]))
            return
        except Exception as e:
            print(f"[{who}] EXC {type(e).__name__}: {e}")
    print(f"[{who}] 多次失败")

try_upload("投标人A", mint(cfg["accounts"]["bidders"][0]["uid"]))
try_upload("项目经理", mint(cfg["accounts"]["manager"]["uid"]))
