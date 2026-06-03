# -*- coding: utf-8 -*-
"""Page object: 招投标审查平台 - 登录页.

选择器均来自对线上渲染 DOM 的实测 (antd 5 + React 18):
  - 三个登录 Tab 用稳定属性 data-node-key 定位: wxLogin / phone / account
  - 微信登录 = open.weixin.qq.com/connect/qrconnect 的二维码 iframe
  - 手机登录 = #mobile / #smsCode + 「获取验证码」按钮
  - 账号登录 = #username / #password
  - 登录按钮统一带 class `sfc-login`
  - 页脚链接: 帮助 / 隐私 / 条款
"""

import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class LoginPage:
    PATH = "/"

    # --- 登录方式 Tab (data-node-key 为 antd 内部稳定标识) ---
    TAB_WECHAT = (By.CSS_SELECTOR, "div.ant-tabs-tab[data-node-key='wxLogin']")
    TAB_PHONE = (By.CSS_SELECTOR, "div.ant-tabs-tab[data-node-key='phone']")
    TAB_ACCOUNT = (By.CSS_SELECTOR, "div.ant-tabs-tab[data-node-key='account']")
    ANY_TAB = (By.CSS_SELECTOR, "div.ant-tabs-tab")
    ACTIVE_WECHAT = (By.CSS_SELECTOR, "div.ant-tabs-tab-active[data-node-key='wxLogin']")

    # --- 微信扫码 iframe ---
    WECHAT_QR_IFRAME = (By.CSS_SELECTOR, "iframe[src*='qrconnect']")

    # --- 手机登录 ---
    PHONE_INPUT = (By.ID, "mobile")
    SMS_CODE_INPUT = (By.ID, "smsCode")
    GET_CODE_BUTTON = (By.XPATH, "//button[normalize-space()='获取验证码']")

    # --- 账号登录 ---
    USERNAME_INPUT = (By.ID, "username")
    PASSWORD_INPUT = (By.ID, "password")

    # --- 登录提交按钮 (手机/账号两个 Tab 共用同一 class) ---
    LOGIN_BUTTON = (By.CSS_SELECTOR, "button.sfc-login")

    # --- antd 表单必填校验提示 / 腾讯滑块验证码 iframe ---
    FORM_ERRORS = (By.CSS_SELECTOR, ".ant-form-item-explain-error")
    CAPTCHA_IFRAME = (By.CSS_SELECTOR, "iframe[id*='tcaptcha'], iframe[src*='captcha']")

    # --- 页脚 ---
    LINK_HELP = (By.XPATH, "//a[normalize-space()='帮助'] | //*[normalize-space(text())='帮助']")
    LINK_PRIVACY = (By.XPATH, "//a[normalize-space()='隐私'] | //*[normalize-space(text())='隐私']")
    LINK_TERMS = (By.XPATH, "//a[normalize-space()='条款'] | //*[normalize-space(text())='条款']")

    TAB_KEY = {"wxLogin": TAB_WECHAT, "phone": TAB_PHONE, "account": TAB_ACCOUNT}

    def __init__(self, driver, base_url: str, timeout: int = 20):
        self.driver = driver
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.wait = WebDriverWait(driver, timeout)

    # ---------- 打开页面 (含 SPA 挂载重试) ----------
    def open(self, max_attempts: int = 5):
        """打开登录页并等待 React 挂载; 未挂载时刷新重试."""
        for attempt in range(max_attempts):
            try:
                self.driver.get(f"{self.base_url}{self.PATH}")
            except Exception:
                # eager 策略下偶发的加载超时可忽略
                pass
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located(self.ANY_TAB)
                )
                time.sleep(1)  # 给 antd 动画/内容渲染一点缓冲
                return self
            except Exception:
                if attempt < max_attempts - 1:
                    try:
                        self.driver.refresh()
                    except Exception:
                        pass
        raise AssertionError("登录页未能渲染出登录 Tab (SPA 挂载失败)")

    # ---------- 通用 ----------
    def wait_visible(self, locator):
        return self.wait.until(EC.visibility_of_element_located(locator))

    def has_visible(self, locator) -> bool:
        try:
            return self.driver.find_element(*locator).is_displayed()
        except Exception:
            return False

    # ---------- Tab 操作 ----------
    def click_tab(self, key: str):
        """key 取值: 'wxLogin' / 'phone' / 'account'."""
        locator = self.TAB_KEY[key]
        tab = self.wait.until(EC.element_to_be_clickable(locator))
        self.driver.execute_script("arguments[0].click();", tab)
        # 等待该 Tab 真正激活, 并给 antd 切换动画/表单挂载留出缓冲
        try:
            WebDriverWait(self.driver, 8).until(lambda d: self.active_tab_key() == key)
        except Exception:
            pass
        time.sleep(1.2)

    def active_tab_key(self) -> str:
        el = self.driver.find_element(By.CSS_SELECTOR, "div.ant-tabs-tab-active")
        return el.get_attribute("data-node-key")

    # ---------- 表单 ----------
    def fill_account(self, username: str, password: str):
        self.wait_visible(self.USERNAME_INPUT).clear()
        self.driver.find_element(*self.USERNAME_INPUT).send_keys(username)
        self.driver.find_element(*self.PASSWORD_INPUT).clear()
        self.driver.find_element(*self.PASSWORD_INPUT).send_keys(password)

    def fill_phone(self, mobile: str):
        self.wait_visible(self.PHONE_INPUT).clear()
        self.driver.find_element(*self.PHONE_INPUT).send_keys(mobile)

    def value_of(self, locator) -> str:
        return self.driver.find_element(*locator).get_attribute("value")

    # ---------- 提交与校验 ----------
    def submit(self):
        self.wait.until(EC.element_to_be_clickable(self.LOGIN_BUTTON)).click()

    def wait_form_errors(self, timeout: int = 8):
        """等待并返回 antd 必填校验提示文案列表."""
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(self.FORM_ERRORS)
            )
        except Exception:
            pass
        return [
            e.text.strip()
            for e in self.driver.find_elements(*self.FORM_ERRORS)
            if e.text.strip()
        ]

    def submit_expecting_errors(self, attempts: int = 3, timeout: int = 5):
        """点击登录并返回必填校验提示.

        antd 在 React 重渲染期间偶发出现点击未触发的情况, 故最多重试 attempts 次,
        直到出现校验提示为止.
        """
        self.wait_visible(self.USERNAME_INPUT)  # 确保账号表单已渲染
        errors = []
        for _ in range(attempts):
            self.submit()
            errors = self.wait_form_errors(timeout)
            if errors:
                break
            time.sleep(0.5)
        return errors

    def wait_captcha_visible(self, timeout: int = 10) -> bool:
        """提交后等待腾讯滑块验证码 iframe 变为可见."""
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: any(
                    el.is_displayed() for el in d.find_elements(*self.CAPTCHA_IFRAME)
                )
            )
            return True
        except Exception:
            return False
