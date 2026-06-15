# -*- coding: utf-8 -*-
"""下钻「投标文件校验」每家"查看"子报告，补全证据链。

子报告页(URL .../quick-check/{pid}/bidding-task/{taskId})含 3 个评审块：
  投标规范校验 / 报价评估 / 技术方案评估
每块有汇总计数(已满足/不满足/待核验)与结果明细表。

逐家抓取这些计数与明细行，写 evidence_drilldown.json，用于区分：
  - 模型漏判：子报告也 暂无数据 / 不满足=0
  - 汇总未呈现：子报告里 不满足>0 但列表汇总列仍显示"合格"

用法：
  python drilldown_quickcheck.py                 # 下钻 GT 三项目全部投标人
  python drilldown_quickcheck.py --projects P1-COMPLIANCE
"""
import argparse
import functools
import json
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pages.project_page import ProjectPage
from pages.project_detail_page import ProjectDetailPage
from batch_create_execute import make_driver, inject_auth, BASE, AUTH

TABS = ("投标规范校验", "报价评估", "技术方案评估")

# 在「投标文件校验」表里，点 操作列里 含某 core 串的那一行的"查看"
CLICK_VIEW_FOR_UNIT_JS = r"""
var sec='投标文件校验', core=arguments[0];
var all=Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,div,span,p'));
var head=null;
for(var i=0;i<all.length;i++){var t=(all[i].innerText||'').trim();
  if(t===sec||(t.indexOf(sec)===0&&t.length<sec.length+8)){head=all[i];break;}}
if(!head)return {ok:false,msg:'no head'};
var tables=Array.from(document.querySelectorAll('.ant-table'));
var hp=head.getBoundingClientRect().top+window.scrollY,best=null,bd=1e9;
tables.forEach(function(tb){var tp=tb.getBoundingClientRect().top+window.scrollY;
  var d=tp-hp; if(d>=-5&&d<bd){bd=d;best=tb;}});
if(!best)return {ok:false,msg:'no table'};
var rows=Array.from(best.querySelectorAll('.ant-table-tbody tr.ant-table-row'));
for(var j=0;j<rows.length;j++){
  var rt=(rows[j].innerText||'').replace(/\s/g,'');
  if(core && rt.indexOf(core)>=0){
    var links=Array.from(rows[j].querySelectorAll('a,button'));
    var v=links.find(function(e){return (e.innerText||'').indexOf('查看')>=0;});
    if(v){v.scrollIntoView({block:'center'}); v.click();
      return {ok:true, rowtext:(rows[j].innerText||'').trim()};}
  }
}
return {ok:false,msg:'no row/view for '+core};
"""

# 抓当前激活 tab 面板里的汇总计数 + 结果明细表 + 面板文本样本
GRAB_BLOCK_JS = r"""
var out={counts:{}, headers:[], rows:[], empty:true, panel:''};
var scope=document.querySelector('.ant-tabs-tabpane-active') || document.body;
var txt=scope.innerText||'';
out.panel=txt.slice(0,500);
['已满足','不满足','待核验','满足','合计'].forEach(function(k){
  var m=txt.match(new RegExp(k+'\\s*\\n?\\s*(\\d+)'));
  if(m)out.counts[k]=parseInt(m[1]);
});
var tables=Array.from(scope.querySelectorAll('.ant-table'));
if(!tables.length)return out;
var tb=tables[tables.length-1];
out.headers=Array.from(tb.querySelectorAll('.ant-table-thead th')).map(
  function(e){return (e.innerText||'').trim();});
out.empty=!!tb.querySelector('.ant-table-placeholder');
out.rows=Array.from(tb.querySelectorAll('.ant-table-tbody tr.ant-table-row')).map(
  function(r){return Array.from(r.querySelectorAll('td')).map(
    function(c){return (c.innerText||'').trim();});});
return out;
"""


def core_name(unit):
    s = re.sub(r"\s", "", unit)
    for suf in ("建设工程有限公司", "建设有限公司", "工程有限公司", "有限公司", "公司"):
        if s.endswith(suf):
            return s[:-len(suf)]
    return s


def click_tab(d, label):
    # 优先点 antd 标签页 tab，其次任意可见同文本元素
    sels = [f"//div[contains(@class,'ant-tabs-tab')][normalize-space(.)='{label}']",
            f"//*[@role='tab'][normalize-space(.)='{label}']",
            f"//*[normalize-space(text())='{label}']"]
    for xp in sels:
        for e in d.find_elements("xpath", xp):
            try:
                if e.is_displayed():
                    d.execute_script("arguments[0].click();", e)
                    return True
            except Exception:
                continue
    return False


def click_view_with_paging(d, core, max_pages=5):
    """在投标文件校验表里点该家查看；找不到则翻页再试。"""
    for _ in range(max_pages):
        r = d.execute_script(CLICK_VIEW_FOR_UNIT_JS, core)
        if r.get("ok"):
            return r
        nxt = d.find_elements("css selector",
                              ".ant-pagination-next:not(.ant-pagination-disabled)")
        if not nxt:
            return r
        try:
            d.execute_script("arguments[0].click();", nxt[0])
            time.sleep(1.2)
        except Exception:
            return r
    return {"ok": False, "msg": "not found after paging"}


def scrape_subreport(d):
    """在子报告页，逐块(投标规范校验/报价评估/技术方案评估)抓计数+明细。"""
    blocks = {}
    for tab in TABS:
        click_tab(d, tab)
        time.sleep(1.5)
        try:
            res = d.execute_script(GRAB_BLOCK_JS)
        except Exception:
            res = {}
        blocks[tab] = res or {}
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default="gt_out/ground_truth.json")
    ap.add_argument("--projects", default="")
    ap.add_argument("--out", default="evidence_drilldown.json")
    args = ap.parse_args()

    gt = json.load(open(args.gt, encoding="utf-8"))
    want = [s.strip() for s in args.projects.split(",") if s.strip()]
    targets = [p for p in gt["projects"]
               if p["id"] != "STRESS" and (not want or p["id"] in want)]

    state = json.loads(Path(AUTH).read_text(encoding="utf-8"))
    d = make_driver()
    out = {"projects": []}
    try:
        inject_auth(d, state)
        page = ProjectPage(d, BASE)
        detail = ProjectDetailPage(d, BASE)
        for p in targets:
            name = p["name"]
            units = [fr["unit"] for fr in p["files"] if fr.get("format") == "pdf"]
            print(f"\n=== 下钻 [{p['id']}] {len(units)}家 ===")
            page.ensure_quick_check_loaded(attempts=3, timeout=20)
            if not page.enter_quick_check_detail_by_name(name, timeout=15):
                print(f"  进详情失败"); continue
            detail.wait_loaded(timeout=20)
            detail.wait_content(markers=("投标文件校验",), timeout=25)
            detail_url = d.current_url.split("?")[0]

            prec = []
            for u in units:
                core = core_name(u)
                r = {"ok": False, "msg": "init"}
                for attempt in range(3):
                    d.get(detail_url)
                    detail.wait_content(markers=("投标文件校验",), timeout=20)
                    d.execute_script(
                        "var a=Array.from(document.querySelectorAll('*')).find("
                        "e=>(e.innerText||'').trim()==='投标文件校验');"
                        "if(a)a.scrollIntoView({block:'center'});")
                    time.sleep(1.2 + attempt)
                    r = click_view_with_paging(d, core)
                    if r.get("ok"):
                        break
                if not r.get("ok"):
                    print(f"  {u}: 未点到查看({r.get('msg')})")
                    prec.append({"unit": u, "error": r.get("msg")}); continue
                time.sleep(3.5)
                blocks = scrape_subreport(d)
                tot_unmet = sum(int(b.get("counts", {}).get("不满足", 0) or 0)
                                for b in blocks.values())
                tot_rows = sum(len(b.get("rows", []) or []) for b in blocks.values())
                summary = {t: {"counts": blocks[t].get("counts", {}),
                               "rows": len(blocks[t].get("rows", []) or []),
                               "empty": blocks[t].get("empty", True)} for t in TABS}
                print(f"  {u}: 不满足合计={tot_unmet} 明细行合计={tot_rows} "
                      f"{ {t: summary[t]['counts'] for t in TABS} }")
                prec.append({"unit": u, "sub_url": d.current_url.split("?")[0],
                             "unmet_total": tot_unmet, "rows_total": tot_rows,
                             "blocks": blocks})
            out["projects"].append({"id": p["id"], "name": name, "files": prec})
    finally:
        d.quit()

    json.dump(out, open(args.out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n证据链: {args.out}")


if __name__ == "__main__":
    main()
