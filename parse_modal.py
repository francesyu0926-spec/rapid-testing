# -*- coding: utf-8 -*-
"""解析 new_project_modal.html, 提取表单字段 id / 文件输入 / 底部按钮. 一次性工具."""
import re
import sys
from pathlib import Path

H = Path("new_project_modal.html").read_text(encoding="utf-8")


def main():
    print("=== 所有 input (按出现顺序) ===")
    for m in re.finditer(r"<input\b[^>]*>", H):
        tag = m.group(0)
        idv = re.search(r'id="([^"]*)"', tag)
        typ = re.search(r'type="([^"]*)"', tag)
        ph = re.search(r'placeholder="([^"]*)"', tag)
        nm = re.search(r'name="([^"]*)"', tag)
        acc = re.search(r'accept="([^"]*)"', tag)
        print(f"  id={idv.group(1) if idv else None!r:40} type={typ.group(1) if typ else None!r:8} ph={ph.group(1) if ph else None!r:14} name={nm.group(1) if nm else None!r} accept={acc.group(1) if acc else None!r}")

    print("\n=== 按钮文本 (button 标签内可见文字) ===")
    for m in re.finditer(r"<button\b[^>]*>(.*?)</button>", H, re.S):
        cls = re.search(r'class="([^"]*)"', m.group(0))
        # 取按钮内纯文本
        inner = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if inner:
            print(f"  text={inner!r:20} class={cls.group(1) if cls else ''!r}")

    print("\n=== '新增投标单位' 上下文 ===")
    idx = H.find("新增投标单位")
    if idx > 0:
        print(H[idx-300:idx+200])


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
