# -*- coding: utf-8 -*-
"""后台（admin 应用）客户端：用 PHPSESSID 会话访问 /zjgj230214/* 列表接口。

后台 layui 表格接口返回格式通常为 {"code":0,"msg":"","count":N,"data":[...]}，
与前端 /api 的 {"code":1,...} 不同，这里直接返回解析后的 dict。
"""

import requests

from client import log


class AdminClient:
    def __init__(self, base_url: str, prefix: str, php_session: str,
                 timeout: int = 30, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.prefix = "/" + prefix.strip("/") if prefix else ""
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.session.cookies.set("PHPSESSID", php_session)
        self.session.headers.update({
            "accept": "application/json, text/javascript, */*; q=0.01",
            "accept-language": "zh-CN,zh;q=0.9",
            "x-requested-with": "XMLHttpRequest",
            "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/148.0.0.0 Safari/537.36"),
        })

    def _url(self, path: str) -> str:
        return f"{self.base_url}{self.prefix}/{path.lstrip('/')}"

    def get(self, path: str, params: dict = None, referer: str = None) -> dict:
        headers = {}
        if referer:
            headers["referer"] = referer
        try:
            resp = self.session.get(self._url(path), params=params or {},
                                    headers=headers, timeout=self.timeout,
                                    verify=self.verify_ssl)
        except requests.RequestException as e:
            return {"_error": f"请求异常: {e}"}
        try:
            return resp.json()
        except ValueError:
            return {"_status": resp.status_code, "_text": (resp.text or "")[:800]}

    # --------------------------- 业务列表 --------------------------- #
    def list_projects(self, page: int = 1, limit: int = 20) -> dict:
        """公示项目列表。"""
        return self.get(
            "/PublicityProject/getList.html",
            params={"tableUniqueStr": "admin_publicityproject_index",
                    "page": page, "limit": limit},
            referer=self._url("/PublicityProject/index.html"),
        )

    def list_registers(self, project_id, page: int = 1, limit: int = 50) -> dict:
        """某项目的报名人员列表（含 registerId）。"""
        params = {
            "tableUniqueStr": "admin_projectregister_index",
            "id": project_id,
            "0[0]": "project_id",
            "0[1]": "=",
            "0[2]": project_id,
            "page": page,
            "limit": limit,
        }
        return self.get(
            "/ProjectRegister/getList.html", params=params,
            referer=self._url(f"/ProjectRegister/index.html"
                              f"?tableUniqueStr=admin_publicityproject_index&id={project_id}"),
        )

    def list_users(self, role: str = "formal", page: int = 1, limit: int = 50,
                   keyword: str = None) -> dict:
        """用户列表。role: manager=项目经理列表 / formal=正式会员(含投标人)。
        可选 keyword 按昵称/手机号搜索（后台搜索字段）。"""
        table = {
            "manager": "admin_user_manager",
            "formal": "admin_user_formal",
        }.get(role, "admin_user_formal")
        params = {"tableUniqueStr": table, "page": page, "limit": limit}
        if keyword:
            params["keyword"] = keyword
        return self.get("/user/getList.html", params=params,
                        referer=self._url("/user/index.html"))

    def resolve_code(self, code: str) -> int:
        """把用户 code（邀请码）解析为数字 uid。扫描 项目经理/正式会员 列表并缓存。
        找到返回 uid（int），未找到返回 0。"""
        code = str(code).strip()
        cache = getattr(self, "_code_map", None)
        if cache is None:
            cache = {}
            for role in ("manager", "formal"):
                for page in range(1, 81):
                    rows = self.rows(self.list_users(role=role, page=page, limit=100))
                    if not rows:
                        break
                    for row in rows:
                        cd = row.get("code")
                        if cd and cd not in cache:
                            cache[cd] = row.get("id")
                    if len(rows) < 100:
                        break
            self._code_map = cache
        return int(cache.get(code) or 0)

    def mint_token(self, uid) -> str:
        """后台「模拟登录」给指定用户签发前端 /api token（绕过微信/密码）。
        成功返回 token 字符串，失败返回空串。"""
        try:
            resp = self.session.get(
                self._url("/user/login.html"), params={"id": uid},
                timeout=self.timeout, verify=self.verify_ssl,
                allow_redirects=False,
            )
        except requests.RequestException as e:
            log(f"[mint_token] uid={uid} 请求异常: {e}")
            return ""
        token = resp.cookies.get("token")
        if not token:
            # 兜底：从 Set-Cookie 头解析
            raw = resp.headers.get("Set-Cookie", "")
            for part in raw.split(","):
                part = part.strip()
                if part.startswith("token="):
                    token = part[len("token="):].split(";", 1)[0]
                    break
        # mint 会把 token 写进当前 session，清掉以免影响后续 admin 调用语义
        self.session.cookies.pop("token", None)
        if not token:
            log(f"[mint_token] uid={uid} 未拿到 token：{(resp.text or '')[:120]}")
        return token or ""

    @staticmethod
    def rows(payload: dict) -> list:
        """从 layui 返回里取数据行。"""
        if isinstance(payload, dict):
            for k in ("data", "list", "rows"):
                if isinstance(payload.get(k), list):
                    return payload[k]
        return []
