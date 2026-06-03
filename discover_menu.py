# -*- coding: utf-8 -*-
"""复用登录态打开"登录后"页面, 自动打印导航/菜单等可定位元素, 方便写选择器.

前置: 先跑过 python save_auth_state.py, 生成 auth_state.json.

用法:
  python discover_menu.py
  # 浏览器会注入登录态进入系统, 终端打印菜单/链接/按钮/标题等候选选择器,
  # 同时把渲染后的 HTML 存到 logged_in.html 供你细看. 看完按回车关闭.
"""

import json
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = "https://www.detection.shanxiguandian.com"
AUTH_FILE = Path(__file__).resolve().parent / "auth_state.json"


def sanitize_cookie(cookie: dict) -> dict:
    allowed = ("name", "value", "path", "domain", "secure", "httpOnly", "expiry", "sameSite")
    clean = {k: cookie[k] for k in allowed if k in cookie}
    if "expiry" in clean:
        clean["expiry"] = int(clean["expiry"])
    if clean.get("sameSite") not in ("Strict", "Lax", "None"):
        clean.pop("sameSite", None)
    return clean


def inject_storage(driver, store: str, data: dict):
    for key, value in (data or {}).items():
        driver.execute_script(f"{store}.setItem(arguments[0], arguments[1]);", key, value)


def get_with_retry(driver, url: str, max_attempts: int = 6) -> bool:
    """打开 url, 遇到 ERR_CONNECTION_CLOSED 等偶发错误时重试."""
    for attempt in range(1, max_attempts + 1):
        try:
            driver.get(url)
            return True
        except Exception as e:
            print(f"  第 {attempt} 次打开失败: {type(e).__name__}, 重试中...")
            time.sleep(1.5)
    return False


def block_third_party(driver):
    """屏蔽微信/验证码第三方域, 既避免拖死渲染进程, 也加快 React 挂载."""
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": [
            "*open.weixin.qq.com*", "*qrconnect*", "*res.wx.qq.com*",
            "*captcha.qq.com*", "*turing.captcha*", "*captcha.gtimg.com*", "*tcaptcha*",
        ]})
    except Exception:
        pass


def wait_app_mounted(driver, timeout: int = 30) -> bool:
    """轮询等待 React 把 #root 渲染出内容(脚本极多, 挂载较慢)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            n = driver.execute_script(
                "var r=document.getElementById('root');return r?r.children.length:0;"
            )
            if n and int(n) > 0:
                time.sleep(2)  # 再给内部组件/接口渲染一点缓冲
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main():
    # 可选: 第一个命令行参数指定登录后要探查的路由, 默认探查首页
    target_path = sys.argv[1] if len(sys.argv) > 1 else "/"
    if not target_path.startswith("/"):
        target_path = "/" + target_path

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
        # 注入登录态
        if not get_with_retry(driver, BASE_URL + "/"):
            print("无法打开站点 (网络/服务端偶发), 请稍后重试")
            return
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
        get_with_retry(driver, BASE_URL + target_path)
        if wait_app_mounted(driver, timeout=30):
            print("[ok] React 已挂载, 开始抓取")
        else:
            print("[警告] 等待 30s 后 #root 仍为空, 可能挂载更慢或被重定向, 仍尝试抓取")

        print("=== 当前 URL ===", driver.current_url)
        print("=== 标题 ===", driver.title)
        if "/login" in driver.current_url:
            print("[警告] 仍在登录页, 登录态可能已过期, 请重跑 save_auth_state.py")

        # 1) antd 菜单项
        print("\n=== antd 菜单 (.ant-menu-item / .ant-menu-submenu-title) ===")
        for el in driver.find_elements(By.CSS_SELECTOR, ".ant-menu-item, .ant-menu-submenu-title"):
            t = el.text.strip()
            if t:
                print(f"  text={t!r}  key={el.get_attribute('data-menu-id')!r}")

        # 2) 通用导航 (nav / 角色)
        print("\n=== 导航容器 (nav, [role=navigation], .ant-menu, .ant-layout-sider) ===")
        for el in driver.find_elements(By.CSS_SELECTOR, "nav, [role=navigation], .ant-menu, .ant-layout-sider"):
            print(f"  tag={el.tag_name}  class={el.get_attribute('class')!r}")

        # 3) 链接
        print("\n=== 链接 a (前 40 个有文本的) ===")
        count = 0
        for el in driver.find_elements(By.TAG_NAME, "a"):
            t = el.text.strip()
            if t:
                print(f"  text={t!r}  href={el.get_attribute('href')!r}")
                count += 1
                if count >= 40:
                    break

        # 4) 按钮
        print("\n=== 按钮 button (前 30 个有文本的) ===")
        count = 0
        for el in driver.find_elements(By.TAG_NAME, "button"):
            t = el.text.strip()
            if t:
                print(f"  text={t!r}  class={el.get_attribute('class')!r}")
                count += 1
                if count >= 30:
                    break

        # 5) 标题 h1-h3
        print("\n=== 标题 h1/h2/h3 ===")
        for el in driver.find_elements(By.CSS_SELECTOR, "h1, h2, h3"):
            t = el.text.strip()
            if t:
                print(f"  <{el.tag_name}> {t!r}")

        # 6) 输入框 / 下拉 / 上传
        print("\n=== 输入框 input (前 30 个) ===")
        for el in driver.find_elements(By.TAG_NAME, "input")[:30]:
            print(f"  id={el.get_attribute('id')!r}  type={el.get_attribute('type')!r}  "
                  f"placeholder={el.get_attribute('placeholder')!r}")
        print("\n=== 下拉/选择器 (.ant-select) ===")
        for el in driver.find_elements(By.CSS_SELECTOR, ".ant-select"):
            print(f"  class={el.get_attribute('class')!r}  text={el.text.strip()[:30]!r}")
        print("\n=== 上传组件 (.ant-upload) ===")
        for el in driver.find_elements(By.CSS_SELECTOR, ".ant-upload"):
            print(f"  class={el.get_attribute('class')!r}")

        # 7) 表格表头列名
        print("\n=== 表格表头 (.ant-table-thead th) ===")
        for el in driver.find_elements(By.CSS_SELECTOR, ".ant-table-thead th"):
            t = el.text.strip()
            if t:
                print(f"  列: {t!r}")

        # 8) 标签页 / 分段控制器
        print("\n=== Tab/分段 (.ant-tabs-tab, .ant-segmented-item) ===")
        for el in driver.find_elements(By.CSS_SELECTOR, ".ant-tabs-tab, .ant-segmented-item"):
            t = el.text.strip()
            if t:
                print(f"  {t!r}")

        with open("logged_in.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("\n已保存渲染后 HTML 到 logged_in.html")

        # 交互式运行时停下来让你亲眼看页面; 非交互(被脚本调用)时直接结束
        if sys.stdin and sys.stdin.isatty():
            input("\n看完后按回车关闭浏览器...")
    finally:
        driver.quit()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
