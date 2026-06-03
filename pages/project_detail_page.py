# -*- coding: utf-8 -*-
"""Page object: 招投标审查平台 - 项目详情页(项目经理"开标中环节检查").

选择器/区块均来自对登录后真实 DOM 的实测(explore_quickcheck.py):
  - 进入路径: 项目列表中点击"开标中"项目 -> URL /ai/my-projects/list/<id>, 标题"项目详情"
  - 右上角有"导出报告"按钮
  - "本页目录"包含 10 个审查区块(实测), 对应需求说明书 3.3 / 4.3.2 开标中环节检查
  - 各审查区块为 antd 表格, 表头与需求书一致(暂无数据时显示空态)

对应需求说明书条款:
  - 投标文件查重 4.3.2.3 / 相同投标预警 4.3.2.4 / 投标环境校验 4.3.2.6 /
    投标IP校验 4.3.2.7 / 投标笔迹校验 4.3.2.8 / 文件属性校验 4.3.2.9 /
    报价规律性校验 4.3.2.10 / 投标时间校验 4.3.2.11 / 投标次数预警 4.3.2.12
"""

import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class ProjectDetailPage:
    EXPORT_BUTTON = (By.XPATH, "//button[contains(normalize-space(),'导出报告')]")
    TABLE_HEADERS = (By.CSS_SELECTOR, ".ant-table-thead th")

    # 详情页四个阶段步骤(对应需求书 4.3 开标前/开标中/评标中环节)
    STAGE_STEPS = ("开标前", "开标中", "评标中", "评标后")

    # "开标中"阶段实测的审查区块(无"保证金校验", 故不臆测), 对应需求书 3.3 / 4.3.2
    OPEN_BID_SECTIONS = (
        "投标文件校验",
        "投标文件查重",
        "相同投标预警",
        "投标环境校验",
        "投标IP校验",
        "投标笔迹校验",
        "文件属性校验",
        "投标次数预警",
        "报价规律校验",
        "投标时间相近",
    )
    # 兼容旧名
    EXPECTED_SECTIONS = OPEN_BID_SECTIONS

    # "开标前"阶段实测的审查区块, 对应需求书 3.2 / 4.3.1 开标前环节校验
    PREBID_SECTIONS = (
        "招标文件识别",
        "招标备案识别",
        "招标成员关系分析",
    )

    # 快检详情(投标人自助快检报告)实测的审查区块, 对应需求书 3.2/3.3 与 4.2
    QUICK_CHECK_SECTIONS = (
        "招标备案识别",
        "投标文件校验",
        "投标文件查重",
        "相同投标预警",
        "投标笔迹校验",
        "文件属性校验",
        "投标次数预警",
        "报价规律校验",
    )

    def __init__(self, driver, base_url: str, timeout: int = 20):
        self.driver = driver
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.wait = WebDriverWait(driver, timeout)

    def current_url(self) -> str:
        try:
            return self.driver.current_url or ""
        except Exception:
            return ""

    def wait_loaded(self, timeout: int = 20, titles=("项目详情", "快检详情")) -> bool:
        """等待详情页加载完成(文档标题变为'项目详情'或'快检详情')."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.driver.title in titles:
                    time.sleep(1)
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    def wait_content(self, markers=None, timeout: int = 25) -> bool:
        """等待详情页审查内容渲染出来(出现任一给定标记文本).

        不同阶段内容不同, 由调用方传入对应标记:
          开标中 -> ("投标文件查重", ...); 开标前 -> ("招标文件识别", ...).
        """
        markers = markers or ("本页目录", "投标文件查重", "投标文件校验")
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = self.body_text()
            if any(m in text for m in markers):
                time.sleep(1)
                return True
            time.sleep(0.5)
        return False

    def has_stage_steps(self) -> bool:
        """详情页是否含开标前/开标中/评标中/评标后四个阶段步骤."""
        text = self.body_text()
        return all(s in text for s in self.STAGE_STEPS)

    def missing_stage_steps(self) -> list:
        text = self.body_text()
        return [s for s in self.STAGE_STEPS if s not in text]

    def body_text(self) -> str:
        try:
            return self.driver.execute_script("return document.body.innerText;") or ""
        except Exception:
            return ""

    def has_section(self, name: str) -> bool:
        return name in self.body_text()

    def missing_sections(self, names=None) -> list:
        """返回未出现的审查区块名(用于断言齐全)."""
        names = names or self.EXPECTED_SECTIONS
        text = self.body_text()
        return [n for n in names if n not in text]

    def header_texts(self) -> list:
        """详情页所有表格的表头文本合集.

        用 JS 一次性读取, 避免表格异步重渲染导致逐元素读取时 StaleElementReference.
        """
        try:
            texts = self.driver.execute_script(
                "return Array.from(document.querySelectorAll('.ant-table-thead th'))"
                ".map(function(e){return (e.innerText||'').trim();});"
            ) or []
        except Exception:
            texts = []
        return [t for t in texts if t]

    def has_headers(self, headers, timeout: int = 10) -> bool:
        """页面是否包含全部给定表头(跨所有审查表格), 给异步渲染留重试时间."""
        deadline = time.time() + timeout
        while True:
            present = set(self.header_texts())
            if all(h in present for h in headers):
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.5)

    def has_export_button(self) -> bool:
        return bool(self.driver.find_elements(*self.EXPORT_BUTTON))

    def text_contains(self, *fragments) -> bool:
        """正文是否同时包含若干文本片段(用于校验业务规则描述)."""
        text = self.body_text()
        return all(f in text for f in fragments)
