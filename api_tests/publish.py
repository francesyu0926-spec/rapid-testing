# -*- coding: utf-8 -*-
"""项目经理：上传招标文件 -> 用返回的文件地址 + 从招标文件提取的项目名称 发布项目。

约定：每个项目文件夹下有 招标文件\招标文件\招标文件正文.pdf；
项目名称从该正文首页提取，招标文件必须上传并写入 images 入参。

用法：
  python publish.py                 # 演练：定位招标文件+提取名称+打印 payload，不创建
  python publish.py --do-create     # 真正创建（默认取第 1 个项目文件夹）
  python publish.py --do-create --count 5     # 取前 5 个项目文件夹各建一个
  python publish.py --do-create --start 6 --count 5   # 从第 6 个开始建 5 个
"""

import sys, os, json, time, argparse, datetime, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)
import yaml, requests
from admin_client import AdminClient
from tender import find_tender_doc, extract_project_name, project_dirs

ROOT = r"D:\文件\测试项目资料"


def retry(fn, tries=6, sleep=2):
    last = None
    for _ in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e; time.sleep(sleep)
    raise last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--do-create", action="store_true", help="真正创建项目")
    ap.add_argument("--count", type=int, default=1, help="创建项目数量")
    ap.add_argument("--start", type=int, default=1, help="从第几个项目文件夹开始(1基)")
    ap.add_argument("--dirs", default="", help="指定项目文件夹名(逗号分隔)，优先于 start/count")
    args = ap.parse_args()

    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    base = cfg["base_url"].rstrip("/"); adm = cfg["admin"]
    ac = AdminClient(base, adm["prefix"], adm.get("php_session", ""), timeout=30,
                     verify_ssl=False, username=adm.get("username", ""),
                     password=adm.get("password", ""))
    S = requests.Session()

    uid = cfg["accounts"]["manager"]["uid"]
    tok = ""
    for _ in range(8):
        tok = ac.mint_token(uid)
        if tok:
            break
        time.sleep(3)
    if not tok:
        print("项目经理 token 签发失败（网络抖动，请重试）"); return
    H = {"token": tok}
    print(f"项目经理 token: {tok[:14]}.. (uid={uid})")

    # 选取项目文件夹
    dirs = project_dirs(ROOT)
    if args.dirs.strip():
        wanted = [s.strip() for s in args.dirs.split(",") if s.strip()]
        targets = [os.path.join(ROOT, w) for w in wanted]
    else:
        start = max(1, args.start) - 1
        targets = dirs[start:start + max(1, args.count)]
    if not targets:
        print("没有可用的项目文件夹"); return
    # 按招标文件大小升序处理：小文件先完成，最大的放最后（本环境上行带宽低）
    def _tsize(d):
        t = find_tender_doc(d)
        return os.path.getsize(t) if t and os.path.exists(t) else 1 << 60
    targets.sort(key=_tsize)

    now = datetime.datetime.now()
    fmt = "%Y-%m-%d %H:%M:%S"
    tomorrow = now + datetime.timedelta(days=1)
    file_start = now - datetime.timedelta(minutes=10)                 # 今天（已开始报名）
    file_end = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)   # 明天
    open_time = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)  # 明天（同一天）
    print(f"获取文件: {file_start.strftime(fmt)} ~ {file_end.strftime(fmt)}；开标: {open_time.strftime(fmt)}")

    ok = 0
    for i, pdir in enumerate(targets, 1):
        folder = os.path.basename(pdir)
        tender = find_tender_doc(pdir)
        if not tender:
            print(f"[{i}] {folder} 未找到招标文件，跳过"); continue
        name = extract_project_name(tender) or folder
        size_kb = os.path.getsize(tender) // 1024
        print(f"\n[{i}/{len(targets)}] {folder}")
        print(f"  招标文件: ...{os.sep}{os.path.relpath(tender, ROOT)} ({size_kb}KB)")
        print(f"  项目名称(取自招标文件): {name}")

        if not args.do_create:
            print("  [演练] 未加 --do-create，仅定位招标文件+提取名称，不上传/不创建。")
            continue

        # 上传招标文件（网络抖动，长超时+多次重试）
        def _up():
            with open(tender, "rb") as f:
                return S.post(base + "/api/uploads/uploadImage", headers=H,
                              files={"file": (os.path.basename(tender), f, "application/pdf")},
                              timeout=100, verify=False)
        try:
            r = retry(_up, tries=25, sleep=2)
            url = (r.json().get("data") or {}).get("url")
        except Exception as e:
            print(f"  上传异常 {type(e).__name__}，跳过"); continue
        if not url:
            print(f"  上传失败: {r.status_code} {r.text[:200]}"); continue
        print(f"  上传成功: {url}")

        images = json.dumps([{"name": url, "tempFilePath": url}], ensure_ascii=False)
        payload = {
            "title": name,
            "username": "接口测试招标人",
            "project_no": f"AUTO{now.strftime('%y%m%d%H%M%S')}{i:02d}",
            "company_id": 1,
            "cate_id": 1,
            "pattern_id": 1,
            "address": "山西省太原市",
            "file_start_time": file_start.strftime(fmt),
            "file_end_time": file_end.strftime(fmt),
            "start_time": open_time.strftime(fmt),
            "price": "1000000",
            "deposit": "1",
            "file_price": "1",
            "platform_price": "1",
            "is_bid_section": 0,
            "is_min": 1,
            "is_audit": 0,
            "intro": f"接口自动发布：{name}",
            "images": images,
        }
        def _create():
            return S.post(base + "/api/publicity/create", headers=H, data=payload,
                          timeout=60, verify=False)
        try:
            res = retry(_create, tries=4).json()
        except Exception as e:
            print(f"  创建异常 {type(e).__name__}"); continue
        if res.get("code") in (1, 200):
            ok += 1
            print(f"  创建成功 ({res.get('msg')})")
        else:
            print(f"  创建失败 code={res.get('code')} msg={res.get('msg')}")

    if args.do_create:
        print(f"\n合计创建成功 {ok}/{len(targets)}")


if __name__ == "__main__":
    main()
