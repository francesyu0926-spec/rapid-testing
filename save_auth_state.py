# -*- coding: utf-8 -*-
"""人工登录一次, 保存登录态(Cookie + localStorage + sessionStorage)供自动化复用.

为什么需要它:
  登录页有微信扫码 / 腾讯滑块验证码, 无法被脚本稳定通过. 行业标准做法是:
  人工手动登录成功一次, 把浏览器里的登录态导出到 auth_state.json,
  之后的自动化测试直接注入这份登录态, 跳过登录环节去测"登录后"的功能.

用法:
  python save_auth_state.py
  # 会弹出一个浏览器, 你手动完成: 选登录方式 -> 输入账号密码/扫码 -> 滑动验证码 -> 登录成功
  # 看到已经进入系统(不再停留在 /login)后, 回到终端按回车
  # 脚本会把登录态写入 auth_state.json

可选参数:
  python save_auth_state.py --url https://你的环境 --out auth_state.json
"""

import argparse
import json
import sys
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

DEFAULT_URL = "https://www.detection.shanxiguandian.com/"
DEFAULT_OUT = "auth_state.json"

# 在浏览器里抓取 localStorage / sessionStorage 全量键值
_DUMP_STORAGE_JS = (
    "var s={};for(var i=0;i<%(store)s.length;i++){"
    "var k=%(store)s.key(i);s[k]=%(store)s.getItem(k);}return s;"
)


def dump_storage(driver, store: str) -> dict:
    """store 取 'localStorage' 或 'sessionStorage'."""
    try:
        return driver.execute_script(_DUMP_STORAGE_JS % {"store": store}) or {}
    except Exception:
        return {}


def open_with_retry(driver, url: str, max_attempts: int = 6) -> bool:
    """打开登录页并等待 React 挂载; 遇到 ERR_CONNECTION_CLOSED 等偶发问题时重试.

    站点首个连接偶发被服务器掐断(ERR_CONNECTION_CLOSED), 重试/刷新通常即可恢复.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            driver.get(url)
        except Exception as e:
            print(f"  第 {attempt} 次打开失败: {type(e).__name__}, 重试中...")
            time.sleep(1.5)
            continue
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".ant-tabs-tab"))
            )
            time.sleep(1)
            return True
        except Exception:
            print(f"  第 {attempt} 次未挂载登录表单, 刷新重试...")
            try:
                driver.refresh()
            except Exception:
                pass
            time.sleep(1.5)
    return False


def main():
    parser = argparse.ArgumentParser(description="人工登录并保存登录态")
    parser.add_argument("--url", default=DEFAULT_URL, help="登录页地址")
    parser.add_argument("--out", default=DEFAULT_OUT, help="登录态输出文件")
    args = parser.parse_args()

    options = Options()
    options.add_argument("--window-size=1440,900")
    options.add_argument("--lang=zh-CN")
    # 降低自动化特征, 避免被风控直接拦在验证码环节
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    # 站点含第三方 iframe(微信/验证码), normal 策略可能永不结束; eager 在 DOM 就绪即返回
    options.page_load_strategy = "eager"

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(30)
    try:
        if not open_with_retry(driver, args.url):
            print("\n[错误] 多次重试仍无法打开登录页 (可能网络/服务端偶发).")
            print("       请检查网络后重试, 或稍后再运行本脚本.")
            return
        print("=" * 60)
        print("浏览器已打开, 请在浏览器里手动完成登录:")
        print("  1) 选择登录方式(账号/手机/微信)")
        print("  2) 输入凭证并通过滑块/扫码验证码")
        print("  3) 确认页面已进入系统(地址栏不再是 /login)")
        print("完成后回到本终端, 按回车保存登录态...")
        print("=" * 60)
        input()

        current_url = driver.current_url
        if "/login" in current_url:
            print(f"[警告] 当前仍停留在登录页: {current_url}")
            print("       可能还没登录成功. 仍要保存吗? 直接回车保存, 输入 n 放弃: ", end="")
            if input().strip().lower() == "n":
                print("已放弃保存.")
                return

        state = {
            "url": args.url,
            "current_url": current_url,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "cookies": driver.get_cookies(),
            "local_storage": dump_storage(driver, "localStorage"),
            "session_storage": dump_storage(driver, "sessionStorage"),
        }

        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        print(f"\n登录态已保存到 {args.out}")
        print(f"  cookies: {len(state['cookies'])} 个")
        print(f"  localStorage: {len(state['local_storage'])} 项")
        print(f"  sessionStorage: {len(state['session_storage'])} 项")
        print("\n现在可以运行登录后测试:  pytest test_authenticated.py -v")
    finally:
        time.sleep(1)
        driver.quit()


if __name__ == "__main__":
    # Windows 终端中文输出
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
