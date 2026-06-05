# -*- coding: utf-8 -*-
"""对【已建好的】项目跑：3 家投标人报名 -> 直接置为已支付（后台改 pay_state）。

要点：
  - 报名资质文件复用项目自身已上传的 images 地址，避免再次上传（本环境上行不稳）。
  - 测试环境无真实微信支付，paymentErrorHandler 不会更新 pay_state；
    故缴费用后台 ProjectRegister/save 直接把 pay_state 置为已支付(=2)并补 pay_time。
  - 所有请求带重试，容忍网络抖动。

用法：
  python run_register_pay.py 2027,2028,2029,2030,2031            # 演练
  python run_register_pay.py 2027,2028,2029,2030,2031 --do       # 真实报名+置已支付
"""
import sys, json, time, datetime, argparse, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml, requests
requests.packages.urllib3.disable_warnings()
from admin_client import AdminClient

PAID = 2  # 已支付


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", help="project_id 逗号分隔")
    ap.add_argument("--do", action="store_true", help="真实执行")
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.split(",") if x.strip()]

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    base = cfg["base_url"].rstrip("/"); adm = cfg["admin"]
    ac = AdminClient(base, adm["prefix"], adm.get("php_session", ""), timeout=40,
                     verify_ssl=False, username=adm.get("username", ""),
                     password=adm.get("password", ""))
    S = requests.Session()
    bidders = cfg["accounts"]["bidders"]

    def _do(sess, method, url, **kw):
        kw.setdefault("verify", False); kw.setdefault("timeout", 60)
        last = None
        for _ in range(8):
            try:
                r = sess.request(method, url, **kw)
                try:
                    return r.json(), r
                except Exception:
                    return {"_status": r.status_code, "_text": (r.text or "")[:200]}, r
            except Exception as e:
                last = e; time.sleep(2)
        return {"_error": str(last)}, None

    def req(method, url, **kw):
        return _do(S, method, url, **kw)

    def admin_req(method, url, **kw):
        return _do(ac.session, method, url, **kw)

    def mint(uid):
        for _ in range(8):
            t = ac.mint_token(uid)
            if t:
                return t
            time.sleep(2)
        return ""

    tok = {}  # uid -> token
    def token_for(uid):
        if uid not in tok:
            tok[uid] = mint(uid)
        return tok[uid]

    summary = []
    for pid in ids:
        mgr = token_for(cfg["accounts"]["manager"]["uid"])
        info, _ = req("GET", base + "/api/publicity/projectInfo",
                      headers={"token": mgr}, params={"project_id": pid})
        d = info.get("data") or {}
        title = d.get("title", "")
        secs = d.get("sections") or []
        sid = secs[0]["id"] if secs else 0
        images = d.get("images") or "[]"   # 复用项目已上传文件作为报名资质
        print(f"\n{'='*60}\n项目 {pid} | {title}\n section_id={sid} 招标人={d.get('username')}\n{'='*60}")
        # 把后台会话的“当前项目”切到 pid（save 可能按当前项目校验）
        if args.do:
            admin_req("GET", ac._url("/ProjectRegister/index.html"),
                      params={"tableUniqueStr": "admin_publicityproject_index", "id": pid})

        for b in bidders:
            uid = b["uid"]; label = b.get("name", str(uid))
            btok = token_for(uid)
            if not btok:
                print(f"  {label} 取 token 失败，跳过"); summary.append((pid, label, "TOKEN_FAIL")); continue
            # 先查是否已报名
            chk, _ = req("POST", base + "/api/project_register/check",
                         headers={"token": btok}, data={"project_id": pid, "section_id": sid})
            payload = {
                "project_id": pid, "section_id": sid, "sections": str(sid),
                "company_name": f"{label}有限公司", "company_address": "山西省太原市测试地址",
                "legal_name": "张三", "contact": f"{label}联系人",
                "contact_phone": "13800000000", "email": "test@example.com",
                "images": images,
            }
            rid = None
            if not args.do:
                print(f"  [演练] {label} 将报名 project={pid} section={sid}（复用项目文件作资质）")
                summary.append((pid, label, "DRY")); continue
            reg, _ = req("POST", base + "/api/project_register/register",
                         headers={"token": btok}, data=payload)
            if reg.get("code") in (1, 200):
                rid = (reg.get("data") or {}).get("id") if isinstance(reg.get("data"), dict) else None
                rid = rid or reg.get("register_id") or reg.get("id")
            else:
                # 可能已报名：从 myList 找该项目的报名id
                ml, _ = req("GET", base + "/api/project_register/myList",
                            headers={"token": btok}, params={"page": 1, "limit": 30})
                for row in (ml.get("data") or {}).get("list", []) if isinstance(ml.get("data"), dict) else (ml.get("data") or []):
                    if str(row.get("project_id")) == str(pid):
                        rid = row.get("id"); break
                if not rid:
                    print(f"  {label} 报名失败：{json.dumps(reg, ensure_ascii=False)[:160]}")
                    summary.append((pid, label, "REG_FAIL")); continue
            # 置为已支付：后台 ProjectRegister/save
            save = {
                "id": rid, "uid": uid, "project_id": pid, "sections": str(sid),
                "company_name": payload["company_name"],
                "company_address": payload["company_address"],
                "legal_name": payload["legal_name"], "contact": payload["contact"],
                "contact_phone": payload["contact_phone"], "email": payload["email"],
                "images": images,
                "total_deposit": d.get("deposit", "1"),
                "total_file_price": d.get("file_price", "1"),
                "total_platform_price": d.get("platform_price", "1"),
                "status": 2, "pay_state": PAID,
                "pay_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            sres, _ = admin_req("POST", ac._url("/ProjectRegister/save.html"),
                                data=save, timeout=40,
                                headers={"referer": ac._url(f"/ProjectRegister/edit.html?id={rid}"),
                                         "x-requested-with": "XMLHttpRequest"})
            # 复核
            chk2, _ = req("GET", base + "/api/project_register/info",
                          headers={"token": btok}, params={"id": rid})
            ps = (chk2.get("data") or {}).get("pay_state")
            psn = (chk2.get("data") or {}).get("pay_state_name")
            ok = str(ps) == str(PAID)
            print(f"  {label} register_id={rid} save={sres.get('code')} -> pay_state={ps}({psn}) {'OK' if ok else 'NOT-PAID'}")
            summary.append((pid, label, f"PAID:{psn}" if ok else f"pay_state={ps}"))

    print("\n" + "=" * 60 + "\n汇总")
    for pid, label, st in summary:
        print(f"  项目{pid} {label}: {st}")


if __name__ == "__main__":
    main()
