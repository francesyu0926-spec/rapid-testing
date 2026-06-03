# -*- coding: utf-8 -*-
"""轮询快检列表任务状态, 对"已完成"项目进详情, 校验界面结果与上传的招投标文件一致.

可确定性比对项(界面"事实"是否与上传文件一致, 不评判 AI 的围标/串标结论):
  1) 项目名称: 详情页应出现取自招标文件首页的项目名;
  2) 投标单位: 上传的前 K 家投标单位名称应在详情页(查重/文件属性/报价规律/投标次数等模块)出现;
  3) 投标家数: 详情页出现的我方上传单位数应等于上传家数.
功能逻辑参考需求说明书 4.3.2(快检详情展示) / 3.3(各检测项定义).

期望值(项目名 + 前 K 家投标单位)直接复用 batch_create_execute 的解析逻辑, 与当初创建时一致.

用法:
  python verify_results.py                       # 轮询前16项目, 每项目前3家, 最长等60分钟
  python verify_results.py --count 16 --bidders 3 --poll-minutes 60
  python verify_results.py --no-wait             # 只看当前已完成的, 不等待
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pages.project_page import ProjectPage
from batch_create_execute import BASE, AUTH, MAT, extract_project_name, resolve


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def make_driver():
    o = Options()
    for a in ("--window-size=1440,900", "--lang=zh-CN", "--disable-gpu",
              "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage",
              "--no-sandbox", "--disable-extensions",
              "--disable-background-timer-throttling", "--disable-renderer-backgrounding"):
        o.add_argument(a)
    o.page_load_strategy = "eager"
    d = webdriver.Chrome(options=o)
    d.set_page_load_timeout(40)
    return d


def inject_auth(d, state):
    d.execute_cdp_cmd("Network.enable", {})
    d.execute_cdp_cmd("Network.setBlockedURLs", {"urls": [
        "*open.weixin.qq.com*", "*qrconnect*", "*res.wx.qq.com*", "*tcaptcha*"]})
    for _ in range(6):
        try:
            d.get(BASE + "/")
            if (d.current_url or "").startswith("http"):
                break
        except Exception:
            pass
        time.sleep(1)
    for k, v in (state.get("local_storage") or {}).items():
        try:
            d.execute_script("window.localStorage.setItem(arguments[0],arguments[1]);", k, v)
        except Exception:
            pass


def build_expected(count: int, bidders: int) -> dict:
    """{项目名(归一化无空白): {'name':原名,'units':[前K家单位],'folder':名}}."""
    exp = {}
    projs = sorted([p for p in MAT.iterdir() if p.is_dir()])[:count]
    for proj in projs:
        tender, bd = resolve(proj, bidders)
        if not tender:
            continue
        name = extract_project_name(tender) or proj.name
        units = [u for u, _ in bd]
        exp[re.sub(r"\s", "", name)] = {"name": name, "units": units, "folder": proj.name}
    return exp


def norm(s: str) -> str:
    return re.sub(r"\s", "", s or "")


def verify_one(page: ProjectPage, name: str, expected: dict) -> dict:
    """进详情, 比对项目名/投标单位/家数, 返回结果字典."""
    if not page.enter_quick_check_detail_by_name(name, timeout=15):
        return {"ok": False, "detail": "未能进入详情"}
    blob = page.quick_check_detail_blob(settle=5)
    nblob = norm(blob)
    name_hit = norm(expected["name"])[:20] in nblob if expected["name"] else False
    units = expected["units"]
    unit_hits = [u for u in units if norm(u) and norm(u) in nblob]
    res = {
        "ok": True,
        "name_hit": name_hit,
        "units_total": len(units),
        "units_found": len(unit_hits),
        "units_missing": [u for u in units if u not in unit_hits],
        "blob_len": len(blob),
    }
    res["consistent"] = name_hit and len(unit_hits) == len(units) and len(units) > 0
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=16)
    ap.add_argument("--bidders", type=int, default=3)
    ap.add_argument("--poll-minutes", type=int, default=60)
    ap.add_argument("--interval", type=int, default=60, help="轮询间隔秒")
    ap.add_argument("--no-wait", action="store_true", help="只看当前已完成, 不等待")
    args = ap.parse_args()

    state = json.loads(AUTH.read_text(encoding="utf-8"))
    expected = build_expected(args.count, args.bidders)
    log(f"期望项目: {len(expected)} 个 (每项目前 {args.bidders} 家投标)")
    for k, v in expected.items():
        log(f"  · {v['name'][:36]} | 单位: {v['units']}")

    d = make_driver()
    verified = {}  # 归一化名 -> 结果
    try:
        inject_auth(d, state)
        page = ProjectPage(d, BASE)
        deadline = time.time() + (0 if args.no_wait else args.poll_minutes * 60)
        round_no = 0
        while True:
            round_no += 1
            if not page.ensure_quick_check_loaded(attempts=4, timeout=25):
                log("快检列表未加载(登录态可能失效, 请重跑 save_auth_state.py)")
                break
            rows = page.qc_list_rows()
            done = [r for r in rows if "已完成" in (r.get("status") or "")]
            log(f"[轮询#{round_no}] 列表 {len(rows)} 行, 已完成 {len(done)} 个; 已校验 {len(verified)} 个")

            for r in done:
                nm = norm(r["name"])
                # 仅校验属于我们期望集合且尚未校验的项目
                match = None
                for k in expected:
                    if k and (k in nm or nm in k):
                        match = k
                        break
                if not match or match in verified:
                    continue
                log(f"  -> 校验已完成项目: {expected[match]['name'][:36]}")
                res = verify_one(page, expected[match]["name"], expected[match])
                verified[match] = res
                tag = "一致" if res.get("consistent") else ("进入失败" if not res.get("ok") else "不一致/部分")
                log(f"     结果[{tag}] 项目名命中={res.get('name_hit')} "
                    f"投标单位 {res.get('units_found')}/{res.get('units_total')} "
                    f"缺失={res.get('units_missing')}")
                page.ensure_quick_check_loaded(attempts=2, timeout=20)

            if len(verified) >= len(expected):
                log("全部期望项目均已完成并校验.")
                break
            if args.no_wait or time.time() >= deadline:
                log("到达等待上限或 --no-wait, 结束轮询.")
                break
            time.sleep(args.interval)
    finally:
        d.quit()

    print("\n" + "=" * 64, flush=True)
    print("快检结果一致性校验汇总:", flush=True)
    ok = 0
    for k, v in expected.items():
        r = verified.get(k)
        if not r:
            print(f"  [未完成/未校验] {v['name'][:42]}", flush=True)
            continue
        if r.get("consistent"):
            ok += 1
            print(f"  [一致]   {v['name'][:42]} | 投标单位 {r['units_found']}/{r['units_total']}", flush=True)
        elif not r.get("ok"):
            print(f"  [进入失败] {v['name'][:42]} | {r.get('detail')}", flush=True)
        else:
            print(f"  [不一致] {v['name'][:42]} | 项目名命中={r['name_hit']} "
                  f"投标单位 {r['units_found']}/{r['units_total']} 缺失={r['units_missing']}", flush=True)
    print(f"\n一致 {ok}/{len(expected)} (已校验 {len(verified)})", flush=True)
    Path("verify_results_out.json").write_text(
        json.dumps({k: verified.get(k) for k in expected}, ensure_ascii=False, indent=2),
        encoding="utf-8")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
