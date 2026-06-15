# -*- coding: utf-8 -*-
"""投标人递交投标文件：每家用各自公司的【完整】投标文件，逐个上传（不复用链接）。

用法：
  python submit_bids.py 2029                  # 演练
  python submit_bids.py 2027,2028,2029,2030,2031 --do   # 真实递交
  python open_bidding.py --do                   # file_end 调到过去
  python sync_tender.py 2027,...,2031 --do      # 同步进 tender/myList
"""
import os, sys, json, time, argparse, functools, datetime
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml, requests
requests.packages.urllib3.disable_warnings()
from admin_client import AdminClient

ROOT = r"D:\文件\测试项目资料"
PROJECT_FOLDER = {
    2031: "项目001-工程施建",
    2030: "项目003-工程施建",
    2029: "项目002-工程施建",
    2028: "项目004-货物采购",
    2027: "项目005-工程施建",
}
_EXCLUDE = ("技术部分", "商务部分", "差异表", "招标文件", "清单", "承诺",
            "保证金", "报价", "须知", "封面")
BID_PASSWORD = "123456"  # 加密密码须 6 位


def list_companies(folder):
    base = os.path.join(ROOT, folder)
    return [os.path.join(base, d) for d in sorted(os.listdir(base))
            if os.path.isdir(os.path.join(base, d)) and d.endswith("的投标文件")]


def choose_bid_file(company_dir):
    """完整《<公司>投标文件.pdf》：含「投标文件」、排除分册后取最大者。"""
    tf = []
    for f in os.listdir(company_dir):
        p = os.path.join(company_dir, f)
        if os.path.isfile(p) and f.lower().endswith(".pdf") \
                and "投标文件" in f and not any(x in f for x in _EXCLUDE):
            tf.append((os.path.getsize(p), p))
    if not tf:
        return None
    tf.sort()
    return tf[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids")
    ap.add_argument("--do", action="store_true")
    ap.add_argument("--amount", default="990000", help="投标报价")
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.split(",") if x.strip()]

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    base = cfg["base_url"].rstrip("/"); adm = cfg["admin"]
    ac = AdminClient(base, adm["prefix"], adm.get("php_session", ""), timeout=40,
                     verify_ssl=False, username=adm.get("username", ""),
                     password=adm.get("password", ""))
    S = requests.Session()
    bidders = cfg["accounts"]["bidders"]

    def _do(sess, method, url, tries=6, **kw):
        kw.setdefault("verify", False); kw.setdefault("timeout", 60)
        last = None
        for _ in range(tries):
            try:
                r = sess.request(method, url, **kw)
                try:
                    return r.json(), r
                except Exception:
                    return {"_status": r.status_code, "_text": (r.text or "")[:200]}, r
            except Exception as e:
                last = e; time.sleep(2)
        return {"_error": str(last)}, None

    def req(method, url, tries=6, **kw):
        return _do(S, method, url, tries=tries, **kw)

    tok = {}
    def token_for(uid):
        if uid not in tok:
            for _ in range(8):
                t = ac.mint_token(uid)
                if t:
                    tok[uid] = t; break
                time.sleep(2)
        return tok.get(uid, "")

    def ensure_paid(rid, btok):
        """递交前确保 pay_state=2（测试环境补单后可能被重置）。"""
        chk, _ = req("GET", base + "/api/project_register/info",
                     headers={"token": btok}, params={"id": rid})
        d = chk.get("data") or {}
        if str(d.get("pay_state")) == "2":
            return True
        keys = ["id", "uid", "project_id", "sections", "company_name",
                "company_address", "legal_name", "contact", "contact_phone",
                "email", "images", "total_deposit", "total_file_price",
                "total_platform_price", "status"]
        payload = {k: d.get(k) for k in keys if d.get(k) is not None}
        payload["pay_state"] = 2
        payload["pay_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not isinstance(payload.get("images"), str):
            payload["images"] = json.dumps(payload.get("images") or [], ensure_ascii=False)
        r = ac.session.post(ac._url("/ProjectRegister/save.html"), data=payload,
                            verify=False, timeout=30,
                            headers={"referer": ac._url(f"/ProjectRegister/edit.html?id={rid}")})
        try:
            return r.json().get("code") == 1
        except Exception:
            return False

    def find_tender(btok, pid):
        """从 tender/myList 取 tender_id（≠ project_id）及 apply_id。"""
        tl, _ = req("GET", base + "/api/tender/myList",
                    headers={"token": btok}, params={"page": 1, "limit": 50})
        d = tl.get("data")
        rows = d.get("list", []) if isinstance(d, dict) else (d or [])
        for row in rows:
            if str(row.get("project_id")) == str(pid):
                return (row.get("tender_id"), row.get("section_id"),
                        row.get("apply_id"))
        return None, None, None

    summary = []
    for pid in ids:
        folder = PROJECT_FOLDER.get(pid)
        if not folder:
            print(f"[{pid}] 无项目文件夹映射，跳过"); continue
        mgr = token_for(cfg["accounts"]["manager"]["uid"])
        info, _ = req("GET", base + "/api/publicity/projectInfo",
                      headers={"token": mgr}, params={"project_id": pid})
        d = info.get("data") or {}
        secs = d.get("sections") or []
        sid = secs[0]["id"] if secs else 0
        print(f"\n{'='*64}\n项目 {pid} | {d.get('title','')}\n"
              f" 源={folder} section_id={sid}\n"
              f" 获取截止={d.get('file_end_time')} 开标={d.get('start_time')}\n{'='*64}")

        chosen = []
        for cdir in list_companies(folder):
            c = choose_bid_file(cdir)
            if c:
                chosen.append((c[0], c[1], os.path.basename(cdir).replace("的投标文件", "")))
        chosen.sort()
        picks = chosen[:len(bidders)]
        if len(picks) < len(bidders):
            print(f"  [注意] 仅找到 {len(picks)} 家完整投标文件")
        for sz, p, comp in picks:
            print(f"  候选: {sz//1024:>6}KB  {comp}  | {os.path.basename(p)}")

        for b, (sz, fpath, comp) in zip(bidders, picks):
            uid = b["uid"]; label = b.get("name", str(uid))
            if not args.do:
                print(f"  [演练] {label} 将递交《{comp}》{os.path.basename(fpath)} ({sz//1024}KB)")
                summary.append((pid, label, comp, "DRY")); continue
            btok = token_for(uid)
            tid, t_sec, apply_id = find_tender(btok, pid)
            if not tid:
                print(f"  {label} 不在 tender/myList，请先运行 sync_tender.py")
                summary.append((pid, label, comp, "NO_TENDER")); continue
            use_sid = t_sec or sid
            rid = apply_id
            ensure_paid(rid, btok)
            up_tries, up_to = 15, 1800
            print(f"  {label} 上传完整投标文件 {sz//1024}KB …(可能较久)")
            with open(fpath, "rb") as f:
                up, _ = req("POST", base + "/api/uploads/uploadImage", tries=up_tries,
                            headers={"token": btok}, timeout=up_to,
                            files={"file": (os.path.basename(fpath), f, "application/pdf")})
            ud = up.get("data") or {}
            url = ud.get("url") if isinstance(ud, dict) else None
            if not url:
                print(f"  {label} 上传失败：{json.dumps(up, ensure_ascii=False)[:160]}")
                summary.append((pid, label, comp, "UPLOAD_FAIL")); continue
            print(f"  {label} 上传成功: {url}")
            files_val = json.dumps([{"name": os.path.basename(fpath), "url": url,
                                      "tempFilePath": url}], ensure_ascii=False)
            sub, _ = req("POST", base + "/api/tender/submitFile", headers={"token": btok},
                         data={
                             "tender_id": tid, "section_id": use_sid, "apply_id": rid,
                             "files": files_val, "amount": args.amount,
                             "address": "山西省太原市", "deadline": "90天",
                             "mobile": "13800000000",
                             "password": BID_PASSWORD, "password_confirm": BID_PASSWORD,
                         })
            ok = sub.get("code") in (1, 200)
            print(f"  {label} 递交 code={sub.get('code')} msg={sub.get('msg')} "
                  f"(register={rid})")
            summary.append((pid, label, comp, "OK" if ok else f"FAIL:{sub.get('msg')}"))

    print("\n" + "=" * 64 + "\n汇总")
    for pid, label, comp, st in summary:
        print(f"  项目{pid} {label} <{comp}>: {st}")


if __name__ == "__main__":
    main()
