# -*- coding: utf-8 -*-
"""投标人角色: 在"我的任务/任务列表"用"新建项目"创建项目(项目名 + 单个投标文件PDF<=500MB).

与快检"新建项目"不同: 投标人表单只需 1) 项目名称 2) 上传一个投标文件PDF(<=500MB), 然后"创建".
脚本会先把账号 i5cjpv 的角色切到"投标人员"(右上角角色下拉, 服务端持久化).

用法:
  python bidder_create.py                 # 前10个项目, 各取一个<=500MB的投标文件
  python bidder_create.py --count 10 --start 0 --auth auth_state.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

from selenium.webdriver.common.by import By

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pages.project_page import ProjectPage  # noqa (确保 pages 可导入)
from batch_create_execute import BASE, MAT, make_driver, inject_auth, resolve, extract_project_name

MAX_BYTES = 500 * 1024 * 1024  # 500MB 限制


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def pick_bid_pdf(proj: Path):
    """真实主投标文件: 取各家"XX投标文件.pdf"中最小者(仍是真实主投标文件, 挑小的以缩短上传).
    退化: 若无主投标文件, 用项目内最小有效PDF.
    """
    bidder_dirs = [d for d in sorted(proj.iterdir())
                   if d.is_dir() and d.name.endswith("的投标文件")]
    mains = []  # (size, unit, path)
    for d in bidder_dirs:
        unit = d.name[: -len("的投标文件")]
        main = d / f"{unit}投标文件.pdf"
        if main.exists() and main.stat().st_size <= MAX_BYTES:
            mains.append((main.stat().st_size, unit, main))
    if mains:
        mains.sort(key=lambda x: x[0])
        return mains[0][1], mains[0][2]
    # 退化: 项目内最小的有效PDF
    pdfs = sorted([p for p in proj.rglob("*.pdf")
                   if 0 < p.stat().st_size <= MAX_BYTES],
                  key=lambda p: p.stat().st_size)
    if pdfs:
        return proj.name, pdfs[0]
    return None, None


def project_name(proj: Path) -> str:
    td = proj / "招标文件"
    cand = list(td.rglob("招标文件正文.pdf")) if td.exists() else []
    if not cand:
        cand = list(proj.rglob("招标文件正文.pdf"))
    if cand:
        nm = extract_project_name(str(cand[0]))
        if nm:
            return nm
    return proj.name


# ---------- 角色切换 ----------
def role_select(d):
    roles = ("项目经理", "投标人员", "评审专家")
    for s in d.find_elements(By.CSS_SELECTOR, ".ant-layout-header .ant-select"):
        try:
            if any(r in (s.text or "") for r in roles):
                return s
        except Exception:
            continue
    return None


def _wait_role_select(d, timeout=30):
    """等待 header 角色 select 渲染出真实角色名(项目经理/投标人员/评审专家)."""
    roles = ("项目经理", "投标人员", "评审专家")
    end = time.time() + timeout
    while time.time() < end:
        sel = role_select(d)
        if sel is not None:
            t = (sel.text or "").strip()
            if any(r in t for r in roles):
                return sel
        time.sleep(1)
    return None


def _select_role(d, role_name: str) -> bool:
    """打开角色 select 并选中指定角色项."""
    sel = role_select(d)
    if sel is None:
        return False
    try:
        sel.click()
    except Exception:
        try:
            d.execute_script("arguments[0].click();", sel)
        except Exception:
            return False
    time.sleep(1.2)
    for o in d.find_elements(By.CSS_SELECTOR, ".ant-select-dropdown .ant-select-item-option"):
        try:
            if o.is_displayed() and role_name in o.text:
                d.execute_script("arguments[0].click();", o)
                return True
        except Exception:
            continue
    return False


def has_new_btn(d) -> bool:
    return any(b.is_displayed() for b in d.find_elements(*NEW_BTN))


def _wait_new_btn_present(d, timeout) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if has_new_btn(d):
            return True
        time.sleep(0.5)
    return False


def switch_to_bidder(d) -> bool:
    """真正切到投标人员: 操作 header 角色 select 选"投标人员", 等"新建项目"按钮真正出现.
    注意: 角色仅在本次会话内生效, 重开浏览器会默认回"项目经理"; 切换后切勿再 d.get 导航(会被重定向回 my-projects)."""
    sel = _wait_role_select(d, 30)
    if sel is None:
        log("  未找到角色切换 select")
        return False
    cur = (sel.text or "").strip()
    log(f"  当前角色: {cur}")
    # 已是投标人员且新建按钮已在 => 直接成功
    if "投标人员" in cur and has_new_btn(d):
        return True
    for attempt in range(4):
        # 若当前已显示投标人员但按钮未出现, 需先切到项目经理再切回以强制触发导航
        cur = (role_select(d).text or "").strip() if role_select(d) else ""
        if "投标人员" in cur:
            _select_role(d, "项目经理")
            time.sleep(1.5)
        if _select_role(d, "投标人员"):
            if _wait_new_btn_present(d, 18):
                return True
        log(f"  第{attempt+1}次切换后未见'新建项目', 重试")
        time.sleep(1.5)
    return has_new_btn(d)


# ---------- 新建项目(投标人) ----------
NEW_BTN = (By.XPATH, "//button[contains(normalize-space(),'新建项目')]")
DRAWER = (By.CSS_SELECTOR, ".ant-drawer, .ant-modal")
NAME_INPUT = (By.CSS_SELECTOR,
              ".ant-drawer input[placeholder='请输入'], .ant-modal input[placeholder='请输入']")
FILE_INPUT = (By.CSS_SELECTOR, ".ant-drawer input[type='file'], .ant-modal input[type='file']")
CREATE_BTN = (By.XPATH, "//div[contains(@class,'ant-drawer') or contains(@class,'ant-modal')]"
                        "//button[contains(.,'创') and contains(.,'建')]")
CANCEL_BTN = (By.XPATH, "//div[contains(@class,'ant-drawer') or contains(@class,'ant-modal')]"
                        "//button[contains(.,'取') and contains(.,'消')]")


def form_open(d) -> bool:
    for e in d.find_elements(*NAME_INPUT):
        try:
            if e.is_displayed():
                return True
        except Exception:
            continue
    return False


def _wait_new_btn(d, timeout):
    end = time.time() + timeout
    while time.time() < end:
        btns = [b for b in d.find_elements(*NEW_BTN) if b.is_displayed()]
        if btns:
            return btns
        time.sleep(0.5)
    return []


def open_form(d, timeout=15) -> bool:
    btns = _wait_new_btn(d, timeout)
    if not btns:
        # "新建项目"不在 => 角色多半已回退到项目经理, 重新切换(不要 d.get, 否则被重定向)
        log("  '新建项目'缺失, 重新切换投标人员")
        switch_to_bidder(d)
        btns = _wait_new_btn(d, 5)
    if not btns:
        return False
    for _ in range(3):
        try:
            d.execute_script("arguments[0].click();", btns[0])
        except Exception:
            pass
        e = time.time() + 5
        while time.time() < e:
            if form_open(d):
                time.sleep(0.8)
                return True
            time.sleep(0.3)
    return form_open(d)


UPLOAD_TRIGGER = (By.XPATH, "//*[text()='点击上传']")
PROGRESS = (By.CSS_SELECTOR, ".ant-modal-body .ant-progress, .ant-drawer-body .ant-progress, "
                            ".ant-modal .ant-progress, .ant-drawer .ant-progress")


def upload_percents(d) -> list:
    out = []
    for p in d.find_elements(*PROGRESS):
        v = None
        inner = p.find_elements(By.CSS_SELECTOR, "[aria-valuenow]")
        if inner:
            v = inner[0].get_attribute("aria-valuenow")
        else:
            v = p.get_attribute("aria-valuenow")
        try:
            out.append(int(float(v)))
        except (TypeError, ValueError):
            pass
    return out


def cancel(d):
    try:
        for b in d.find_elements(*CANCEL_BTN):
            if b.is_displayed():
                d.execute_script("arguments[0].click();", b)
                break
        time.sleep(1)
        # 可能有确认退出
        for o in d.find_elements(By.XPATH, "//button[contains(.,'确') and contains(.,'定')]"):
            if o.is_displayed():
                d.execute_script("arguments[0].click();", o)
                break
    except Exception:
        pass


def create_one(d, name: str, pdf: Path, upload_timeout=600) -> str:
    if not open_form(d, timeout=15):
        return "失败(未打开新建抽屉)"
    # 项目名称
    inputs = [e for e in d.find_elements(*NAME_INPUT) if e.is_displayed()]
    if not inputs:
        cancel(d)
        return "失败(无项目名称输入框)"
    try:
        inputs[0].clear()
        inputs[0].send_keys(name[:80])
    except Exception:
        pass
    # 选择投标文件
    fis = d.find_elements(*FILE_INPUT)
    if not fis:
        cancel(d)
        return "失败(无文件输入)"
    try:
        fis[0].send_keys(str(pdf))
    except Exception as e:
        cancel(d)
        return f"失败(send_keys异常:{e})"
    time.sleep(1)
    # 关键: 选择文件只是"暂存", 必须点"点击上传"才真正开始上传
    trg = d.find_elements(*UPLOAD_TRIGGER)
    if not trg:
        cancel(d)
        return "失败(未出现'点击上传')"
    d.execute_script("arguments[0].click();", trg[-1])
    log(f"  已选并触发上传 {pdf.name} ({pdf.stat().st_size/1024/1024:.0f}MB), 等待100%...")
    end = time.time() + upload_timeout
    last = -1
    last_change = time.time()
    stall_limit = 240  # 进度连续 240s 不动 => 判停滞
    ok = False
    while time.time() < end:
        pcts = upload_percents(d)
        if pcts and all(p >= 100 for p in pcts):
            ok = True
            break
        if pcts and pcts[0] != last:
            log(f"    上传 {pcts[0]}%")
            last = pcts[0]
            last_change = time.time()
        if time.time() - last_change > stall_limit:
            cancel(d)
            return f"失败(上传停滞@{last}%)"
        time.sleep(2)
    if not ok:
        cancel(d)
        return "失败(上传超时)"
    # 创建
    btns = [b for b in d.find_elements(*CREATE_BTN) if b.is_displayed()]
    if not btns:
        cancel(d)
        return "失败(无创建按钮)"
    d.execute_script("arguments[0].click();", btns[0])
    end = time.time() + 60
    while time.time() < end and form_open(d):
        time.sleep(1.5)
    if form_open(d):
        cancel(d)
        return "失败(创建后抽屉未关闭)"
    return "成功(已创建)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth", default="auth_state.json")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--upload-timeout", type=int, default=600)
    ap.add_argument("--skip-names", default="", help="逗号分隔, 项目名含其一即跳过(如已建过的)")
    args = ap.parse_args()
    skips = [s for s in args.skip_names.split(",") if s]

    auth = Path(args.auth)
    state = json.loads(auth.read_text(encoding="utf-8"))
    projs = sorted([p for p in MAT.iterdir() if p.is_dir()])[args.start:args.start + args.count]
    log(f"待创建项目: {len(projs)} 个 (start={args.start})")

    d = make_driver()
    results = {}
    try:
        inject_auth(d, state)
        d.get(BASE + "/")
        time.sleep(8)
        if not switch_to_bidder(d):
            log("切换到投标人员失败, 终止")
            return
        log(f"已切到投标人员, URL={d.current_url}")
        for i, proj in enumerate(projs, start=args.start + 1):
            if any(s in proj.name for s in skips):
                results[proj.name] = "跳过(--skip-names)"
                log(f"=== [{i}] {proj.name} -> 跳过 ===")
                continue
            log(f"=== [{i}] {proj.name} ===")
            unit, pdf = pick_bid_pdf(proj)
            if not pdf:
                results[proj.name] = "跳过(无<=500MB的投标PDF)"
                log(f"  -> {results[proj.name]}")
                continue
            name = project_name(proj)
            log(f"  项目名={name[:36]}  投标文件={pdf.name}")
            try:
                r = create_one(d, name, pdf, args.upload_timeout)
            except Exception as e:
                r = f"异常({type(e).__name__}: {e})"
                try:
                    cancel(d)
                except Exception:
                    pass
            results[proj.name] = r
            log(f"  -> {r}")
            # 回到任务列表(创建后通常已在列表)
            time.sleep(1)
    finally:
        try:
            d.quit()
        except Exception:
            pass

    print("\n" + "=" * 60, flush=True)
    print("投标人新建项目结果:", flush=True)
    ok = 0
    for k, v in results.items():
        if str(v).startswith("成功"):
            ok += 1
        print(f"  {k}: {v}", flush=True)
    print(f"\n成功 {ok}/{len(results)}", flush=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
