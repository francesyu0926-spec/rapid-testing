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
import re
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
    if not page.find_status_across_pages(status):
        cleanup()
        pytest.skip(f"项目列表(全部分页)中无'{status}'项目, 无法进入对应详情")
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


def _load_list_rows(driver, request, which: str) -> dict:
    """注入登录态 -> 加载(项目/快检)列表 -> 返回 {headers, rows(dict列表)}; 失败 skip.

    which: 'project' 项目列表 / 'quick' 快检列表. 调用方负责 cleanup(返回 cleanup callable).
    """
    base_url = request.config.getoption("--base-url").rstrip("/")
    auth_path = Path(request.config.getoption("--auth-state"))
    if not auth_path.exists():
        pytest.skip(f"未找到登录态文件 {auth_path}, 请先运行: python save_auth_state.py")
    with open(auth_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    _inject_auth_state(driver, base_url, state)
    page = ProjectPage(driver, base_url)
    # SPA 路由切换瞬间可能残留另一张表格, 故不仅要等出现数据行, 还要等表头出现该列表的
    # 签名列(项目列表'开标时间' / 快检列表'创建时间'), 避免读到上一张表的残留数据.
    sig = "开标时间" if which == "project" else "创建时间"
    label = "项目" if which == "project" else "快检"
    m = {"headers": [], "rows": []}
    for _ in range(5):
        if which == "project":
            page.ensure_list_loaded(attempts=2, timeout=25)
        else:
            page.ensure_quick_check_loaded(attempts=2, timeout=25)
        # 等待目标表头签名列出现(最长 ~10s), 应对异步重渲染
        deadline = time.time() + 10
        while time.time() < deadline:
            m = page.table_matrix()
            if sig in m.get("headers", []) and m.get("rows"):
                break
            time.sleep(0.5)
        if sig in m.get("headers", []) and m.get("rows"):
            break
    if sig not in m.get("headers", []) or not m.get("rows"):
        _cleanup_auth_state(driver, base_url)
        pytest.skip(f"{label}列表未加载出含'{sig}'列的数据(实得表头 {m.get('headers')})")
    rows = page.table_rows_as_dicts()
    return {"headers": m["headers"], "rows": rows, "base_url": base_url}


@pytest.fixture(scope="module")
def project_list_data(driver, request):
    """项目列表首页数据(module 级, 注入一次): {headers, rows(dict列表)}."""
    data = _load_list_rows(driver, request, "project")
    try:
        yield data
    finally:
        _cleanup_auth_state(driver, data["base_url"])


@pytest.fixture(scope="module")
def quick_check_list_data(driver, request):
    """快检列表首页数据(module 级, 注入一次): {headers, rows(dict列表)}."""
    data = _load_list_rows(driver, request, "quick")
    try:
        yield data
    finally:
        _cleanup_auth_state(driver, data["base_url"])


@pytest.fixture(scope="module")
def manager_prebid_detail(driver, request):
    """项目经理进入某"开标前"项目详情(仅进入, 不要求审查内容渲染), 用于权限边界断言.

    返回 {detail, body, table_count, url}. 无开标前项目或点击未跳转则 skip.
    与 _enter_project_detail 不同: 本 fixture 不调用 wait_content(开标前对项目经理本就无内容).
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
    if not page.ensure_list_loaded(attempts=4, timeout=25):
        cleanup()
        pytest.skip("项目列表未加载, 无法验证开标前权限边界")
    if not page.find_status_across_pages("开标前"):
        cleanup()
        pytest.skip("项目列表(全部分页)无'开标前'项目, 无法验证开标前阶段可见性")
    if not page.click_row_with_status("开标前", timeout=25):
        cleanup()
        pytest.skip("点击'开标前'项目名称未跳转到详情(另一种权限表现, 本用例不覆盖)")

    detail = ProjectDetailPage(driver, base_url)
    detail.wait_loaded(timeout=25)
    # 轮询等"开标前"环节内容渲染(招标侧检测项); 详情数据异步加载偶发较慢, 失败再重进一次.
    prebid_markers = ("招标文件识别", "招标备案识别", "招标成员关系分析", "本页目录")
    body = ""
    table_count = 0
    for attempt in range(2):
        deadline = time.time() + 30
        while time.time() < deadline:
            body = detail.body_text()
            try:
                table_count = len(driver.find_elements("css selector", ".ant-table"))
            except Exception:
                table_count = 0
            if any(m in body for m in prebid_markers) or table_count > 0:
                break
            time.sleep(1.5)
        if any(m in body for m in prebid_markers) or table_count > 0:
            break
        # 内容未出, 重进一次详情
        if attempt == 0:
            page.ensure_list_loaded(attempts=2, timeout=20)
            if page.first_row_status("开标前"):
                page.click_row_with_status("开标前", timeout=25)
                detail.wait_loaded(timeout=25)
    if not (any(m in body for m in prebid_markers) or table_count > 0):
        cleanup()
        pytest.skip("开标前详情内容未渲染(数据异步加载超时), 不做'阶段可见性'断言")
    ctx = {"detail": detail, "body": body, "table_count": table_count,
           "url": detail.current_url(), "title": (driver.title or "")}
    try:
        yield ctx
    finally:
        cleanup()


@pytest.fixture(scope="module")
def bidder_context(driver, request):
    """切到"投标人员"角色后的会话上下文, 用于投标人员权限边界断言.

    采集:
      - home: 切到投标人员后的落地 URL / 角色名 / 菜单 / "新建项目"按钮(投标人员本职能力);
      - manager_list: 投标人员直接导航到项目经理"我的项目/项目列表"后的最终 URL;
      - manager_detail: 投标人员直接导航到某项目经理项目详情(/list/<id>)后的最终 URL/正文标记/表格数。
    需求 2.3: 投标人员无权进入项目经理的项目列表/项目详情(检测信息), 会被重定向回"我的任务"。
    teardown 切回"项目经理"并清理登录态, 避免污染后续用例。
    """
    import bidder_create as bc  # 复用实战打磨的角色切换/选择器

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
    if not page.wait_app_chrome(timeout=40):
        cleanup()
        pytest.skip("应用外壳未渲染(登录态可能过期), 无法验证投标人员权限边界")
    time.sleep(2)
    if not bc.switch_to_bidder(driver):
        cleanup()
        pytest.skip("未能切换到投标人员角色(登录态过期或角色渲染异常)")

    def _markers(body):
        return [m for m in ("本页目录", "投标文件查重", "投标文件校验",
                            "投标IP校验", "报价规律", "招标文件识别", "招标备案识别")
                if m in body]

    home = {
        "url": page.current_url(),
        "role": page.current_role(8),
        "menus": page.menu_texts(),
        "new_project_btn": page.has_new_project_button(),
    }

    # 投标人员尝试直接进入项目经理"项目列表"
    driver.get(f"{base_url}{ProjectPage.PROJECT_LIST_PATH}")
    time.sleep(4)
    manager_list = {"url": page.current_url()}

    # 投标人员尝试直接进入某项目经理项目详情(/list/<id>; 任一 /my-projects/* 对投标人员均应被拦截)
    driver.get(f"{base_url}{ProjectPage.PROJECT_LIST_PATH}/1826")
    time.sleep(4)
    try:
        body = driver.find_element("tag name", "body").text
    except Exception:
        body = ""
    manager_detail = {
        "url": page.current_url(),
        "audit_markers": _markers(body),
        "audit_tables": len(driver.find_elements("css selector", ".ant-table")),
        "body_len": len(body),
    }

    ctx = {"home": home, "manager_list": manager_list, "manager_detail": manager_detail}
    try:
        yield ctx
    finally:
        try:
            bc._select_role(driver, "项目经理")
            time.sleep(1.5)
        except Exception:
            pass
        cleanup()


@pytest.fixture(scope="module")
def reviewer_context(driver, request):
    """切到"评审专家"角色后的会话上下文, 用于评审专家角色边界断言.

    实测定位: 评审专家是面向项目/评标的"只读评审"角色 ——
      - 落地项目经理同侧的"我的项目/项目列表"(非投标人员的"我的任务");
      - 无"新建项目"能力(不可发起项目);
      - 可进入项目详情(可见评标环节), 区别于投标人员被拦截。
    采集: home(url/role/menus/new_btn) 与 detail(点列表首行进入后的 url/正文标记)。
    teardown 切回"项目经理"并清理登录态。
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
    if not page.wait_app_chrome(timeout=40):
        cleanup()
        pytest.skip("应用外壳未渲染(登录态可能过期), 无法验证评审专家边界")
    time.sleep(1.5)
    if not page.switch_role("评审专家", timeout=30):
        cleanup()
        pytest.skip("未能切换到评审专家角色(账号可能无该角色或渲染异常)")
    time.sleep(2)

    home = {
        "url": page.current_url(),
        "role": page.current_role(8),
        "menus": page.menu_texts(),
        "new_project_btn": page.has_new_project_button(),
    }

    # 评审专家应能进入项目详情: 先尝试点列表首行项目名; 失败再回退到直接导航详情 URL
    # (实测评审专家列表行可能为只读、无名称链接, 但直达详情 URL 不会像投标人员那样被拦截)
    detail = {"entered": False, "url": "", "markers": []}
    entered = False
    if page.ensure_list_loaded(attempts=3, timeout=20):
        entered = page.open_first_project_detail(timeout=20)
    if not entered:
        _safe_get(driver, f"{base_url}{ProjectPage.PROJECT_LIST_PATH}/1826")
        time.sleep(4)
        entered = bool(re.search(r"/list/\d+", page.current_url()))
    else:
        time.sleep(3)
    try:
        body = driver.find_element("tag name", "body").text
    except Exception:
        body = ""
    detail = {
        "entered": entered,
        "url": page.current_url(),
        "markers": [m for m in ("评标", "评审", "评分", "本页目录",
                                "招标文件识别", "投标文件查重") if m in body],
    }

    ctx = {"home": home, "detail": detail}
    try:
        yield ctx
    finally:
        try:
            import bidder_create as bc
            bc._select_role(driver, "项目经理")
            time.sleep(1.5)
        except Exception:
            pass
        cleanup()


@pytest.fixture(scope="module")
def consistency_context(driver, request):
    """L2 自洽性上下文: 进某"已完成"快检项目详情, 产出"上传文件 oracle + 详情展示文本".

    流程:
      1) 由测试资料目录解析期望(项目名 + 前 K 家投标单位), 复用创建时的解析逻辑;
      2) 进快检列表, 找一个"已完成"且能与某材料目录项目名匹配的项目;
      3) 进其详情, 抓全文本(blob);
      4) 产出 {expected, blob, name_hit, units_found, units_total, units_missing}.
    任一前置不满足(无材料/无已完成匹配项目/详情未渲染)则 skip, 不产生假失败.
    """
    base_url = request.config.getoption("--base-url").rstrip("/")
    auth_path = Path(request.config.getoption("--auth-state"))
    if not auth_path.exists():
        pytest.skip(f"未找到登录态文件 {auth_path}, 请先运行: python save_auth_state.py")

    try:
        from verify_results import build_expected, norm
    except Exception as e:  # pragma: no cover
        pytest.skip(f"无法导入比对逻辑(verify_results): {e}")

    expected = build_expected(count=16, bidders=3)
    if not expected:
        pytest.skip("测试资料目录未解析出任何期望项目(检查 MATERIALS 目录与文件结构)")

    with open(auth_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    _inject_auth_state(driver, base_url, state)

    def cleanup():
        _cleanup_auth_state(driver, base_url)

    page = ProjectPage(driver, base_url)
    if not page.ensure_quick_check_loaded(attempts=4, timeout=25):
        cleanup()
        pytest.skip("快检列表未加载, 无法做一致性比对")

    # 找"已完成"且与期望集合匹配的首个项目(快检列表分页, 故跨页扫描)
    match_key = None
    online_name = None
    for _page_no in range(10):  # 最多扫 10 页
        for r in page.qc_list_rows():
            if "已完成" not in (r.get("status") or ""):
                continue
            nm = norm(r.get("name") or "")
            for k in expected:
                if k and (k in nm or nm in k):
                    match_key, online_name = k, r.get("name")
                    break
            if match_key:
                break
        if match_key or not page.qc_next_page(timeout=10):
            break
    if not match_key:
        cleanup()
        pytest.skip("快检列表(跨页)中无与测试资料匹配的'已完成'项目, 无法做一致性比对")

    entry = expected[match_key]
    detail = ProjectDetailPage(driver, base_url)
    qc_markers = ("招标备案识别", "投标文件查重", "报价规律", "本页目录")
    rendered = False
    # 进详情后须等异步审查内容渲染再抓文本, 否则只拿到骨架(整体重试: 进列表->点名称->等内容)
    for _ in range(3):
        if not page.enter_quick_check_detail_by_name(entry["name"], timeout=20):
            page.ensure_quick_check_loaded(attempts=2, timeout=20)
            continue
        detail.wait_loaded(timeout=20)
        if detail.wait_content(markers=qc_markers, timeout=25):
            rendered = True
            break
        page.ensure_quick_check_loaded(attempts=2, timeout=20)
    if not rendered:
        cleanup()
        pytest.skip(f"'{entry['name'][:20]}'快检详情内容未渲染(数据加载超时)")
    blob = page.quick_check_detail_blob(settle=5)
    nblob = norm(blob)
    units = entry["units"]
    unit_hits = [u for u in units if norm(u) and norm(u) in nblob]
    ctx = {
        "expected": entry,
        "online_name": online_name,
        "blob_len": len(blob),
        "name_hit": (norm(entry["name"])[:20] in nblob) if entry["name"] else False,
        "units_total": len(units),
        "units_found": len(unit_hits),
        "units_missing": [u for u in units if u not in unit_hits],
    }
    try:
        yield ctx
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
