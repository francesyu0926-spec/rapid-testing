# -*- coding: utf-8 -*-
"""招投标流程模拟器入口。

用法：
  1) 复制 config.example.yaml 为 config.yaml，填入 base_url 与各角色账号/token
  2) 安装依赖：pip install -r requirements.txt
  3) 运行：    python run.py            （默认读取 ./config.yaml）
               python run.py -c other.yaml
               python run.py --allow-writes      # 真实写入（创建项目/报名等）
               python run.py --payment-mode mock
"""

import argparse
import os
import sys

import yaml

from client import ApiClient, log
from endpoints import Api
from flow import TenderSimulator
from admin_client import AdminClient


def _extract_token(res) -> str:
    """从登录返回里尽力找出 token。"""
    candidates = ("token", "Token", "userToken", "access_token", "api_token")

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in candidates and isinstance(v, str) and v:
                    return v
            for v in obj.values():
                found = walk(v)
                if found:
                    return found
        elif isinstance(obj, list):
            for v in obj:
                found = walk(v)
                if found:
                    return found
        return ""

    return walk(res.data) or walk(res.raw)


def build_client(acct: dict, base_url, api_prefix, opts, label, dry_run,
                 admin: AdminClient = None) -> Api | None:
    """根据账号配置构建并鉴权一个角色客户端；无可用凭证则返回 None。

    鉴权优先级：token > uid(后台模拟登录免微信签发) > username/password。
    """
    if not acct:
        return None
    token = (acct.get("token") or "").strip()
    username = (acct.get("username") or "").strip()
    password = (acct.get("password") or "").strip()
    uid = acct.get("uid")
    code = (acct.get("code") or "").strip() if acct.get("code") else None
    # code 模式：先把邀请码解析为 uid
    if not token and not uid and code and admin is not None:
        uid = admin.resolve_code(code)
        if uid:
            log(f"[{label}] code={code} 解析为 uid={uid}")
        else:
            log(f"[{label}] code={code} 未能解析到 uid")
    # uid 模式：用后台会话给该用户签发 /api token（绕过微信登录）
    if not token and uid and admin is not None:
        token = admin.mint_token(uid)
        if token:
            log(f"[{label}] 后台模拟登录成功，已为 uid={uid} 签发 token")
        else:
            log(f"[{label}] 后台模拟登录失败 uid={uid}")
    if not token and not username:
        return None

    client = ApiClient(
        base_url=base_url, api_prefix=api_prefix, token=token,
        timeout=opts.get("timeout", 30), verify_ssl=opts.get("verify_ssl", True),
        label=label, dry_run=dry_run,
    )
    api = Api(client)
    if not token and username:
        res = api.login_check(username, password)
        if res.ok:
            tok = _extract_token(res)
            if tok:
                client.set_token(tok)
                log(f"[{label}] 账号登录成功，已获取 token")
            else:
                log(f"[{label}] 登录成功但未解析到 token，后续鉴权可能失败：{res.brief()}")
        else:
            log(f"[{label}] 账号登录失败：{res.brief()}")
            return None
    else:
        log(f"[{label}] 使用配置的 token")
    return api


def main():
    parser = argparse.ArgumentParser(description="招投标全流程接口模拟器")
    parser.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--allow-writes", action="store_true",
                        help="真实写入（覆盖配置；会产生正式数据）")
    parser.add_argument("--payment-mode", choices=["real", "mock", "skip", "supplement"],
                        help="缴费处理方式（覆盖配置）")
    parser.add_argument("--stage", choices=["pay", "full"], default="full",
                        help="pay=只跑到'建项目+报名+补单'即停；full=完整流程")
    args = parser.parse_args()

    cfg_path = args.config
    if not os.path.exists(cfg_path):
        log(f"未找到配置文件 {cfg_path}。请复制 config.example.yaml 为 config.yaml 并填写。")
        sys.exit(1)
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    base_url = (cfg.get("base_url") or "").strip()
    if not base_url or "your-host" in base_url:
        log("请在配置文件中填写真实的 base_url。")
        sys.exit(1)
    api_prefix = cfg.get("api_prefix", "/api")
    opts = cfg.get("options", {})
    if args.allow_writes:
        opts["allow_writes"] = True
    if args.payment_mode:
        opts["payment_mode"] = args.payment_mode
    cfg["options"] = opts

    allow_writes = bool(opts.get("allow_writes", False))
    dry_run = not allow_writes
    if dry_run:
        log("【演练模式】allow_writes=false：所有写操作只打印不实际发送。"
            "确认无误后加 --allow-writes 真实执行。")

    # 后台会话：用于按 uid 给各角色签发 token（绕过微信登录）
    admin = None
    adm_cfg = cfg.get("admin") or {}
    if (adm_cfg.get("php_session") or "").strip():
        admin = AdminClient(base_url, adm_cfg.get("prefix", ""),
                            adm_cfg["php_session"], timeout=opts.get("timeout", 30),
                            verify_ssl=opts.get("verify_ssl", True))

    accounts = cfg.get("accounts", {})
    manager = build_client(accounts.get("manager"), base_url, api_prefix, opts,
                           "项目经理", dry_run, admin)
    if manager is None:
        log("项目经理账号未配置或登录失败，无法发起流程。")
        sys.exit(1)
    tenderee = build_client(accounts.get("tenderee"), base_url, api_prefix, opts,
                            "招标人", dry_run, admin)
    bidders = []
    for i, acct in enumerate(accounts.get("bidders") or [], 1):
        api = build_client(acct, base_url, api_prefix, opts,
                           acct.get("name") or f"投标人{i}", dry_run, admin)
        if api:
            bidders.append(api)
    experts = []
    for i, acct in enumerate(accounts.get("experts") or [], 1):
        api = build_client(acct, base_url, api_prefix, opts,
                           acct.get("name") or f"专家{i}", dry_run, admin)
        if api:
            experts.append(api)

    log(f"角色就绪：项目经理 OK  招标人 {'OK' if tenderee else '未配置'}  "
        f"投标人×{len(bidders)}  专家×{len(experts)}")

    sim = TenderSimulator(manager, tenderee, bidders, experts, cfg)
    stop_after = "pay" if args.stage == "pay" else None
    sim.run(stop_after=stop_after)


if __name__ == "__main__":
    main()
