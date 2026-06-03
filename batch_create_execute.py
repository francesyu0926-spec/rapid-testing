# -*- coding: utf-8 -*-
"""批量: 对测试资料前 N 个项目, 完整执行"创建快检项目(招标+前K家投标) + 点击执行(文件校验)".

项目名称从招标文件首页标题提取(不乱输入); 备案文件不上传.
会在系统产生真实项目并触发后端检测. 逐项目带日志, 单项目失败不影响其余.

用法:
  python batch_create_execute.py                  # 前16项目, 每项目前3家投标
  python batch_create_execute.py --count 16 --bidders 3
  python batch_create_execute.py --start 5        # 从第6个(0基)开始, 便于断点续跑
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

BASE = "https://www.detection.shanxiguandian.com"
AUTH = Path(__file__).resolve().parent / "auth_state.json"
MAT = Path(r"D:\文件\测试项目资料")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def extract_project_name(tender_pdf: str) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(tender_pdf)
        text = reader.pages[0].extract_text() or ""
    except Exception:
        return ""
    out = []
    for line in text.splitlines():
        s = re.sub(r"\s", "", line)
        if not s:
            continue
        if "招标文件" in s or "招标编号" in s or "招标公告" in s:
            break
        out.append(line)
    return re.sub(r"\s+", "", "".join(out))[:80]


def resolve(proj: Path, max_bidders: int):
    td = proj / "招标文件"
    cand = list(td.rglob("招标文件正文.pdf")) if td.exists() else []
    if not cand:
        cand = list(proj.rglob("招标文件正文.pdf"))
    if not cand and td.exists():
        cand = sorted(td.rglob("*.pdf"))
    tender = str(cand[0]) if cand else None
    bidders = []
    for d in sorted(proj.iterdir()):
        if d.is_dir() and d.name.endswith("的投标文件"):
            unit = d.name[: -len("的投标文件")]
            main = d / f"{unit}投标文件.pdf"
            if not main.exists():
                pdfs = sorted(d.glob("*.pdf"), key=lambda p: p.stat().st_size, reverse=True)
                main = pdfs[0] if pdfs else None
            if main and main.exists():
                bidders.append((unit, str(main)))
        if len(bidders) >= max_bidders:
            break
    return tender, bidders


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


def process_one(page: ProjectPage, proj: Path, max_bidders: int, upload_timeout: int) -> str:
    tender, bidders = resolve(proj, max_bidders)
    if not tender or len(bidders) < 1:
        return f"跳过(资料不全 招标={bool(tender)} 投标={len(bidders)})"
    name = extract_project_name(tender) or proj.name
    log(f"  项目名: {name}  招标=1 投标={len(bidders)}家")

    if not page.ensure_quick_check_loaded(attempts=4, timeout=25):
        return "失败(快检列表未加载)"
    if not page.open_new_project_modal(timeout=15):
        return "失败(未打开新建抽屉)"

    def _cb(done, total, percents):
        log(f"  上传进度: 第{done}/{total}份完成 percents={percents}")

    log(f"  开始逐个上传(招标+{len(bidders)}家)...")
    if not page.fill_and_upload_sequential(name, tender, bidders, record_pdf=None,
                                           per_file_timeout=upload_timeout, progress_cb=_cb):
        page.cancel_modal()
        return f"失败(上传超时/异常 进度={page.upload_percents()})"
    log(f"  上传完成, 提交 ...")
    if not page.submit_new_project():
        page.cancel_modal()
        return "失败(无提交按钮)"
    end = time.time() + 90
    while time.time() < end and page.new_project_form_open():
        time.sleep(2)
    if page.new_project_form_open():
        page.cancel_modal()
        return "失败(提交后抽屉未关闭)"
    log(f"  已提交, 在列表中点击执行 ...")
    page.ensure_quick_check_loaded(attempts=3, timeout=20)
    if page.click_execute(name, timeout=25):
        return "成功(已创建+已点执行)"
    return "部分(已创建, 但未点到执行)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=16)
    ap.add_argument("--bidders", type=int, default=3)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--upload-timeout", type=int, default=900)
    args = ap.parse_args()

    state = json.loads(AUTH.read_text(encoding="utf-8"))
    projs = sorted([p for p in MAT.iterdir() if p.is_dir()])[args.start:args.count]
    log(f"待处理项目: {len(projs)} 个 (start={args.start}, bidders={args.bidders})")

    d = make_driver()
    results = {}
    try:
        inject_auth(d, state)
        page = ProjectPage(d, BASE)
        for i, proj in enumerate(projs, start=args.start + 1):
            log(f"=== [{i}] {proj.name} ===")
            try:
                r = process_one(page, proj, args.bidders, args.upload_timeout)
            except Exception as e:
                r = f"异常({type(e).__name__}: {e})"
                try:
                    page.cancel_modal()
                except Exception:
                    pass
            results[proj.name] = r
            log(f"  -> {r}")
    finally:
        d.quit()

    print("\n" + "=" * 60, flush=True)
    print("批量结果汇总:", flush=True)
    ok = 0
    for name, r in results.items():
        if r.startswith("成功"):
            ok += 1
        print(f"  {name}: {r}", flush=True)
    print(f"\n成功 {ok}/{len(results)}", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
