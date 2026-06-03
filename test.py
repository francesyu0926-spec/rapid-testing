# discover_dom.py —— 跑一次,导出渲染后的真实页面结构
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
URL = "https://www.detection.shanxiguandian.com/"
def discover():
    options = Options()
    # 先别用无头,方便你亲眼看到页面长什么样
    options.add_argument("--window-size=1440,900")
    driver = webdriver.Chrome(options=options)
    driver.get(URL)
    # SPA 需要等 JS 渲染完,这里简单等几秒(后面正式测试会用显式等待)
    time.sleep(5)
    print("=== 当前 URL ===")
    print(driver.current_url)          # 看看是否自动跳到了 /login
    print("=== 标题 ===")
    print(driver.title)
    # 1) 导出渲染后的完整 HTML
    with open("rendered.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print("已保存渲染后 HTML 到 rendered.html")
    # 2) 列出页面上所有可交互元素,方便定位
    print("\n=== 输入框 input ===")
    for el in driver.find_elements(By.TAG_NAME, "input"):
        print(f"  placeholder={el.get_attribute('placeholder')!r}  "
              f"id={el.get_attribute('id')!r}  type={el.get_attribute('type')!r}")
    print("\n=== 按钮 button ===")
    for el in driver.find_elements(By.TAG_NAME, "button"):
        print(f"  text={el.text!r}  class={el.get_attribute('class')!r}")
    print("\n=== 链接/标签页文本 ===")
    for el in driver.find_elements(By.CSS_SELECTOR, ".ant-tabs-tab, a"):
        t = el.text.strip()
        if t:
            print(f"  {t!r}")
    input("\n看完后按回车关闭浏览器...")
    driver.quit()

if __name__ == "__main__":
    discover()