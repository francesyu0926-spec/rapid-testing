# -*- coding: utf-8 -*-
"""招投标平台 API 客户端：统一处理 Token 鉴权、返回码解析、超时与日志。

平台约定（见接口文档）：
  - 鉴权：`token` 参数 或 `Token` 请求头；两者都带最稳妥。
  - 统一返回：{"code":1,"msg":"...","result"/"data":...}
  - code=1 成功；code=-1 失败；code=202 Token 过期。
"""

import sys
import time
import requests
import urllib3

# 关闭 verify_ssl 时抑制 InsecureRequestWarning 噪音
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Windows 控制台/重定向默认 GBK，含中文及符号时易报 UnicodeEncodeError；
# 统一切到 UTF-8 并对无法编码的字符做替换，保证长流程日志不中断。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def log(msg: str, *, indent: int = 0):
    """统一日志输出（即时刷新，便于长流程观察）。"""
    prefix = "  " * indent
    try:
        print(f"{prefix}{msg}", flush=True)
    except UnicodeEncodeError:
        print(f"{prefix}{msg}".encode("utf-8", "replace").decode("utf-8", "replace"),
              flush=True)


class ApiResult:
    """对单次接口响应的统一封装。"""

    def __init__(self, status_code: int, payload, method: str, url: str):
        self.status_code = status_code
        self.raw = payload
        self.method = method
        self.url = url
        if isinstance(payload, dict):
            self.code = payload.get("code")
            self.msg = payload.get("msg") or payload.get("message") or ""
            # result 优先，其次 data
            self.data = payload.get("result", payload.get("data"))
        else:
            self.code = None
            self.msg = ""
            self.data = payload

    @property
    def ok(self) -> bool:
        return self.code == 1

    @property
    def token_expired(self) -> bool:
        return self.code == 202

    def get(self, *keys, default=None):
        """从 data 里安全取嵌套键：res.get('userinfo','token')。"""
        cur = self.data
        for k in keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
        return cur

    def brief(self) -> str:
        d = self.data
        if isinstance(d, (dict, list)):
            text = str(d)
            if len(text) > 200:
                text = text[:200] + "..."
        else:
            text = str(d)
        return f"[HTTP {self.status_code}] code={self.code} msg={self.msg!r} data={text}"


class ApiClient:
    """单个角色/会话的 API 客户端。"""

    def __init__(self, base_url: str, api_prefix: str = "/api", token: str = "",
                 timeout: int = 30, verify_ssl: bool = True, label: str = "",
                 dry_run: bool = False):
        self.base_url = base_url.rstrip("/")
        self.api_prefix = "/" + api_prefix.strip("/") if api_prefix else ""
        self.token = token or ""
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.label = label  # 角色名，便于日志区分
        self.dry_run = dry_run
        self.session = requests.Session()

    def set_token(self, token: str):
        self.token = token or ""

    def _url(self, path: str) -> str:
        return f"{self.base_url}{self.api_prefix}/{path.lstrip('/')}"

    def request(self, method: str, path: str, *, params=None, data=None,
                json=None, files=None, auth: bool = True,
                is_write: bool = False) -> ApiResult:
        """发起请求并返回 ApiResult。

        is_write=True 且处于 dry_run 时，仅打印请求不实际发送（演练模式）。
        """
        url = self._url(path)
        params = dict(params or {})
        headers = {}
        if auth and self.token:
            headers["Token"] = self.token
            params.setdefault("token", self.token)

        if is_write and self.dry_run:
            log(f"[DRY-RUN] {method} {url} params={params} data={data} "
                f"json={json} files={'有' if files else '无'}", indent=2)
            return ApiResult(0, {"code": 1, "msg": "dry-run(未实际发送)",
                                 "result": {"dry_run": True}}, method, url)

        try:
            resp = self.session.request(
                method=method.upper(), url=url, params=params, data=data,
                json=json, files=files, headers=headers,
                timeout=self.timeout, verify=self.verify_ssl,
            )
        except requests.RequestException as e:
            return ApiResult(-1, {"code": -1, "msg": f"请求异常: {e}"}, method, url)

        try:
            payload = resp.json()
        except ValueError:
            payload = {"code": None, "msg": "非JSON响应",
                       "_text": (resp.text or "")[:500]}
        return ApiResult(resp.status_code, payload, method, url)

    def get(self, path: str, **kw) -> ApiResult:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw) -> ApiResult:
        return self.request("POST", path, **kw)
