# -*- coding: utf-8 -*-
"""扫描每个项目下各公司的“主投标文件”(<公司>投标文件.pdf)及大小。"""
import os, sys, functools
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print = functools.partial(print, flush=True)

ROOT = r"D:\文件\测试项目资料"
folders = sys.argv[1].split(",") if len(sys.argv) > 1 else [
    "项目001-工程施建", "项目002-工程施建", "项目003-工程施建",
    "项目004-货物采购", "项目005-工程施建"]


def main_bid(company_dir):
    """返回该公司目录下的主投标文件(名字含‘投标文件’且不是子项)。"""
    cands = []
    for f in os.listdir(company_dir):
        p = os.path.join(company_dir, f)
        if os.path.isfile(p) and f.lower().endswith(".pdf") and "投标文件" in f \
                and "招标文件" not in f and "差异表" not in f:
            cands.append((os.path.getsize(p), p))
    cands.sort()  # 取最小的那个“投标文件”作为可上传候选
    return cands


for fol in folders:
    base = os.path.join(ROOT, fol)
    if not os.path.isdir(base):
        print(f"\n## {fol}  (不存在)"); continue
    comps = [d for d in sorted(os.listdir(base))
             if os.path.isdir(os.path.join(base, d)) and d.endswith("的投标文件")]
    print(f"\n## {fol}  共 {len(comps)} 家投标公司")
    rows = []
    for c in comps:
        cd = os.path.join(base, c)
        cands = main_bid(cd)
        if cands:
            sz, p = cands[0]
            rows.append((sz, c.replace("的投标文件", ""), os.path.basename(p)))
    rows.sort()
    for sz, comp, fn in rows[:6]:
        print(f"  {sz//1024:>7}KB  {comp}  | {fn}")
