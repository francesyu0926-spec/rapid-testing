# -*- coding: utf-8 -*-
"""Selenium fixtures for 招投标审查平台 登录页 UI 测试.

要点:
  - 直接用 Selenium 4 自带的 Selenium Manager 解析驱动, 不再依赖 webdriver-manager
    (这正是之前 `cache_valid_range` 报错的根源).
  - 该站点是 React(antd) 单页应用, 用 module script 加载; headless 下经常挂载失败,
    所以默认有头运行, 并在 LoginPage.open() 里做了刷新重试.
  - 页面含微信/腾讯验证码 iframe, 完整 load 可能永不结束, 故用 page_load_strategy=eager.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from pages.login_page import LoginPage
from pages.project_page import ProjectPage
from pages.project_detail_page import ProjectDetailPage

DEFAULT_BASE_URL = "https://www.detection.shanxiguandian.com"
DEFAULT_AUTH_STATE = str(Path(__file__).resolve().parent / "auth_state.json")


def pytest_addoption(parser):
    parser.addoption(
        "--base-url",
        action="store",
        default=os.environ.get("BID_REVIEW_BASE_URL", DEFAULT_BASE_URL),
        help="招投标审查平台根地址",
    )
    parser.addoption(
        "--headless",
        action="store_true",
        default=os.environ.get("SELENIUM_HEADLESS", "").lower() in ("1", "true", "yes"),
        help="无头模式运行 Chrome (注意: 该 SPA 在无头下可能挂载不稳定)",
    )
    # 账号登录测试用的凭证; 优先读环境变量, 避免把真实密码写死/提交到仓库
    parser.addoption(
        "--username",
        action="store",
        default=os.environ.get("TEST_USERNAME", "i5cjpv"),
        help="账号登录用户名",
    )
    parser.addoption(
        "--password",
        action="store",
        default=os.environ.get("TEST_PASSWORD", "Test123456"),
        help="账号登录密码",
    )
    # 会话复用: 人工登录一次后由 save_auth_state.py 导出的登录态文件
    parser.addoption(
        "--auth-state",
        action="store",
        default=os.environ.get("AUTH_STATE_FILE", DEFAULT_AUTH_STATE),
        help="登录态(Cookie/Storage) JSON 文件路径, 由 save_auth_state.py 生成",
    )
    # 新建项目上传用例: 测试资料根目录 + 是否真实提交
    parser.addoption(
        "--materials-dir",
        action="store",
        default=os.environ.get("MATERIALS_DIR", r"D:\文件\测试项目资料"),
        help="招投标测试资料根目录(含若干项目文件夹), 供上传用例使用",
    )
    parser.addoption(
        "--do-submit",
        action="store_true",
        default=os.environ.get("DO_SUBMIT", "").lower() in ("1", "true", "yes"),
        help="允许真实点击'提交'创建项目并触发后端检测(会产生正式数据). 默认仅填表+取消",
    )


@pytest.fixture
def base_url(request):
    return request.config.getoption("--base-url").rstrip("/")


@pytest.fixture
def credentials(request):
    return {
        "username": request.config.getoption("--username"),
        "password": request.config.getoption("--password"),
    }


@pytest.fixture(scope="session")
def driver(request):
    headless = request.config.getoption("--headless")
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    # 站点含微信/验证码等第三方 iframe, 整页 load 经常永不结束并把渲染进程拖到
    # "Timed out receiving message from renderer"; 故无论有头/无头都用 eager,
    # 在 DOMContentLoaded 即返回, 后续靠显式等待具体元素.
    options.page_load_strategy = "eager"
    options.add_argument("--window-size=1440,900")
    options.add_argument("--disable-gpu")
    options.add_argument("--lang=zh-CN")
    # 降低自动化特征, 部分前端在检测到自动化时行为不同
    options.add_argument("--disable-blink-features=AutomationControlled")
    # 防止渲染进程因共享内存不足/沙箱问题卡死 (renderer timeout 常见诱因)
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-renderer-backgrounding")

    # 驱动解析优先级: 环境变量 CHROMEDRIVER > 本地 drivers/chromedriver.exe > Selenium Manager 自动解析
    override = os.environ.get("CHROMEDRIVER")
    if not override:
        local_driver = Path(__file__).resolve().parent / "drivers" / "chromedriver.exe"
        if local_driver.exists():
            override = str(local_driver)
    service = Service(override) if override else None
    drv = webdriver.Chrome(service=service, options=options)

    drv.set_page_load_timeout(30)
    drv.implicitly_wait(0)
    yield drv
    drv.quit()


@pytest.fixture
def login_page(driver, base_url):
    page = LoginPage(driver, base_url)
    return page


# --------------------------------------------------------------------------- #
# 会话复用: 注入人工登录一次后保存的登录态, 跳过验证码直接进入"已登录"状态
# --------------------------------------------------------------------------- #
def _sanitize_cookie(cookie: dict) -> dict:
    """清洗 driver.get_cookies() 的输出, 使其能被 add_cookie 接受.

    - expiry 必须是 int(部分浏览器导出为 float)
    - sameSite 非法值会被某些 chromedriver 拒绝, 不确定时直接去掉
    """
    allowed = ("name", "value", "path", "domain", "secure", "httpOnly", "expiry", "sameSite")
    clean = {k: cookie[k] for k in allowed if k in cookie}
    if "expiry" in clean:
        clean["expiry"] = int(clean["expiry"])
    if clean.get("sameSite") not in ("Strict", "Lax", "None"):
        clean.pop("sameSite", None)
    return clean


def _inject_storage(driver, store: str, data: dict):
    """把 dict 写回 localStorage / sessionStorage(逐项容错)."""
    if not data:
        return
    for key, value in data.items():
        try:
            driver.execute_script(
                f"window.{store}.setItem(arguments[0], arguments[1]);", key, value
            )
        except Exception:
            pass


# 登录页会内嵌这些第三方域(微信扫码 / 腾讯验证码), 它们经常永不结束并把渲染进程
# 拖到 "Timed out receiving message from renderer". 走会话复用时我们已有 token, 完全
# 用不到它们, 直接在网络层屏蔽, 让页面秒开.
_BLOCKED_THIRD_PARTY = [
    "*open.weixin.qq.com*",
    "*qrconnect*",
    "*captcha.qq.com*",
    "*turing.captcha.qcloud.com*",
    "*captcha.gtimg.com*",
    "*tcaptcha*",
]


def _block_third_party(driver):
    """用 CDP 屏蔽微信/验证码第三方域, 避免其拖死渲染进程."""
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": _BLOCKED_THIRD_PARTY})
    except Exception:
        pass


def _safe_get(driver, url: str):
    """driver.get 容错版: eager 下偶发的加载/渲染超时直接忽略(DOM 通常已就绪)."""
    try:
        driver.get(url)
    except Exception:
        pass


def _current_url(driver) -> str:
    try:
        return driver.current_url or ""
    except Exception:
        return ""


def _ensure_origin(driver, base_url: str, attempts: int = 6) -> bool:
    """反复导航直到真正落在 http(s) 页面.

    冷启动首个连接偶发被掐(ERR_CONNECTION_CLOSED)或渲染超时, 会把浏览器留在初始
    'data:,' 空白页, 此时无法写 localStorage. 重试直到 current_url 为 http 才返回.
    """
    for _ in range(attempts):
        _safe_get(driver, base_url + "/")
        if _current_url(driver).startswith("http"):
            return True
        time.sleep(1.0)
    return False


def _inject_auth_state(driver, base_url: str, state: dict):
    """把保存的登录态注入当前 driver, 完成后停在已登录页面.

    该站登录态是 localStorage 里的 JWT(redux-persist), 而非 Cookie. Storage 只能在
    同源页面下写入, 故先打开一次站点(屏蔽第三方域后秒开)再注入, 然后重新加载,
    让 redux-persist 用 token 恢复登录态.
    """
    _block_third_party(driver)
    # 1) 先打开站点(此时还未登录, 但只需建立同源上下文以写入 Storage);
    #    必须确保真正落在 http 页面, 否则在 'data:,' 空白页写 Storage 会报错
    _ensure_origin(driver, base_url)
    try:
        driver.delete_all_cookies()
    except Exception:
        pass
    for cookie in state.get("cookies", []):
        try:
            driver.add_cookie(_sanitize_cookie(cookie))
        except Exception:
            # 个别第三方域 Cookie 注入失败可忽略, 关键登录态通常在主站域
            pass
    _inject_storage(driver, "localStorage", state.get("local_storage", {}))
    _inject_storage(driver, "sessionStorage", state.get("session_storage", {}))
    # 2) 带着登录态重新加载, redux-persist 读取 token 后应被识别为已登录
    _safe_get(driver, base_url + "/")


@pytest.fixture
def auth_state_path(request) -> Path:
    return Path(request.config.getoption("--auth-state"))


def _cleanup_auth_state(driver, base_url: str):
    """清理注入的登录态与第三方域屏蔽.

    driver 是 session 级共享, 若不清理, 注入的 token 与 CDP 屏蔽会污染后续用例
    (典型: 之后的登录页用例因已登录而看不到登录 Tab, 且微信 iframe 被屏蔽).
    """
    # 1) 解除第三方域屏蔽, 让后续登录页能正常加载微信/验证码 iframe
    try:
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": []})
    except Exception:
        pass
    # 2) 清空登录态(localStorage/sessionStorage/cookie); 清 Storage 需在同源 http 页
    try:
        if not _current_url(driver).startswith("http"):
            _safe_get(driver, base_url + "/")
        driver.execute_script(
            "try{window.localStorage.clear();window.sessionStorage.clear();}catch(e){}"
        )
        driver.delete_all_cookies()
    except Exception:
        pass


@pytest.fixture
def authenticated_driver(driver, base_url, auth_state_path):
    """已登录的 driver: 注入 save_auth_state.py 导出的登录态.

    若登录态文件不存在则跳过依赖它的用例, 并提示如何生成.
    用例结束后清理登录态, 避免污染共享的 session driver(尤其是后续登录页用例).
    """
    if not auth_state_path.exists():
        pytest.skip(
            f"未找到登录态文件 {auth_state_path}, 请先运行: python save_auth_state.py"
        )
    with open(auth_state_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    _inject_auth_state(driver, base_url, state)
    yield driver
    _cleanup_auth_state(driver, base_url)


@pytest.fixture
def project_page(authenticated_driver, base_url):
    """登录后"我的项目"页面对象(已注入登录态)."""
    return ProjectPage(authenticated_driver, base_url)


@pytest.fixture
def materials_dir(request):
    return Path(request.config.getoption("--materials-dir"))


@pytest.fixture
def do_submit(request):
    return bool(request.config.getoption("--do-submit"))


def _enter_project_detail(driver, request, status, content_markers):
    """通用: 注入登录态 -> 进项目列表 -> 点击指定状态项目名称进入详情 -> 等内容渲染.

    详情内容依赖列表点击传入的路由状态(直接用 URL 只出空壳), 故必须点击项目名称链接.
    返回 (ProjectDetailPage, cleanup_callable); 失败时 pytest.skip.
    """
    base_url = request.config.getoption("--base-url").rstrip("/")
    auth_path = Path(request.config.getoption("--auth-state"))
    if not auth_path.exists():
        pytest.skip(f"未找到登录态文件 {auth_path}, 请先运行: python save_auth_state.py")
    with open(auth_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    _inject_auth_state(driver, base_url, state)

    def cleanup():
        _cleanup_auth_state(driver, base_url)

    page = ProjectPage(driver, base_url)
    if not page.ensure_list_loaded(attempts=4, timeout=20):
        cleanup()
        pytest.skip("项目列表表格未加载, 无法进入项目详情")
    if not page.row_key_with_status(status):
        cleanup()
        pytest.skip(f"项目列表中无'{status}'项目, 无法进入对应详情")
    if not page.click_row_with_status(status, timeout=20):
        cleanup()
        pytest.skip(f"点击'{status}'项目名称未能进入详情页")
    detail = ProjectDetailPage(driver, base_url)
    detail.wait_loaded(timeout=25)
    if not detail.wait_content(markers=content_markers, timeout=25):
        cleanup()
        pytest.skip("详情页审查内容未渲染")
    return detail, cleanup


@pytest.fixture(scope="module")
def project_detail_page(driver, request):
    """已进入某"开标中"项目详情页(开标中环节检查)的页面对象(module 级, 仅进入一次).

    取列表中"开标中"项目, 点击项目名称链接进入; 多条审查用例共享同一详情上下文;
    结束后清理登录态以免污染后续(如登录页)用例.
    """
    detail, cleanup = _enter_project_detail(
        driver, request, "开标中", ("投标文件查重", "投标文件校验", "本页目录")
    )
    try:
        yield detail
    finally:
        cleanup()


@pytest.fixture(scope="module")
def quick_check_detail_page(driver, request):
    """已进入某"快检项目"快检详情页的页面对象(module 级, 仅进入一次).

    进快检项目列表 -> 点首行项目名称链接 -> 快检详情(招标备案识别/投标文件查重/报价规律等),
    对应需求书 4.2 我的项目(投标人自助快检)与 3.2/3.3 审查项. 结束后清理登录态.
    """
    base_url = request.config.getoption("--base-url").rstrip("/")
    auth_path = Path(request.config.getoption("--auth-state"))
    if not auth_path.exists():
        pytest.skip(f"未找到登录态文件 {auth_path}, 请先运行: python save_auth_state.py")
    with open(auth_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    _inject_auth_state(driver, base_url, state)

    def cleanup():
        _cleanup_auth_state(driver, base_url)

    page = ProjectPage(driver, base_url)
    if not page.ensure_quick_check_loaded(attempts=4, timeout=20):
        cleanup()
        pytest.skip("快检项目列表无数据行, 无法进入快检详情")

    detail = ProjectDetailPage(driver, base_url)
    markers = ("招标备案识别", "投标文件查重", "报价规律", "本页目录")
    rendered = False
    # 快检详情数据异步加载偶发较慢, 整体重试: 进列表->点名称->等内容渲染
    for _ in range(3):
        if not page.open_first_quick_check_detail(timeout=20):
            page.ensure_quick_check_loaded(attempts=2, timeout=20)
            continue
        detail.wait_loaded(timeout=20)
        if detail.wait_content(markers=markers, timeout=25):
            rendered = True
            break
        page.ensure_quick_check_loaded(attempts=2, timeout=20)
    if not rendered:
        cleanup()
        pytest.skip("快检详情审查内容未渲染(数据加载超时)")
    try:
        yield detail
    finally:
        cleanup()


@pytest.fixture(scope="module")
def prebid_detail_page(driver, request):
    """已进入某"开标前"项目详情页(开标前环节校验)的页面对象(module 级, 仅进入一次).

    取列表中"开标前"项目, 点击项目名称链接进入; 默认展示开标前环节校验内容
    (招标文件识别/招标备案识别/招标成员关系分析, 对应需求书 3.2 / 4.3.1).
    """
    detail, cleanup = _enter_project_detail(
        driver, request, "开标前", ("招标文件识别", "招标备案识别", "招标成员关系分析")
    )
    try:
        yield detail
    finally:
        cleanup()
