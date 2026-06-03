# -*- coding: utf-8 -*-
"""招投标审查平台 - 登录页 UI 测试 (选择器均经线上 DOM 实测).

运行:
  pip install -r requirements.txt
  pytest test_login_page.py -v
  # 默认有头运行该地址: https://www.detection.shanxiguandian.com
  # 自定义地址:  pytest --base-url https://你的环境
  # 无头(可能不稳定): pytest --headless

说明:
  - 微信扫码 + 腾讯验证码无法被自动化通过, 因此这里只测"登录页布局与交互",
    不断言登录成功. 登录后功能请用"先扫码一次, 存 Cookie 复用"的方式另测.
"""

import pytest

from pages.login_page import LoginPage


@pytest.mark.ui
class TestLoginPageLayout:
    """页面结构与静态元素."""

    def test_title_is_login(self, login_page):
        """用例1: 登录页文档标题应为「登录」."""
        login_page.open()
        from selenium.webdriver.support.ui import WebDriverWait
        WebDriverWait(login_page.driver, 15).until(lambda d: d.title == "登录")
        assert login_page.driver.title == "登录"

    def test_three_login_tabs_visible(self, login_page):
        """用例2: 应展示微信/手机/账号三种登录方式 Tab."""
        login_page.open()
        wechat = login_page.wait_visible(LoginPage.TAB_WECHAT)
        phone = login_page.wait_visible(LoginPage.TAB_PHONE)
        account = login_page.wait_visible(LoginPage.TAB_ACCOUNT)
        assert "微信登录" in wechat.text
        assert "手机登录" in phone.text
        assert "账号登录" in account.text

    def test_default_tab_is_wechat(self, login_page):
        """用例3: 默认选中的 Tab 应为「微信登录」."""
        login_page.open()
        assert login_page.active_tab_key() == "wxLogin"

    def test_footer_links_present(self, login_page):
        """用例4: 页脚帮助/隐私/条款链接可见."""
        login_page.open()
        assert login_page.has_visible(LoginPage.LINK_HELP)
        assert login_page.has_visible(LoginPage.LINK_PRIVACY)
        assert login_page.has_visible(LoginPage.LINK_TERMS)


@pytest.mark.ui
class TestWeChatLoginTab:
    """微信登录 (默认 Tab)."""

    def test_wechat_qr_iframe_present(self, login_page):
        """用例5: 微信登录下应嵌入微信扫码 iframe(qrconnect)."""
        login_page.open()
        iframe = login_page.wait_visible(LoginPage.WECHAT_QR_IFRAME)
        src = iframe.get_attribute("src")
        assert "open.weixin.qq.com" in src and "qrconnect" in src

    def test_wechat_iframe_has_appid(self, login_page):
        """用例6: 微信扫码 iframe 的 URL 应携带 appid 参数."""
        login_page.open()
        src = login_page.driver.find_element(*LoginPage.WECHAT_QR_IFRAME).get_attribute("src")
        assert "appid=wx" in src


@pytest.mark.ui
class TestPhoneLoginTab:
    """手机登录 Tab."""

    def test_switch_to_phone_shows_fields(self, login_page):
        """用例7: 切到手机登录, 应出现手机号、验证码输入与「获取验证码」按钮."""
        login_page.open()
        login_page.click_tab("phone")
        assert login_page.active_tab_key() == "phone"
        assert login_page.has_visible(LoginPage.PHONE_INPUT)
        assert login_page.has_visible(LoginPage.SMS_CODE_INPUT)
        assert login_page.has_visible(LoginPage.GET_CODE_BUTTON)
        assert login_page.has_visible(LoginPage.LOGIN_BUTTON)

    def test_phone_field_placeholders(self, login_page):
        """用例8: 手机号/验证码输入框 placeholder 文案正确."""
        login_page.open()
        login_page.click_tab("phone")
        mobile = login_page.driver.find_element(*LoginPage.PHONE_INPUT)
        sms = login_page.driver.find_element(*LoginPage.SMS_CODE_INPUT)
        assert mobile.get_attribute("placeholder") == "请输入手机号"
        assert sms.get_attribute("placeholder") == "请输入验证码"

    def test_phone_input_accepts_text(self, login_page):
        """用例9: 手机号输入框可正常输入."""
        login_page.open()
        login_page.click_tab("phone")
        login_page.fill_phone("13800138000")
        assert login_page.value_of(LoginPage.PHONE_INPUT) == "13800138000"


@pytest.mark.ui
class TestAccountLoginTab:
    """账号登录 Tab."""

    def test_switch_to_account_shows_fields(self, login_page):
        """用例10: 切到账号登录, 应出现用户名与密码输入框."""
        login_page.open()
        login_page.click_tab("account")
        assert login_page.active_tab_key() == "account"
        assert login_page.has_visible(LoginPage.USERNAME_INPUT)
        assert login_page.has_visible(LoginPage.PASSWORD_INPUT)
        assert login_page.has_visible(LoginPage.LOGIN_BUTTON)

    def test_password_field_is_masked(self, login_page):
        """用例11: 密码框 type 应为 password(掩码)."""
        login_page.open()
        login_page.click_tab("account")
        pwd = login_page.driver.find_element(*LoginPage.PASSWORD_INPUT)
        assert pwd.get_attribute("type") == "password"

    def test_account_inputs_accept_text(self, login_page):
        """用例12: 用户名/密码输入框可正常输入."""
        login_page.open()
        login_page.click_tab("account")
        login_page.fill_account("test_user", "secret123")
        assert login_page.value_of(LoginPage.USERNAME_INPUT) == "test_user"
        assert login_page.value_of(LoginPage.PASSWORD_INPUT) == "secret123"


@pytest.mark.ui
class TestAccountLoginValidation:
    """账号登录的必填校验 (无需真实登录即可验证)."""

    def test_empty_submit_shows_required_errors(self, login_page):
        """用例15: 账号密码均为空点击登录, 应提示两个必填错误且不跳转."""
        login_page.open()
        login_page.click_tab("account")
        errors = login_page.submit_expecting_errors()
        assert len(errors) >= 2, f"应出现账号与密码必填提示, 实际: {errors}"
        assert any("不能为空" in e for e in errors)
        assert "/login" in login_page.driver.current_url

    def test_only_username_requires_password(self, login_page):
        """用例16: 只填用户名点击登录, 应提示密码必填."""
        login_page.open()
        login_page.click_tab("account")
        login_page.driver.find_element(*LoginPage.USERNAME_INPUT).send_keys("i5cjpv")
        errors = login_page.submit_expecting_errors()
        assert any("密码" in e and "不能为空" in e for e in errors), f"实际: {errors}"

    def test_only_password_requires_account(self, login_page):
        """用例17: 只填密码点击登录, 应提示账号必填."""
        login_page.open()
        login_page.click_tab("account")
        login_page.driver.find_element(*LoginPage.PASSWORD_INPUT).send_keys("Test123456")
        errors = login_page.submit_expecting_errors()
        assert any("账号" in e and "不能为空" in e for e in errors), f"实际: {errors}"

    def test_errors_cleared_after_filling(self, login_page, credentials):
        """用例18: 触发必填错误后, 填入账号密码, 错误提示应消失."""
        login_page.open()
        login_page.click_tab("account")
        assert login_page.submit_expecting_errors(), "应先出现必填错误"
        login_page.fill_account(credentials["username"], credentials["password"])
        import time
        time.sleep(1)
        assert not login_page.driver.find_elements(*LoginPage.FORM_ERRORS), "填入后错误应清除"


@pytest.mark.ui
class TestAccountLoginSubmit:
    """账号登录提交流程 (使用真实凭证, 但会被验证码拦截, 不断言登录成功)."""

    def test_valid_credentials_trigger_captcha(self, login_page, credentials):
        """用例19: 填入正确账号密码点击登录, 应弹出腾讯滑块验证码(进入验证码环节)."""
        login_page.open()
        login_page.click_tab("account")
        login_page.fill_account(credentials["username"], credentials["password"])
        # 提交前账号/密码值应已正确写入
        assert login_page.value_of(LoginPage.USERNAME_INPUT) == credentials["username"]
        login_page.submit()
        # 校验应通过(无必填错误), 并触发滑块验证码
        assert not login_page.driver.find_elements(*LoginPage.FORM_ERRORS)
        assert login_page.wait_captcha_visible(), "提交后应弹出腾讯滑块验证码"

    def test_login_blocked_by_captcha_no_session(self, login_page, credentials):
        """用例20: 因无法自动通过滑块验证码, 登录不会完成(仍停留在登录页)."""
        login_page.open()
        login_page.click_tab("account")
        login_page.fill_account(credentials["username"], credentials["password"])
        login_page.submit()
        login_page.wait_captcha_visible()
        import time
        time.sleep(3)
        assert "/login" in login_page.driver.current_url, "未通过验证码不应跳转登录成功"


@pytest.mark.ui
class TestTabSwitching:
    """Tab 之间来回切换."""

    def test_switch_phone_then_back_to_wechat(self, login_page):
        """用例13: 切到手机登录再切回微信, 微信 iframe 应再次出现."""
        login_page.open()
        login_page.click_tab("phone")
        assert login_page.active_tab_key() == "phone"
        login_page.click_tab("wxLogin")
        assert login_page.active_tab_key() == "wxLogin"
        assert login_page.has_visible(LoginPage.WECHAT_QR_IFRAME)

    def test_account_fields_gone_after_switch_to_phone(self, login_page):
        """用例14: 从账号登录切到手机登录后, 账号专属字段(#username)应消失."""
        login_page.open()
        login_page.click_tab("account")
        assert login_page.has_visible(LoginPage.USERNAME_INPUT)
        login_page.click_tab("phone")
        assert not login_page.has_visible(LoginPage.USERNAME_INPUT)
        assert login_page.has_visible(LoginPage.PHONE_INPUT)
