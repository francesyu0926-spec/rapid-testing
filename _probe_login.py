# -*- coding: utf-8 -*-
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

URL = "https://www.detection.shanxiguandian.com/"
USER, PWD = "i5cjpv", "Test123456"

opt = Options()
opt.add_argument("--window-size=1440,900")
opt.add_argument("--lang=zh-CN")
opt.add_argument("--disable-blink-features=AutomationControlled")
d = webdriver.Chrome(options=opt)
d.set_page_load_timeout(30)

def open_login():
    for _ in range(5):
        try: d.get(URL)
        except Exception: pass
        try:
            WebDriverWait(d, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".ant-tabs-tab")))
            time.sleep(1); return True
        except Exception:
            try: d.refresh()
            except Exception: pass
    return False

def snap(tag):
    print(f"\n--- {tag} ---")
    print("url:", d.current_url)
    print("title:", d.title)
    msgs = d.find_elements(By.CSS_SELECTOR, ".ant-message-notice, .ant-message")
    print("ant-message:", [m.text for m in msgs if m.text.strip()])
    errs = d.find_elements(By.CSS_SELECTOR, ".ant-form-item-explain-error")
    print("form-errors:", [e.text for e in errs if e.text.strip()])
    notes = d.find_elements(By.CSS_SELECTOR, ".ant-notification-notice")
    print("notification:", [n.text for n in notes if n.text.strip()])
    caps = d.find_elements(By.CSS_SELECTOR, "iframe[id*='tcaptcha'], iframe[src*='captcha']")
    print("captcha-iframes:", [(c.get_attribute('id'), c.is_displayed()) for c in caps])

try:
    assert open_login(), "not mounted"
    tab = WebDriverWait(d, 10).until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, ".ant-tabs-tab[data-node-key='account'] .ant-tabs-tab-btn")))
    d.execute_script("arguments[0].click();", tab)
    time.sleep(1)

    # 1) 空提交
    d.find_element(By.CSS_SELECTOR, "button.sfc-login").click()
    time.sleep(1.5)
    snap("empty submit")

    # 2) 填正确账号密码提交
    d.find_element(By.ID, "username").clear(); d.find_element(By.ID, "username").send_keys(USER)
    d.find_element(By.ID, "password").clear(); d.find_element(By.ID, "password").send_keys(PWD)
    d.find_element(By.CSS_SELECTOR, "button.sfc-login").click()
    time.sleep(3)
    snap("after correct submit")
    d.save_screenshot("probe_after_submit.png")

    # 3) 再等一会, 看是否跳转
    time.sleep(4)
    snap("after wait")
    print("\ncookies:", [c['name'] for c in d.get_cookies()])
finally:
    time.sleep(1)
    d.quit()
