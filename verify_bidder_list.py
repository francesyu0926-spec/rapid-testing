# -*- coding: utf-8 -*-
"""核验: 切到投标人员, 读"任务列表"行数与项目名."""
import json, sys, time
from pathlib import Path
from selenium.webdriver.common.by import By
sys.path.insert(0, str(Path(__file__).resolve().parent))
from batch_create_execute import BASE, make_driver, inject_auth
from bidder_create import switch_to_bidder


def main():
    st = json.loads(Path("auth_state.json").read_text(encoding="utf-8"))
    d = make_driver(); d.set_page_load_timeout(40)
    try:
        inject_auth(d, st); d.get(BASE+"/"); time.sleep(8)
        if not switch_to_bidder(d):
            print("切换投标人员失败", d.current_url); return
        time.sleep(3)
        print("URL:", d.current_url, flush=True)
        rows = d.find_elements(By.CSS_SELECTOR, ".ant-table-tbody tr.ant-table-row")
        print("任务列表行数:", len(rows), flush=True)
        for i, r in enumerate(rows, 1):
            tds = r.find_elements(By.CSS_SELECTOR, "td")
            cells = [t.text.strip().replace("\n", " ") for t in tds]
            name = next((c for c in cells if len(c) > 6), "")
            print(f"  {i}. {name[:46]}", flush=True)
    finally:
        d.quit()


if __name__ == "__main__":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    main()
