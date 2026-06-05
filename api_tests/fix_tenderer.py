# -*- coding: utf-8 -*-
"""把【已创建】项目的招标人(username)改为从招标文件提取的真实招标方名称。

做法：读 projectInfo 拿到项目所有字段 -> 用项目标题匹配到源招标文件 ->
提取招标人 -> 调后台 PublicityProject/save.html 原地更新 username。

用法：
  python fix_tenderer.py 2031              # 演练：打印将要改成的招标人，不写入
  python fix_tenderer.py 2031 --do         # 真实更新单个
  python fix_tenderer.py 2027,2028,2029,2030,2031 --do   # 批量
"""
import sys, json, argparse, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml, requests
requests.packages.urllib3.disable_warnings()
from admin_client import AdminClient
from tender import find_tender_doc, extract_project_name, extract_tenderer, project_dirs

ROOT = r"D:\文件\测试项目资料"

# 后台 save 需要的项目字段（取自 projectInfo 的列）
SAVE_FIELDS = ["id", "uid", "company_id", "project_no", "title", "is_audit",
               "cate_id", "username", "address", "pattern_id", "start_time",
               "file_start_time", "file_end_time", "price", "deposit",
               "file_price", "platform_price", "is_bid_section", "intro",
               "images", "is_min"]


def build_title_tenderer_map(limit=8):
    m = {}
    for d in project_dirs(ROOT)[:limit]:
        t = find_tender_doc(d)
        if not t:
            continue
        title = extract_project_name(t)
        tenderer = extract_tenderer(t)
        if title and tenderer:
            m[title] = tenderer
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", help="project_id（逗号分隔）")
    ap.add_argument("--do", action="store_true", help="真实更新")
    args = ap.parse_args()
    ids = [int(x) for x in args.ids.split(",") if x.strip()]

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    base = cfg["base_url"].rstrip("/"); adm = cfg["admin"]
    ac = AdminClient(base, adm["prefix"], adm.get("php_session", ""), timeout=30,
                     verify_ssl=False, username=adm.get("username", ""),
                     password=adm.get("password", ""))
    tok = ac.mint_token(cfg["accounts"]["manager"]["uid"])
    H = {"token": tok}

    tmap = build_title_tenderer_map()
    print("标题->招标人 映射：")
    for k, v in tmap.items():
        print(f"  {v}  <=  {k[:30]}")

    for pid in ids:
        info = requests.get(base + "/api/publicity/projectInfo", headers=H,
                            params={"project_id": pid}, verify=False, timeout=30).json()
        d = info.get("data") or {}
        if not isinstance(d, dict) or not d:
            print(f"\n[{pid}] projectInfo 取不到，跳过"); continue
        title = d.get("title", "")
        tenderer = tmap.get(title)
        if not tenderer:
            # 标题可能被截断/规整，做包含匹配
            for k, v in tmap.items():
                if k[:20] in title or title[:20] in k:
                    tenderer = v; break
        print(f"\n[{pid}] {title}")
        print(f"  当前招标人: {d.get('username')}  ->  目标: {tenderer}")
        if not tenderer:
            print("  未匹配到招标人，跳过"); continue
        if not args.do:
            print("  [演练] 未加 --do，不写入"); continue

        payload = {k: d.get(k) for k in SAVE_FIELDS if d.get(k) is not None}
        payload["id"] = pid
        payload["username"] = tenderer
        r = ac.session.post(ac._url("/PublicityProject/save.html"),
                            data=payload, verify=False, timeout=30,
                            headers={"referer": ac._url(f"/PublicityProject/edit.html?id={pid}")})
        try:
            res = r.json()
        except Exception:
            print(f"  save 返回非JSON: {r.status_code} {r.text[:160]}"); continue
        print(f"  save: code={res.get('code')} msg={res.get('msg')}")
        # 复核
        info2 = requests.get(base + "/api/publicity/projectInfo", headers=H,
                             params={"project_id": pid}, verify=False, timeout=30).json()
        print(f"  复核招标人: {(info2.get('data') or {}).get('username')}")


if __name__ == "__main__":
    main()
