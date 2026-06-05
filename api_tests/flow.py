# -*- coding: utf-8 -*-
"""TenderSimulator：用接口按业务顺序模拟整条招投标流程。

角色编排（对应需求《掌上微采购三期》开标及评标章节）：
  项目经理发布项目 -> 邀请招标人/招标人接受 -> 确认专家资质
  -> 投标人报名 -> 缴费 -> 项目经理审核报名 -> 投标人递交投标文件
  -> (到开标时间) 投标人签字解密 -> 项目经理邀请/抽取专家
  -> 专家确认出席/签到 -> 组长推选 -> 形式/资格/响应性评审
  -> (谈判/磋商/二轮报价) -> 商务/技术/报价评分 -> 最终得分及候选人
  -> 出具评标报告/专家签名 -> 中标公示 / 代理费 / 归档

设计原则：
  - 每一步打印请求结果，状态记入 self.steps，最后输出汇总；
  - 单步失败按 on_error=continue/abort 决定是否中止；
  - 写操作在 dry_run（allow_writes=false）下只打印不发送；
  - 缴费/开标时间等无法纯接口推进的环节，按 payment_mode/说明降级或跳过。
"""

import time
from client import log, ApiClient
from endpoints import Api


class StopFlow(Exception):
    """on_error=abort 时用于中止整条流程。"""


class TenderSimulator:
    def __init__(self, manager: Api, tenderee, bidders, experts, config: dict):
        self.manager = manager
        self.tenderee = tenderee            # Api 或 None
        self.bidders = bidders or []        # list[Api]
        self.experts = experts or []        # list[Api]
        self.cfg = config
        self.opts = config.get("options", {})
        self.on_error = self.opts.get("on_error", "continue")
        self.payment_mode = self.opts.get("payment_mode", "skip")

        self.ctx = {
            "project_id": None,
            "section_id": None,
            "registers": {},      # bidder_label -> register_id
            "tender_files": {},   # bidder_label -> tender_file_id
            "leader_uid": None,
        }
        self.steps = []           # [(name, status, detail)]

    # ------------------------------- 步骤记录 ------------------------------- #
    def _record(self, name: str, status: str, detail: str = ""):
        self.steps.append((name, status, detail))
        log(f"[{status}] {name}{' - ' + detail if detail else ''}", indent=1)
        if status == "FAIL" and self.on_error == "abort":
            raise StopFlow(name)

    def _need(self, *keys) -> bool:
        """确保上下文里有必要的 id；缺失则返回 False。"""
        return all(self.ctx.get(k) for k in keys)

    # ================================ 主流程 ================================ #
    # 有序步骤表：key 供 stop_after 截断使用
    def _ordered_steps(self):
        return [
            ("publish", self.step_publish_project),
            ("register", self.step_bidders_register),
            ("audit", self.step_manager_audit_register),
            ("pay", self.step_bidders_pay),
            ("invite_tenderee", self.step_invite_tenderee),
            ("experts_ready", self.step_experts_ready),
            ("submit_file", self.step_bidders_submit_file),
            ("decrypt", self.step_open_bid_and_decrypt),
            ("invite_experts", self.step_manager_invite_experts),
            ("confirm_sign", self.step_experts_confirm_sign),
            ("leader", self.step_leader_election),
            ("reviews", self.step_reviews),
            ("candidate", self.step_final_candidate),
            ("report", self.step_report_and_sign),
        ]

    def run(self, stop_after: str = None):
        """按序执行流程；stop_after 指定某步 key 时，执行完该步即停止。"""
        log("=" * 64)
        log("招投标全流程接口模拟开始" + (f"（执行至 {stop_after} 即停）" if stop_after else ""))
        log("=" * 64)
        try:
            for key, fn in self._ordered_steps():
                fn()
                if stop_after and key == stop_after:
                    log(f"已执行至 [{key}]，按 stop_after 停止。", indent=1)
                    break
        except StopFlow as e:
            log(f"流程在步骤 [{e}] 中止（on_error=abort）")
        self._summary()

    # ------------------------------- 1 发布项目 ------------------------------- #
    def step_publish_project(self):
        name = "项目经理发布招标项目"
        pj = self.cfg.get("project", {})
        # 先拉基础字典（招标类型/方式/代理公司），失败不致命
        self.manager.publicity_cate()
        self.manager.publicity_pattern()
        self.manager.publicity_company()

        payload = {
            "project_name": pj.get("project_name", "接口模拟-测试项目"),
            "pattern_id": pj.get("pattern_id", 1),
            "cate_id": pj.get("cate_id", 1),
            "file_fee": pj.get("file_fee", "100"),
            "platform_fee": pj.get("platform_fee", "100"),
            "is_lowest_price": pj.get("is_lowest_price", 0),
            "need_audit": pj.get("need_audit", 1),
            "open_public_register": pj.get("open_public_register", 1),
        }
        res = self.manager.publicity_create(payload)
        if not res.ok:
            self._record(name, "FAIL", res.brief())
            return
        # 从返回或“我的项目”里解析 project_id / section_id
        pid = res.get("project_id") or res.get("id") or res.get("projectId")
        if not pid:
            mine = self.manager.publicity_my_projects(page=1, limit=5)
            rows = self._rows(mine)
            if rows:
                pid = rows[0].get("project_id") or rows[0].get("id")
        if not pid:
            self._record(name, "FAIL", f"已创建但未解析到 project_id：{res.brief()}")
            return
        self.ctx["project_id"] = pid
        # 标段
        info = self.manager.publicity_project_info(pid)
        sid = self._first_section_id(info)
        self.ctx["section_id"] = sid or 0
        self._record(name, "OK", f"project_id={pid} section_id={self.ctx['section_id']}")

    # ------------------------------- 2 招标人邀请 ------------------------------- #
    def step_invite_tenderee(self):
        name = "邀请招标人并接受"
        if not self._need("project_id"):
            self._record(name, "SKIP", "缺少 project_id")
            return
        if self.tenderee is None:
            self._record(name, "SKIP", "未配置招标人账号")
            return
        inv = self.manager.invite_tenderee(self.ctx["project_id"])
        if not inv.ok:
            self._record(name, "FAIL", f"发起邀请失败：{inv.brief()}")
            return
        # 招标人查看邀请并接受
        lst = self.tenderee.invite_list()
        rows = self._rows(lst)
        invite_id = rows[0].get("id") if rows else None
        if not invite_id:
            self._record(name, "FAIL", "招标人未查询到待处理邀请")
            return
        acc = self.tenderee.invite_operation(invite_id, status=1)
        self._record(name, "OK" if acc.ok else "FAIL", acc.brief())

    # ------------------------------- 3 专家资质 ------------------------------- #
    def step_experts_ready(self):
        name = "确认专家资质"
        if not self.experts:
            self._record(name, "SKIP", "未配置专家账号")
            return
        ready = 0
        for ex in self.experts:
            info = ex.expert_info()
            if info.ok and info.data:
                ready += 1
            else:
                # 未具备专家资质则提交申请（需后台审核，模拟环境下仅尝试）
                ex.expert_apply({"name": ex.label, "remark": "接口模拟申请"})
        self._record(name, "OK", f"{ready}/{len(self.experts)} 位已具备专家资质")

    # ------------------------------- 4 投标报名 ------------------------------- #
    def step_bidders_register(self):
        name = "投标人报名"
        if not self._need("project_id"):
            self._record(name, "SKIP", "缺少 project_id")
            return
        if not self.bidders:
            self._record(name, "SKIP", "未配置投标人账号")
            return
        ok = 0
        for b in self.bidders:
            b.register_check(self.ctx["project_id"], self.ctx["section_id"])
            payload = {
                "project_id": self.ctx["project_id"],
                "section_id": self.ctx["section_id"],
                "company_name": f"{b.label}有限公司",
                "company_address": "测试地址",
            }
            res = b.register(payload)
            if res.ok:
                ok += 1
                rid = res.get("register_id") or res.get("id")
                if not rid:
                    mine = b.register_my_list(limit=5)
                    rows = self._rows(mine)
                    rid = rows[0].get("id") if rows else None
                self.ctx["registers"][b.label] = rid
            else:
                log(f"{b.label} 报名失败：{res.brief()}", indent=2)
        self._record(name, "OK" if ok else "FAIL",
                     f"{ok}/{len(self.bidders)} 家报名成功")

    # ------------------------------- 5 缴费 ------------------------------- #
    def step_bidders_pay(self):
        name = "投标人缴费(文件费/平台使用费)"
        if self.payment_mode == "skip":
            self._record(name, "SKIP", "payment_mode=skip：跳过缴费")
            return
        if self.payment_mode == "mock":
            self._record(name, "SKIP", "payment_mode=mock：假定缴费已完成（需后端测试态支持）")
            return
        if not self.ctx["registers"]:
            self._record(name, "SKIP", "无报名记录可缴费")
            return
        if self.payment_mode == "supplement":
            self._pay_by_supplement(name)
            return
        # real：走真实支付接口
        ok = 0
        for b in self.bidders:
            rid = self.ctx["registers"].get(b.label)
            if not rid:
                continue
            res = b.register_payment({"id": rid, "pay_way": "wechat"}, v3=True)
            if res.ok:
                ok += 1
            else:
                log(f"{b.label} 缴费失败/需真实支付：{res.brief()}", indent=2)
        self._record(name, "OK" if ok else "FAIL", f"{ok} 家缴费返回成功")

    def _pay_by_supplement(self, name):
        """用配置的"补单"接口完成缴费（project_register/paymentErrorHandler）。

        优先用 payment.supplement.api_token 建专用客户端（补单接口通常用固定 token）；
        未配置则回退到 role 指定角色的客户端。
        """
        sup = (self.cfg.get("payment") or {}).get("supplement") or {}
        path = (sup.get("path") or "").strip()
        if not path:
            self._record(name, "SKIP", "payment_mode=supplement 但未配置 payment.supplement.path")
            return
        method = (sup.get("method") or "GET").upper()
        role = (sup.get("role") or "bidder").lower()
        tmpl = sup.get("params") or {"registerId": "{register_id}"}
        # role=bidder 时用各投标人自己的 token 补单（paymentErrorHandler 为用户自助补单）；
        # 其它角色才用 api_token 专用客户端。
        sup_client = None if role == "bidder" else self._supplement_client(sup)
        ok = 0
        for b in self.bidders:
            rid = self.ctx["registers"].get(b.label)
            if not rid:
                continue
            client = (sup_client or (b if role == "bidder"
                                     else self._client_for_role(role)))
            if client is None:
                log(f"补单客户端不可用，跳过 {b.label}", indent=2)
                continue
            subs = {"register_id": rid, "project_id": self.ctx["project_id"],
                    "section_id": self.ctx["section_id"], "bidder_label": b.label}
            payload = {k: self._fill(v, subs) for k, v in tmpl.items()}
            if method == "GET":
                res = client.c.request("GET", path, params=payload, is_write=True)
            else:
                res = client.c.request("POST", path, data=payload, is_write=True)
            if res.ok:
                ok += 1
            else:
                log(f"{b.label}(register={rid}) 补单失败：{res.brief()}", indent=2)
        self._record(name, "OK" if ok else "FAIL", f"补单成功 {ok} 家")

    def _supplement_client(self, sup: dict):
        """按 payment.supplement.api_token 构造专用补单客户端（复用 manager 的连接参数）。"""
        token = (sup.get("api_token") or "").strip()
        if not token:
            return None
        from endpoints import Api
        base = self.manager.c
        client = ApiClient(base.base_url, base.api_prefix.lstrip("/") or "api",
                           token=token, timeout=base.timeout,
                           verify_ssl=base.verify_ssl, label="补单",
                           dry_run=base.dry_run)
        return Api(client)

    def _client_for_role(self, role: str):
        if role in ("manager", "admin"):
            return self.manager
        if role == "tenderee":
            return self.tenderee
        return self.manager

    @staticmethod
    def _fill(value, subs: dict):
        """把模板里的 {key} 占位符替换为实际值（仅对字符串生效）。"""
        if isinstance(value, str):
            try:
                return value.format(**subs)
            except Exception:
                return value
        return value

    # ------------------------------- 6 报名审核 ------------------------------- #
    def step_manager_audit_register(self):
        name = "项目经理审核报名"
        if not self._need("project_id"):
            self._record(name, "SKIP", "缺少 project_id")
            return
        lst = self.manager.publicity_register_list(
            self.ctx["project_id"], self.ctx["section_id"], limit=50)
        rows = self._rows(lst)
        if not rows:
            self._record(name, "SKIP", "无报名记录待审核")
            return
        passed = 0
        for r in rows:
            rid = r.get("id") or r.get("register_id")
            if not rid:
                continue
            res = self.manager.publicity_register_audit(rid, status=1)
            if res.ok:
                passed += 1
        self._record(name, "OK" if passed else "FAIL", f"通过 {passed} 条报名")

    # ------------------------------- 7 递交投标文件 ------------------------------- #
    def step_bidders_submit_file(self):
        name = "投标人递交投标文件"
        if not self.bidders or not self._need("project_id"):
            self._record(name, "SKIP", "缺少投标人或 project_id")
            return
        ok = 0
        for b in self.bidders:
            proj = b.tender_get_project(self.ctx["project_id"], self.ctx["section_id"])
            tender_id = (proj.get("tender_id") or proj.get("id")
                         or self.ctx["project_id"])
            payload = {
                "tender_id": tender_id,
                "section_id": self.ctx["section_id"],
                "files": "",                      # 实环境填上传后的文件标识
                "apply_id": self.ctx["registers"].get(b.label, ""),
                "password": "Test123456",         # 解密密码（与后续解密一致）
            }
            res = b.tender_submit_file(payload)
            if res.ok:
                ok += 1
                fid = res.get("id") or res.get("tender_file_id")
                self.ctx["tender_files"][b.label] = fid or tender_id
            else:
                log(f"{b.label} 递交失败：{res.brief()}", indent=2)
        self._record(name, "OK" if ok else "FAIL", f"{ok} 家完成递交")

    # ------------------------------- 8 开标 + 解密 ------------------------------- #
    def step_open_bid_and_decrypt(self):
        name = "开标后签字解密"
        if not self.bidders or not self._need("project_id"):
            self._record(name, "SKIP", "缺少投标人或 project_id")
            return
        # 开标由“开标时间到达”触发，接口无法快进时间；这里仅尝试解密，
        # 若项目尚未到开标时间，解密接口通常返回失败（属预期）。
        ok = 0
        for b in self.bidders:
            tid = self.ctx["tender_files"].get(b.label) or self.ctx["project_id"]
            res = b.tender_decrypt(tid, self.ctx["section_id"], "Test123456")
            if res.ok:
                ok += 1
            else:
                log(f"{b.label} 解密未成功(可能未到开标时间)：{res.brief()}", indent=2)
        status = "OK" if ok else "SKIP"
        self._record(name, status,
                     f"{ok} 家解密成功" if ok else "未到开标时间或无递交文件，待人工/定时推进")

    # ------------------------------- 9 邀请/抽取专家 ------------------------------- #
    def step_manager_invite_experts(self):
        name = "项目经理邀请/抽取专家"
        if not self._need("project_id"):
            self._record(name, "SKIP", "缺少 project_id")
            return
        self.manager.manage_invite_expert(self.ctx["project_id"], self.ctx["section_id"])
        added = 0
        # 优先直接添加已配置的专家账号（需其 uid）；否则尝试随机抽取
        for ex in self.experts:
            info = ex.expert_info()
            uid = info.get("uid") or info.get("id") or info.get("user_id")
            if uid:
                res = self.manager.manage_add_expert(
                    self.ctx["project_id"], self.ctx["section_id"], uid)
                if res.ok:
                    added += 1
        if not added:
            self.manager.manage_random_extract(
                self.ctx["project_id"], self.ctx["section_id"], num=len(self.experts) or 3)
        self._record(name, "OK", f"添加专家 {added} 位"
                     if added else "已尝试随机抽取专家")

    # ------------------------------- 10 专家确认+签到 ------------------------------- #
    def step_experts_confirm_sign(self):
        name = "专家确认出席并签到"
        if not self.experts or not self._need("project_id"):
            self._record(name, "SKIP", "缺少专家或 project_id")
            return
        signed = 0
        for ex in self.experts:
            # 确认出席（需 invite_id；从专家项目列表里取）
            mine = ex.expert_my_list(limit=10)
            rows = self._rows(mine)
            invite_id = rows[0].get("invite_id") or rows[0].get("id") if rows else None
            if invite_id:
                ex.expert_confirm(invite_id, status=1)
            res = ex.expert_sign(self.ctx["project_id"], self.ctx["section_id"])
            if res.ok:
                signed += 1
        self._record(name, "OK" if signed else "FAIL",
                     f"{signed}/{len(self.experts)} 位完成签到")

    # ------------------------------- 11 组长推选 ------------------------------- #
    def step_leader_election(self):
        name = "评标组长推选"
        if not self.experts or not self._need("project_id"):
            self._record(name, "SKIP", "缺少专家或 project_id")
            return
        # 取第一位专家 uid 作为组长候选，所有专家投其一票
        leader_info = self.experts[0].expert_info()
        leader_uid = (leader_info.get("uid") or leader_info.get("id")
                      or leader_info.get("user_id"))
        if not leader_uid:
            self._record(name, "SKIP", "无法解析组长 uid")
            return
        self.ctx["leader_uid"] = leader_uid
        votes = 0
        for ex in self.experts:
            res = ex.expert_leader_vote(
                self.ctx["project_id"], self.ctx["section_id"], leader_uid)
            if res.ok:
                votes += 1
        self._record(name, "OK" if votes else "FAIL",
                     f"组长 uid={leader_uid}，{votes} 票")

    # ------------------------------- 12 评审阶段 ------------------------------- #
    def step_reviews(self):
        name = "专家评审(形式/资格/响应性/商务/技术/报价)"
        if not self.experts or not self._need("project_id"):
            self._record(name, "SKIP", "缺少专家或 project_id")
            return
        pid, sid = self.ctx["project_id"], self.ctx["section_id"]
        # 评审阶段 type 取值因环境而异，这里给出常见序列（1~6），实环境据
        # expert/reviewList 与 manage/getProgress 的返回调整。
        stages = [("形式评审", 1), ("资格评审", 2), ("响应性评审", 3),
                  ("商务评分", 4), ("技术评分", 5), ("报价评分", 6)]
        done = []
        for stage_name, t in stages:
            # 报价评分先取系统计算分
            if stage_name == "报价评分":
                self.experts[0].expert_get_offer_score(pid, sid)
            ok_any = False
            for ex in self.experts:
                ex.expert_review_list(pid, sid, review_type=t)
                res = ex.expert_save_review({
                    "project_id": pid, "section_id": sid,
                    "type": t, "result": 1,  # 1=符合/通过（或得分，按环境）
                })
                if res.ok:
                    ok_any = True
            # 组长确认本阶段
            self.experts[0].expert_check_review(pid, sid, flow_type=t)
            done.append(stage_name if ok_any else f"{stage_name}(未确认)")
        self._record(name, "OK", "；".join(done))

    # ------------------------------- 13 最终候选人 ------------------------------- #
    def step_final_candidate(self):
        name = "最终得分及候选人"
        if not self._need("project_id"):
            self._record(name, "SKIP", "缺少 project_id")
            return
        res = self.manager.manage_get_candidate(
            self.ctx["project_id"], self.ctx["section_id"])
        self._record(name, "OK" if res.ok else "FAIL", res.brief())

    # ------------------------------- 14 评标报告/签名 ------------------------------- #
    def step_report_and_sign(self):
        name = "评标报告生成/推送/专家签名"
        if not self._need("project_id"):
            self._record(name, "SKIP", "缺少 project_id")
            return
        pid, sid = self.ctx["project_id"], self.ctx["section_id"]
        self.manager.manage_get_report(pid, sid)
        self.manager.manage_save_report(pid, sid, content="接口模拟生成的评标报告")
        push = self.manager.manage_push_report(pid, sid)
        signed = 0
        for ex in self.experts:
            r = ex.expert_quick_sign(pid, sid)
            if not r.ok:
                r = ex.expert_report_sign(pid, sid)
            if r.ok:
                signed += 1
        self._record(name, "OK" if push.ok or signed else "FAIL",
                     f"推送={'成功' if push.ok else '失败'}，{signed} 位专家签名")

    # ------------------------------- 汇总 ------------------------------- #
    def _summary(self):
        log("=" * 64)
        log("流程模拟结果汇总")
        log("=" * 64)
        ok = sum(1 for _, s, _ in self.steps if s == "OK")
        fail = sum(1 for _, s, _ in self.steps if s == "FAIL")
        skip = sum(1 for _, s, _ in self.steps if s == "SKIP")
        for i, (n, s, d) in enumerate(self.steps, 1):
            log(f"{i:>2}. [{s}] {n}{' — ' + d if d else ''}")
        log("-" * 64)
        log(f"合计 {len(self.steps)} 步：OK {ok} / FAIL {fail} / SKIP {skip}")
        log(f"上下文：project_id={self.ctx['project_id']} "
            f"section_id={self.ctx['section_id']}")

    # ------------------------------- 工具 ------------------------------- #
    @staticmethod
    def _rows(res):
        """从列表型返回里抽出数据行（兼容 data 直接是 list 或 {list/data/rows:[...]}）。"""
        d = res.data
        if isinstance(d, list):
            return d
        if isinstance(d, dict):
            for k in ("list", "data", "rows", "records", "items"):
                if isinstance(d.get(k), list):
                    return d[k]
        return []

    @classmethod
    def _first_section_id(cls, res):
        d = res.data
        if isinstance(d, dict):
            secs = d.get("section") or d.get("sections") or d.get("section_list")
            if isinstance(secs, list) and secs:
                return secs[0].get("id") or secs[0].get("section_id")
            if d.get("section_id"):
                return d.get("section_id")
        return None
