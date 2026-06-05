# -*- coding: utf-8 -*-
"""免微信取 token 工具：基于后台 PHPSESSID 会话。

依赖后台「模拟登录」(/user/login?id=uid) —— 该接口会在 Set-Cookie 下发该用户的
前端 /api token，可直接用于 /api 鉴权。无需微信授权、无需账号密码。

用法：
  python tokens.py list --role manager           # 列项目经理(uid/昵称/手机号)
  python tokens.py list --role formal -k 13800    # 列正式会员，按关键字搜索
  python tokens.py mint --uid 11075               # 给某 uid 签发 token 并校验
"""

import argparse
import sys

import yaml
import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from admin_client import AdminClient


def load_cfg(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def make_admin(cfg):
    adm = cfg.get("admin") or {}
    if not (adm.get("php_session") or "").strip() and not (adm.get("username") or "").strip():
        print("config.yaml 缺少 admin.php_session 或 admin.username/password"); sys.exit(1)
    opts = cfg.get("options", {})
    return AdminClient(cfg["base_url"], adm.get("prefix", ""), adm.get("php_session", ""),
                       timeout=opts.get("timeout", 30),
                       verify_ssl=opts.get("verify_ssl", True),
                       username=adm.get("username", ""), password=adm.get("password", ""))


def cmd_list(cfg, args):
    adm = make_admin(cfg)
    r = adm.list_users(role=args.role, page=args.page, limit=args.limit,
                       keyword=args.keyword)
    rows = AdminClient.rows(r)
    if not rows:
        print(f"无数据。返回：{str(r)[:200]}"); return
    print(f"{'uid':>8}  {'手机号':<13} 昵称 / 角色")
    print("-" * 60)
    for row in rows:
        types = row.get("user_type_name")
        types = "/".join(types) if isinstance(types, list) else (types or "")
        print(f"{str(row.get('id')):>8}  {str(row.get('mobile') or ''):<13} "
              f"{row.get('nickname') or ''}  [{types}]")


def cmd_mint(cfg, args):
    adm = make_admin(cfg)
    token = adm.mint_token(args.uid)
    if not token:
        print(f"uid={args.uid} 取 token 失败"); return
    print(f"uid={args.uid} token = {token}")
    # 校验
    base = cfg["base_url"].rstrip("/")
    verify = cfg.get("options", {}).get("verify_ssl", True)
    try:
        resp = requests.get(base + "/api/user/index", headers={"token": token},
                            timeout=20, verify=verify)
        data = resp.json()
        if data.get("code") == 1:
            d = data.get("data", {})
            print(f"校验OK：{d.get('user_type_name')} mobile={d.get('mobile')}")
        else:
            print(f"校验异常：{str(data)[:200]}")
    except Exception as e:
        print(f"校验请求失败：{e}")


def main():
    p = argparse.ArgumentParser(description="免微信取 token（后台模拟登录）")
    p.add_argument("-c", "--config", default="config.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="列用户")
    pl.add_argument("--role", choices=["manager", "formal"], default="formal")
    pl.add_argument("-k", "--keyword", default=None, help="昵称/手机号关键字")
    pl.add_argument("--page", type=int, default=1)
    pl.add_argument("--limit", type=int, default=30)

    pm = sub.add_parser("mint", help="给 uid 签发并校验 token")
    pm.add_argument("--uid", required=True)

    args = p.parse_args()
    cfg = load_cfg(args.config)
    if args.cmd == "list":
        cmd_list(cfg, args)
    elif args.cmd == "mint":
        cmd_mint(cfg, args)


if __name__ == "__main__":
    main()
