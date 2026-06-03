# -*- coding: utf-8 -*-
"""深度探查"快检项目"列表页, 并自动点进第一个项目, 打印详情页结构.

前置: 已运行 save_auth_state.py 生成 auth_state.json.
用法: python explore_quickcheck.py
"""

import json
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

BASE_URL = "https://www.detection.shanxiguandian.com"
QUICK_CHECK = "/ai/my-projects/quick-check"
AUTH_FILE = Path(__file__).resolve().parent / "auth_state.json"

# 可选: 第一个命令行参数指定要探查的登录后路由
TARGET_PATH = sys.argv[1] if len(sys.argv) > 1 else QUICK_CHECK
if not TARGET_PATH.startswith("/"):
    TARGET_PATH = "/" + TARGET_PATH


def sanitize_cookie(c: dict) -> dict:
    allowed = ("name", "value", "path", "domain", "secure", "httpOnly", "expiry", "sameSite")
    clean = {k: c[k] for k in allowed if k in c}
    if "expiry" in clean:
        clean["expiry"] = int(clean["expiry"])
    if clean.get("sameSite") not in ("Strict", "Lax", "None"):
        clean.pop("sameSite", None)
    return clean


def inject_storage(driver, store, data):
    for k, v in (data or {}).items():
        try:
            driver.execute_script(f"window.{store}.setItem(arguments[0], arguments[1]);", k, v)
        except Exception:
            pass


def safe_get(driver, url, attempts=6):
    for _ in range(attempts):
        try:
            driver.get(url)
            return True
        except Exception:
            time.sleep(1.5)
    return False


def block_third_party(driver):
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": [
            "*open.weixin.qq.com*", "*qrconnect*", "*res.wx.qq.com*",
            "*captcha.qq.com*", "*turing.captcha*", "*captcha.gtimg.com*", "*tcaptcha*",
        ]})
    except Exception:
        pass


def wait_mounted(driver, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            n = driver.execute_script(
                "var r=document.getElementById('root');return r?r.children.length:0;")
            if n and int(n) > 0:
                time.sleep(3)
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def dump_page(driver, tag):
    print(f"\n{'='*70}\n[{tag}] URL={driver.current_url}  TITLE={driver.title!r}\n{'='*70}")

    print("\n--- body 可见文本 (前 2500 字) ---")
    try:
        txt = driver.execute_script("return document.body.innerText;") or ""
        print(txt[:2500])
    except Exception as e:
        print("读取失败:", e)

    print("\n--- 按钮 (text / aria-label / title) ---")
    for el in driver.find_elements(By.CSS_SELECTOR, "button, .ant-btn"):
        t = (el.text or "").strip()
        al = el.get_attribute("aria-label")
        ti = el.get_attribute("title")
        cls = el.get_attribute("class")
        if t or al or ti:
            print(f"  text={t!r} aria={al!r} title={ti!r} class={cls!r}")

    print("\n--- 表格行 (.ant-table-row / tr[data-row-key]) ---")
    rows = driver.find_elements(By.CSS_SELECTOR, ".ant-table-row, tr[data-row-key]")
    print(f"  共 {len(rows)} 行")
    for el in rows[:5]:
        print(f"  row: {el.text.strip()[:120]!r}")

    print("\n--- 卡片/列表项 (.ant-card, .ant-list-item, .ant-pro-card, [class*=item]) ---")
    cards = driver.find_elements(By.CSS_SELECTOR, ".ant-card, .ant-list-item, .ant-pro-card")
    print(f"  共 {len(cards)} 个卡片类元素")
    for el in cards[:5]:
        print(f"  card: {el.text.strip()[:120]!r}  class={el.get_attribute('class')!r}")

    print("\n--- Tab / 分段 ---")
    for el in driver.find_elements(By.CSS_SELECTOR, ".ant-tabs-tab, .ant-segmented-item"):
        t = el.text.strip()
        if t:
            print(f"  {t!r}")

    print("\n--- 表头列 ---")
    for el in driver.find_elements(By.CSS_SELECTOR, ".ant-table-thead th"):
        t = el.text.strip()
        if t:
            print(f"  列: {t!r}")


def main():
    if not AUTH_FILE.exists():
        print(f"未找到 {AUTH_FILE}, 请先运行: python save_auth_state.py")
        return
    state = json.loads(AUTH_FILE.read_text(encoding="utf-8"))

    options = Options()
    options.add_argument("--window-size=1440,900")
    options.add_argument("--lang=zh-CN")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.page_load_strategy = "eager"
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(30)
    try:
        block_third_party(driver)
        safe_get(driver, BASE_URL + "/")
        try:
            driver.delete_all_cookies()
        except Exception:
            pass
        for c in state.get("cookies", []):
            try:
                driver.add_cookie(sanitize_cookie(c))
            except Exception:
                pass
        inject_storage(driver, "localStorage", state.get("local_storage", {}))
        inject_storage(driver, "sessionStorage", state.get("session_storage", {}))
        safe_get(driver, BASE_URL + TARGET_PATH)
        wait_mounted(driver)
        time.sleep(3)  # 列表数据异步

        dump_page(driver, f"列表页 {TARGET_PATH}")

        with open("quickcheck_list.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)

        # 项目经理只能查看"已开标"项目(开标中/后), 故优先点"开标中"的行
        print("\n\n############ 尝试点进一个'开标中'项目 ############")
        clicked = False
        url_before = driver.current_url
        rows = driver.find_elements(By.CSS_SELECTOR, ".ant-table-row, tr[data-row-key]")
        target_row = None
        for r in rows:
            if "开标中" in r.text:
                target_row = r
                break
        if target_row is None and rows:
            target_row = rows[0]

        if target_row is not None:
            print(f"目标行: {target_row.text.strip()[:80]!r}")
            # 先点整行
            driver.execute_script("arguments[0].click();", target_row)
            time.sleep(3)
            if driver.current_url == url_before:
                # 行点击无效, 尝试点该行项目名称单元格里的可点击元素
                cells = target_row.find_elements(By.CSS_SELECTOR, "td a, td .ant-btn, td span[class*=link], td")
                for c in cells:
                    if c.text.strip():
                        print(f"再点单元格: {c.text.strip()[:40]!r}")
                        driver.execute_script("arguments[0].click();", c)
                        time.sleep(2)
                        if driver.current_url != url_before:
                            break
            clicked = driver.current_url != url_before

        if clicked or driver.current_url != url_before:
            clicked = True
        if clicked:
            time.sleep(4)
            dump_page(driver, "点击后的页面(详情?)")
            with open("quickcheck_detail.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
        else:
            print("未找到可点击的项目入口(列表可能为空)")

        print("\n已保存 quickcheck_list.html / quickcheck_detail.html")
        if sys.stdin and sys.stdin.isatty():
            input("\n按回车关闭浏览器...")
    finally:
        driver.quit()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
