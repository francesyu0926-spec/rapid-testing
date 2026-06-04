# -*- coding: utf-8 -*-
"""Page object: 招投标审查平台 - 登录后"我的项目"相关页面.

选择器均来自对登录后真实渲染 DOM 的实测(discover_menu.py, antd 5 + React 18):
  - 左侧导航栏 aside.ant-layout-sider, 根菜单 ul.ant-menu.ant-menu-root
  - 菜单项: 我的项目(submenu) / 项目列表 / 快检项目
  - 项目列表页路由 /ai/my-projects/list, 含分页 .ant-pagination
  - 快检项目页路由 /ai/my-projects/quick-check

配合会话复用使用: 需传入已注入登录态的 driver(见 conftest.authenticated_driver),
因此 ProjectPage 不负责登录, 只负责登录后页面的导航与读取.
"""

import re
import time

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class ProjectPage:
    # --- 路由 ---
    PROJECT_LIST_PATH = "/ai/my-projects/list"
    QUICK_CHECK_PATH = "/ai/my-projects/quick-check"

    # --- 框架/导航 ---
    SIDER = (By.CSS_SELECTOR, "aside.ant-layout-sider")
    ROOT_MENU = (By.CSS_SELECTOR, "ul.ant-menu.ant-menu-root")
    MENU_ITEMS = (By.CSS_SELECTOR, ".ant-menu-item, .ant-menu-submenu-title")

    # --- 列表页 ---
    PAGINATION = (By.CSS_SELECTOR, ".ant-pagination")
    EMPTY = (By.CSS_SELECTOR, ".ant-empty")
    TABLE = (By.CSS_SELECTOR, ".ant-table")
    TABLE_ROWS = (By.CSS_SELECTOR, ".ant-table-row")
    TABLE_HEADERS = (By.CSS_SELECTOR, ".ant-table-thead th")
    SEARCH_BUTTON = (By.XPATH, "//button[normalize-space()='搜索']")
    RESET_BUTTON = (By.XPATH, "//button[normalize-space()='重置']")

    # 项目详情页路由形如 /ai/my-projects/list/<projectId>
    _DETAIL_URL_RE = re.compile(r"/ai/my-projects/list/\d+")
    # 快检详情页路由形如 /ai/my-projects/quick-check/<projectId>
    _QC_DETAIL_URL_RE = re.compile(r"/ai/my-projects/quick-check/\d+")
    # 项目列表表头(实测), 对应需求书项目信息列
    EXPECTED_LIST_COLUMNS = (
        "序号", "项目名称", "标段", "项目类型", "招标发布时间", "开标时间", "项目状态", "招标方",
    )
    # 快检项目列表表头(实测), 对应需求书 4.2 我的项目(投标人自助快检)
    EXPECTED_QC_COLUMNS = (
        "序号", "项目名称", "标段", "招标方", "校验任务状态", "任务状态", "创建时间", "操作",
    )
    NEW_PROJECT_BUTTON = (By.XPATH, "//button[contains(normalize-space(),'新建项目')]")

    # --- 路由标签条(已打开页面的 Tab) 与 顶部角色下拉 ---
    ROUTER_TABS = (By.CSS_SELECTOR, ".ant-tabs-tab")
    ROLE_SELECT = (By.CSS_SELECTOR, ".ant-select")

    def __init__(self, driver, base_url: str, timeout: int = 20):
        self.driver = driver
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.wait = WebDriverWait(driver, timeout)

    # ---------- 容错读取 ----------
    def current_url(self) -> str:
        """渲染进程偶发无响应时返回空串, 避免抛异常打断断言."""
        try:
            return self.driver.current_url or ""
        except Exception:
            return ""

    # ---------- 等待 ----------
    def wait_mounted(self, timeout: int = 30) -> bool:
        """轮询等待 React 把 #root 渲染出内容(脚本极多, 挂载较慢)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                n = self.driver.execute_script(
                    "var r=document.getElementById('root');return r?r.children.length:0;"
                )
                if n and int(n) > 0:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def wait_url_contains(self, fragment: str, timeout: int = 15) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if fragment in self.current_url():
                return True
            time.sleep(0.5)
        return False

    # ---------- 框架/导航读取 ----------
    def sider_visible(self) -> bool:
        try:
            return self.driver.find_element(*self.SIDER).is_displayed()
        except Exception:
            return False

    def menu_visible(self) -> bool:
        try:
            return self.driver.find_element(*self.ROOT_MENU).is_displayed()
        except Exception:
            return False

    def menu_texts(self) -> list:
        return [
            el.text.strip()
            for el in self.driver.find_elements(*self.MENU_ITEMS)
            if el.text.strip()
        ]

    def click_menu(self, text: str) -> bool:
        """点击文本匹配的菜单项(JS 点击更稳); 找到并点击返回 True."""
        for el in self.driver.find_elements(*self.MENU_ITEMS):
            if text in el.text:
                self.driver.execute_script("arguments[0].click();", el)
                return True
        return False

    # ---------- 列表页 ----------
    def on_project_list(self, timeout: int = 20) -> bool:
        """是否已进入项目列表页."""
        return self.wait_url_contains(self.PROJECT_LIST_PATH, timeout)

    def has_pagination(self, timeout: int = 10) -> bool:
        """列表数据异步加载, 在 timeout 内等待分页出现."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.driver.find_elements(*self.PAGINATION):
                return True
            time.sleep(0.5)
        return False

    def list_content_loaded(self, timeout: int = 20) -> bool:
        """列表内容已加载: 出现分页(有数据) 或 空态(无数据) 均算加载完成.

        分页只在有数据时出现, 故仅判断分页会因数据为空而误判; 这里把"空态"也视为
        正常加载, 避免数据状态导致用例 flaky.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.driver.find_elements(*self.PAGINATION) or self.driver.find_elements(*self.EMPTY):
                return True
            time.sleep(0.5)
        return False

    def goto_quick_check(self, timeout: int = 15) -> bool:
        """点击"快检项目"菜单并等待跳转, 成功返回 True."""
        if not self.click_menu("快检项目"):
            return False
        return self.wait_url_contains(self.QUICK_CHECK_PATH, timeout)

    def goto_project_list(self, timeout: int = 15) -> bool:
        """点击"项目列表"菜单并等待跳转, 成功返回 True."""
        if not self.click_menu("项目列表"):
            return False
        return self.wait_url_contains(self.PROJECT_LIST_PATH, timeout)

    # ---------- 项目列表表格 ----------
    def ensure_list_loaded(self, attempts: int = 4, timeout: int = 20) -> bool:
        """确保项目列表加载出数据行(直接用 URL 进入列表更确定, 无行则重导航重试).

        列表是顶层路由, 直接 URL 即可渲染(与详情页不同); 数据异步, 偶发未及时返回时
        重新导航重试. 返回是否拿到数据行(真正空列表则返回是否为空态)."""
        for _ in range(attempts):
            try:
                self.driver.get(f"{self.base_url}{self.PROJECT_LIST_PATH}")
            except Exception:
                pass
            self.wait_mounted()
            if self.wait_table_loaded(timeout) and self.row_count() >= 1:
                return True
        return self.row_count() >= 1 or bool(self.driver.find_elements(*self.EMPTY))

    def wait_table_loaded(self, timeout: int = 20) -> bool:
        """等待列表表格加载完成.

        加载过程中会先短暂出现空态(.ant-empty)再渲染数据行, 故优先等待数据行出现;
        直到超时仍无数据行时, 才以"是否为空态"判定(真正的空列表).
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.driver.find_elements(*self.TABLE_ROWS):
                return True
            time.sleep(0.5)
        return bool(self.driver.find_elements(*self.EMPTY))

    def table_headers(self) -> list:
        return [el.text.strip() for el in self.driver.find_elements(*self.TABLE_HEADERS) if el.text.strip()]

    def rows(self):
        return self.driver.find_elements(*self.TABLE_ROWS)

    def row_count(self) -> int:
        return len(self.rows())

    def has_search_controls(self) -> bool:
        return bool(self.driver.find_elements(*self.SEARCH_BUTTON)) and bool(
            self.driver.find_elements(*self.RESET_BUTTON)
        )

    # ---------- 进入项目详情 ----------
    def on_project_detail(self) -> bool:
        """当前是否在项目详情页(URL 形如 /ai/my-projects/list/<id>)."""
        return bool(self._DETAIL_URL_RE.search(self.current_url()))

    def row_key_with_status(self, status: str):
        """返回状态匹配的首行的 data-row-key(即项目 id); 无则 None.

        stale 安全: 行可能在数据刷新时失效, 逐行读取时吞掉 stale 异常.
        """
        for r in self.rows():
            try:
                if status in r.text:
                    key = r.get_attribute("data-row-key")
                    if key:
                        return key
            except Exception:
                continue
        return None

    def _wait_detail(self, timeout: float) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.on_project_detail():
                return True
            time.sleep(0.5)
        return False

    def click_row_with_status(self, status: str, timeout: int = 12) -> bool:
        """点击状态匹配的首行, 返回是否进入了详情页.

        项目经理对"开标前"项目无权查看 -> 点击不跳转(返回 False);
        "开标中/后"项目 -> 进入详情(返回 True).
        通过 data-row-key 每次重新定位元素以规避 StaleElementReference,
        并在 React 绑定 onClick 后留缓冲、行/单元格双重点击兜底.
        """
        if not self.row_key_with_status(status):
            return False

        def _fresh_target():
            for r in self.rows():
                try:
                    if status in r.text:
                        return r
                except Exception:
                    continue
            return None

        def _try_click_link() -> bool:
            # 实测可进入详情的入口是"项目名称"单元格里的 <a> 链接(点击整行/单元格无效)
            for _ in range(4):
                target = _fresh_target()
                if target is None:
                    time.sleep(1)
                    continue
                links = target.find_elements(By.CSS_SELECTOR, "td a")
                if links:
                    try:
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});", links[0])
                        self.driver.execute_script("arguments[0].click();", links[0])
                    except Exception:
                        pass
                    if self._wait_detail(6):
                        return True
                else:
                    time.sleep(1)
            return self.on_project_detail()

        # 两轮: 偶发渲染未就绪时, 重载列表后再试一次
        time.sleep(3)  # 等表格渲染稳定
        if _try_click_link():
            return True
        self.ensure_list_loaded(attempts=2, timeout=20)
        time.sleep(3)
        return _try_click_link()

    def first_row_status(self, status: str) -> bool:
        """列表中是否存在指定状态(开标前/开标中/...)的项目行."""
        return any(status in r.text for r in self.rows())

    # ---------- 快检项目页 / 顶部框架 ----------
    def on_quick_check(self, timeout: int = 20) -> bool:
        """是否已进入快检项目页."""
        return self.wait_url_contains(self.QUICK_CHECK_PATH, timeout)

    def router_tab_texts(self) -> list:
        """顶部已打开页面的路由标签条文本(如 项目列表 / 快检项目)."""
        return [
            el.text.strip()
            for el in self.driver.find_elements(*self.ROUTER_TABS)
            if el.text.strip()
        ]

    def select_texts(self) -> list:
        """页面上所有 .ant-select 的显示文本(顶部角色下拉等)."""
        return [
            el.text.strip()
            for el in self.driver.find_elements(*self.ROLE_SELECT)
            if el.text.strip()
        ]

    def has_role(self, role: str) -> bool:
        """顶部某个下拉是否显示了指定角色(如 项目经理)."""
        return any(role in t for t in self.select_texts())

    # ---------- 快检项目列表表格 ----------
    def ensure_quick_check_loaded(self, attempts: int = 4, timeout: int = 20) -> bool:
        """确保快检项目列表加载出数据行(直接 URL 进入, 数据异步, 无行则重导航重试)."""
        for _ in range(attempts):
            try:
                self.driver.get(f"{self.base_url}{self.QUICK_CHECK_PATH}")
            except Exception:
                pass
            self.wait_mounted()
            if self.wait_table_loaded(timeout) and self.row_count() >= 1:
                return True
        return self.row_count() >= 1 or bool(self.driver.find_elements(*self.EMPTY))

    def has_new_project_button(self) -> bool:
        return bool(self.driver.find_elements(*self.NEW_PROJECT_BUTTON))

    # ---------- 新建快检项目(上传) ----------
    # "新建项目"弹窗结构(实测): 1.项目名称 2.招标文件 3.备案文件 4.投标文件(每家:单位名称+文件)
    # 实测"新建项目"是 modal 或 drawer, 选择器同时兼容两者
    NEW_PROJECT_MODAL = (By.CSS_SELECTOR, ".ant-modal, .ant-drawer")
    PROJECT_NAME_INPUT = (By.CSS_SELECTOR,
                          ".ant-modal input[placeholder='请输入项目名称'], "
                          ".ant-drawer input[placeholder='请输入项目名称']")
    UNIT_NAME_INPUTS = (By.CSS_SELECTOR,
                        ".ant-modal input[placeholder='请输入'], "
                        ".ant-drawer input[placeholder='请输入']")
    MODAL_FILE_INPUTS = (By.CSS_SELECTOR,
                         ".ant-modal input[type='file'], .ant-drawer input[type='file']")
    ADD_UNIT_BUTTON = (By.XPATH, "//button[contains(.,'新增投标单位')]")
    # antd 对两个汉字的按钮会插入空格(如"提 交"/"取 消"), 故按单字 contains 匹配, 并限定在 footer
    SUBMIT_BUTTON = (By.XPATH,
                     "//div[contains(@class,'ant-drawer-footer') or contains(@class,'ant-modal-footer')]"
                     "//button[contains(.,'提') and contains(.,'交')]")
    CANCEL_BUTTON = (By.XPATH,
                     "//div[contains(@class,'ant-drawer-footer') or contains(@class,'ant-modal-footer')]"
                     "//button[contains(.,'取') and contains(.,'消')]")

    def new_project_form_open(self) -> bool:
        """新建项目抽屉是否处于打开状态(项目名称输入框可见).

        antd Drawer 关闭后内容仍留在 DOM(隐藏), 故用"可见性"而非"存在性"判断.
        """
        for e in self.driver.find_elements(*self.PROJECT_NAME_INPUT):
            try:
                if e.is_displayed():
                    return True
            except Exception:
                continue
        return False

    def open_new_project_modal(self, timeout: int = 12) -> bool:
        """点击"新建项目"打开弹窗, "项目名称"输入框可见才算成功.

        多种点击策略轮试: 滚动到可见 -> JS click -> 原生 click -> ActionChains, 兼容动画/遮罩.
        """
        def _form_ready() -> bool:
            return self.new_project_form_open()

        # 并发/高负载时 React 渲染"新建项目"按钮偏慢, 先等按钮出现再点(不立即判失败)
        btn_deadline = time.time() + timeout
        while time.time() < btn_deadline and not self.driver.find_elements(*self.NEW_PROJECT_BUTTON):
            time.sleep(0.5)

        for _ in range(3):
            btns = self.driver.find_elements(*self.NEW_PROJECT_BUTTON)
            if not btns:
                # 仍未渲染出按钮, 再等一会而非直接放弃
                end = time.time() + timeout
                while time.time() < end and not self.driver.find_elements(*self.NEW_PROJECT_BUTTON):
                    time.sleep(0.5)
                btns = self.driver.find_elements(*self.NEW_PROJECT_BUTTON)
                if not btns:
                    continue
            btn = btns[0]
            try:
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", btn)
            except Exception:
                pass
            time.sleep(0.3)
            for clicker in (
                lambda: self.driver.execute_script("arguments[0].click();", btn),
                lambda: btn.click(),
                lambda: ActionChains(self.driver).move_to_element(btn).pause(0.2).click().perform(),
            ):
                try:
                    clicker()
                except Exception:
                    continue
                end = time.time() + 4
                while time.time() < end:
                    if _form_ready():
                        time.sleep(1)
                        return True
                    time.sleep(0.3)
            # 整体再等一会, 应对慢渲染
            end = time.time() + timeout
            while time.time() < end:
                if _form_ready():
                    time.sleep(1)
                    return True
                time.sleep(0.5)
        return _form_ready()

    def modal_filenames(self) -> list:
        """弹窗/抽屉内已选择的文件名(从可见文本提取 *.pdf), 用于校验上传是否生效."""
        bodies = self.driver.find_elements(
            By.CSS_SELECTOR, ".ant-drawer-body, .ant-modal-body")
        text = bodies[0].text if bodies else ""
        names = re.findall(r"\S+\.pdf", text, flags=re.IGNORECASE)
        if names:
            return names
        # 退化: 仍尝试 antd 默认上传列表项
        for e in self.driver.find_elements(
            By.CSS_SELECTOR,
            ".ant-modal .ant-upload-list-item-name, .ant-modal .ant-upload-list-item, "
            ".ant-drawer .ant-upload-list-item-name, .ant-drawer .ant-upload-list-item"
        ):
            t = e.text.strip()
            if t:
                names.append(t)
        return names

    # "点击上传"触发器(选择文件后必须点它才真正上传); 用直接文本节点定位避免匹配到嵌套祖先
    UPLOAD_TRIGGER = (By.XPATH, "//*[text()='点击上传']")
    UPLOAD_PROGRESS = (By.CSS_SELECTOR,
                       ".ant-drawer-body .ant-progress, .ant-modal-body .ant-progress")

    def fill_new_project(self, name: str, tender_pdf: str, bidders, record_pdf: str = None,
                         submit: bool = False) -> bool:
        """选择"新建项目"表单内容(只选不上传).

        name: 项目名称; tender_pdf: 招标文件绝对路径; record_pdf: 备案文件(可选, 不需要则 None);
        bidders: [(单位名称, 投标文件绝对路径), ...] (至少 1 家);
        submit=True 直接点提交(通常应先 trigger_uploads + wait_uploads_complete 再提交).

        文件 input 顺序(实测): [0]招标 [1]备案 [2..]投标; 投标单位默认 2 行, 不足时点"新增投标单位".
        注意: send_keys 仅"选择"文件, 真正上传需调用 trigger_uploads().
        """
        # 项目名称
        self.driver.find_element(*self.PROJECT_NAME_INPUT).send_keys(name)
        # 招标文件
        files = self.driver.find_elements(*self.MODAL_FILE_INPUTS)
        files[0].send_keys(tender_pdf)
        # 备案文件(可选)
        if record_pdf and len(files) > 1:
            files[1].send_keys(record_pdf)
        # 确保有足够的投标单位行
        while len(self.driver.find_elements(*self.UNIT_NAME_INPUTS)) < len(bidders):
            add = self.driver.find_elements(*self.ADD_UNIT_BUTTON)
            if not add:
                break
            self.driver.execute_script("arguments[0].click();", add[0])
            time.sleep(0.5)
        # 逐家填写 单位名称 + 投标文件
        name_inputs = self.driver.find_elements(*self.UNIT_NAME_INPUTS)
        files = self.driver.find_elements(*self.MODAL_FILE_INPUTS)
        bidder_file_inputs = files[2:]  # 跳过 招标[0]/备案[1]
        for i, (uname, pdf) in enumerate(bidders):
            if i < len(name_inputs):
                name_inputs[i].send_keys(uname)
            if i < len(bidder_file_inputs):
                bidder_file_inputs[i].send_keys(pdf)
            time.sleep(0.3)
        if submit:
            self.driver.find_element(*self.SUBMIT_BUTTON).click()
        return True

    def trigger_uploads(self) -> int:
        """点击每个"点击上传"(各一次)真正上传已选文件. 返回点击数."""
        targets = self.driver.find_elements(*self.UPLOAD_TRIGGER)
        for e in targets:
            try:
                self.driver.execute_script("arguments[0].click();", e)
                time.sleep(0.4)
            except Exception:
                pass
        return len(targets)

    def upload_percents(self) -> list:
        """抽屉内各上传进度条的百分比(int 列表)."""
        out = []
        for p in self.driver.find_elements(*self.UPLOAD_PROGRESS):
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

    def wait_uploads_complete(self, expected: int, timeout: int = 600) -> bool:
        """等待所有上传进度条到 100%. expected: 期望的进度条数(=上传文件数). 全部 100 返回 True."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            pcts = self.upload_percents()
            if len(pcts) >= expected and all(p >= 100 for p in pcts):
                return True
            time.sleep(2)
        pcts = self.upload_percents()
        return len(pcts) >= expected and all(p >= 100 for p in pcts)

    def submit_new_project(self) -> bool:
        """点击提交按钮. 找到并点击返回 True."""
        btns = self.driver.find_elements(*self.SUBMIT_BUTTON)
        if not btns:
            return False
        self.driver.execute_script("arguments[0].click();", btns[0])
        return True

    def _wait_n_uploads(self, n: int, timeout: int) -> bool:
        """等待至少 n 个上传进度条且全部到 100%."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            p = self.upload_percents()
            if len(p) >= n and all(x >= 100 for x in p):
                return True
            time.sleep(2)
        p = self.upload_percents()
        return len(p) >= n and all(x >= 100 for x in p)

    def fill_and_upload_sequential(self, name: str, tender_pdf: str, bidders,
                                   record_pdf: str = None, per_file_timeout: int = 600,
                                   progress_cb=None) -> bool:
        """填表并"一个一个"上传文件: 选一个 -> 点它的"点击上传" -> 等它到100% -> 下一个.

        避免多文件并发上传抢带宽导致卡住. 文件 input 顺序: [0]招标 [1]备案 [2..]投标.
        progress_cb(done, total, percents) 可选回调用于日志.
        """
        # 项目名称
        self.driver.find_element(*self.PROJECT_NAME_INPUT).send_keys(name)
        # 确保投标单位行数
        while len(self.driver.find_elements(*self.UNIT_NAME_INPUTS)) < len(bidders):
            add = self.driver.find_elements(*self.ADD_UNIT_BUTTON)
            if not add:
                break
            self.driver.execute_script("arguments[0].click();", add[0])
            time.sleep(0.5)
        # 填投标单位名称
        name_inputs = self.driver.find_elements(*self.UNIT_NAME_INPUTS)
        for i, (uname, _) in enumerate(bidders):
            if i < len(name_inputs):
                name_inputs[i].send_keys(uname)
        # 上传顺序: 招标[0] -> (备案[1]) -> 投标[2..]
        order = [(0, tender_pdf)]
        if record_pdf:
            order.append((1, record_pdf))
        for i, (_, pdf) in enumerate(bidders):
            order.append((2 + i, pdf))

        total = len(order)
        done = 0
        for idx, path in order:
            files = self.driver.find_elements(*self.MODAL_FILE_INPUTS)
            if idx >= len(files):
                return False
            files[idx].send_keys(path)
            time.sleep(0.8)
            # 点击"刚选这个文件"的点击上传(DOM 顺序与文件一致, 取最后一个=最新)
            triggers = self.driver.find_elements(*self.UPLOAD_TRIGGER)
            if triggers:
                self.driver.execute_script("arguments[0].click();", triggers[-1])
            done += 1
            ok = self._wait_n_uploads(done, per_file_timeout)
            if progress_cb:
                progress_cb(done, total, self.upload_percents())
            if not ok:
                return False
        return True

    def cancel_modal(self, timeout: int = 10) -> bool:
        """点击取消关闭新建项目抽屉/弹窗; 若弹二次确认则确认; 等待真正关闭. 关闭返回 True."""
        def _closed() -> bool:
            return not self.new_project_form_open()

        btns = self.driver.find_elements(*self.CANCEL_BUTTON)
        if btns:
            try:
                self.driver.execute_script("arguments[0].click();", btns[0])
            except Exception:
                pass
        # 点取消会弹二次确认"确认退出...", 其按钮为"确 定"/"取 消"(含空格), 需点"确 定"
        confirm_ok = (
            By.XPATH,
            "//div[contains(@class,'ant-modal-confirm') or contains(@class,'ant-popconfirm')]"
            "//button[(contains(.,'确') and contains(.,'定')) or contains(.,'继续')]",
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            confirms = self.driver.find_elements(*confirm_ok)
            if confirms:
                # 出现二次确认: 点"确 定"确认退出
                try:
                    self.driver.execute_script("arguments[0].click();", confirms[0])
                except Exception:
                    pass
            elif not _closed():
                # 还没弹确认且未关闭: 再点一次取消
                again = self.driver.find_elements(*self.CANCEL_BUTTON)
                if again:
                    try:
                        self.driver.execute_script("arguments[0].click();", again[0])
                    except Exception:
                        pass
            if _closed():
                return True
            time.sleep(0.5)
        return _closed()

    def has_action_buttons(self, *labels: str) -> bool:
        """快检列表操作列是否含给定按钮(如 编辑/执行)."""
        texts = {b.text.strip() for b in self.driver.find_elements(By.CSS_SELECTOR, ".ant-table-row .ant-btn")}
        return all(any(lbl in t for t in texts) for lbl in labels)

    def _confirm_dialog(self) -> bool:
        """若出现确认弹窗(确认执行/确认/确 定/继续/是)则点确认按钮. 点了返回 True.

        覆盖: 执行的"确认执行项目"弹窗(按钮"确认执行")、取消的"确认退出"(按钮"确 定").
        限定在 .ant-modal/.ant-popconfirm 内(新建项目是 drawer, 不会误点其提交).
        """
        from selenium.common.exceptions import StaleElementReferenceException
        btns = self.driver.find_elements(
            By.XPATH,
            "//div[contains(@class,'ant-modal') or contains(@class,'ant-popconfirm')]"
            "//button[contains(.,'确认执行') or contains(.,'确认') "
            "or (contains(.,'确') and contains(.,'定')) or contains(.,'继续') "
            "or normalize-space(.)='是']",
        )
        for b in btns:
            try:
                if b.is_displayed():
                    self.driver.execute_script("arguments[0].click();", b)
                    return True
            except StaleElementReferenceException:
                continue
        return False

    def _click_exec_and_confirm(self, link) -> bool:
        """点击某行的"执行"链接, 等"确认执行项目"弹窗出现并点"确认执行". 确认成功返回 True."""
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", link)
            self.driver.execute_script("arguments[0].click();", link)
        except Exception:
            return False
        # 等确认弹窗出现并点"确认执行"(弹窗有渲染延迟, 多等几秒)
        end = time.time() + 10
        while time.time() < end:
            if self._confirm_dialog():
                time.sleep(1)
                return True
            time.sleep(0.5)
        return False

    def click_execute(self, project_name: str, timeout: int = 20) -> bool:
        """在快检列表中找到匹配项目名的行, 点"执行"并在弹窗中点"确认执行"(触发文件校验).

        匹配用项目名前缀(列表可能换行截断); 按名未命中时兜底点第一行(新建项目通常在最上面).
        仅当成功点到"确认执行"才返回 True.
        """
        from selenium.common.exceptions import StaleElementReferenceException
        exec_xpath = (".//a[normalize-space(.)='执行'] | .//button[normalize-space(.)='执行']"
                      " | .//*[normalize-space(text())='执行']")
        key = re.sub(r"\s", "", project_name)[:16]
        deadline = time.time() + timeout
        while time.time() < deadline:
            for r in self.driver.find_elements(*self.TABLE_ROWS):
                try:
                    if key and key not in re.sub(r"\s", "", r.text):
                        continue
                    links = r.find_elements(By.XPATH, exec_xpath)
                    if links:
                        return self._click_exec_and_confirm(links[0])
                except StaleElementReferenceException:
                    continue
            time.sleep(1)
        # 兜底: 按名未命中时点第一行(新建项目通常在最上面)的执行
        rows = self.driver.find_elements(*self.TABLE_ROWS)
        if rows:
            try:
                links = rows[0].find_elements(By.XPATH, exec_xpath)
                if links:
                    return self._click_exec_and_confirm(links[0])
            except StaleElementReferenceException:
                pass
        return False

    # ---------- 进入快检详情 ----------
    def on_quick_check_detail(self) -> bool:
        """当前是否在快检详情页(URL 形如 /ai/my-projects/quick-check/<id>)."""
        return bool(self._QC_DETAIL_URL_RE.search(self.current_url()))

    def _wait_qc_detail(self, timeout: float) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.on_quick_check_detail():
                return True
            time.sleep(0.5)
        return False

    def open_first_quick_check_detail(self, timeout: int = 15) -> bool:
        """点击快检列表首行"项目名称"链接进入快检详情(与项目列表同样靠 <a> 进入).

        两轮: 偶发渲染未就绪时重载列表后再试.
        """
        def _try() -> bool:
            for _ in range(4):
                rows = self.rows()
                if not rows:
                    time.sleep(1)
                    continue
                links = rows[0].find_elements(By.CSS_SELECTOR, "td a")
                if links:
                    try:
                        self.driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});", links[0])
                        self.driver.execute_script("arguments[0].click();", links[0])
                    except Exception:
                        pass
                    if self._wait_qc_detail(6):
                        return True
                else:
                    time.sleep(1)
            return self.on_quick_check_detail()

        time.sleep(3)
        if _try():
            return True
        self.ensure_quick_check_loaded(attempts=2, timeout=20)
        time.sleep(3)
        return _try()

    # ---------- 快检列表: 任务状态轮询 + 按名进详情 ----------
    def qc_list_rows(self) -> list:
        """读快检列表每行的 {name, status}(JS 原子读取, 规避 stale).

        "任务状态"列需与"校验任务状态"列区分: 先精确匹配, 再退化为含"任务状态"且不含"校验".
        """
        js = r"""
        var ths = Array.prototype.map.call(
            document.querySelectorAll('.ant-table-thead th'),
            function(t){return (t.innerText||'').replace(/\s/g,'');});
        function nameIdx(){for(var i=0;i<ths.length;i++){if(ths[i].indexOf('项目名称')>=0)return i;}return 1;}
        function statusIdx(){
            for(var i=0;i<ths.length;i++){if(ths[i]==='任务状态')return i;}
            for(var i=0;i<ths.length;i++){if(ths[i].indexOf('任务状态')>=0 && ths[i].indexOf('校验')<0)return i;}
            return -1;}
        var ni=nameIdx(), si=statusIdx(), out=[];
        Array.prototype.forEach.call(document.querySelectorAll('.ant-table-row'), function(r){
            var tds=r.querySelectorAll('td');
            out.push({
                name: (ni>=0 && tds[ni]) ? (tds[ni].innerText||'').trim() : '',
                status: (si>=0 && tds[si]) ? (tds[si].innerText||'').trim() : ''
            });
        });
        return out;
        """
        try:
            return self.driver.execute_script(js) or []
        except Exception:
            return []

    def enter_quick_check_detail_by_name(self, name: str, timeout: int = 12) -> bool:
        """点击列表中项目名称匹配的行(其名称列 <a>)进入快检详情."""
        key = re.sub(r"\s", "", name)[:20]
        if not key:
            return False
        for _ in range(4):
            for r in self.rows():
                try:
                    if key in re.sub(r"\s", "", r.text):
                        links = r.find_elements(By.CSS_SELECTOR, "td a")
                        if links:
                            self.driver.execute_script(
                                "arguments[0].scrollIntoView({block:'center'});", links[0])
                            self.driver.execute_script("arguments[0].click();", links[0])
                            if self._wait_qc_detail(8):
                                return True
                except Exception:
                    continue
            time.sleep(1)
        return self.on_quick_check_detail()

    def quick_check_detail_blob(self, settle: float = 4.0) -> str:
        """详情页全部可见文本(含表格单元格), 供"界面结果 vs 上传文件"做包含性比对."""
        time.sleep(settle)
        try:
            return self.driver.execute_script(
                "var b=document.body;return b?(b.innerText||''):'';") or ""
        except Exception:
            return ""
