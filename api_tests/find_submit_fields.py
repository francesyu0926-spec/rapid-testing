# -*- coding: utf-8 -*-
"""从站点静态资源里搜索 submitFile 相关字段名。"""
import re, sys, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import requests
requests.packages.urllib3.disable_warnings()

base = "https://www.bidding.shanxiguandian.com"
r = requests.get(base + "/", verify=False, timeout=30)
scripts = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', r.text)
print("js count:", len(scripts))
keywords = ("submitFile", "服务期限", "交货地点", "投标报价", "service", "period", "limit_time")
for src in scripts[:30]:
    url = src if src.startswith("http") else base + src
    try:
        js = requests.get(url, verify=False, timeout=20).text
    except Exception:
        continue
    for kw in keywords:
        if kw in js:
            idx = js.find(kw)
            print(f"\n== {url[-60:]} :: {kw} ==")
            print(re.sub(r"\s+", " ", js[max(0, idx-80):idx+120])[:200])
