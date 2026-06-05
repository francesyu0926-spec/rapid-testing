# -*- coding: utf-8 -*-
"""按业务模块封装平台 API（前端 /api 应用）。

每个方法直接返回 ApiResult。仅封装“招投标全生命周期”用得到的接口，
分组与接口文档一致：login / index / publicity / project_register /
tender / expert / manage / invite_project / assure。

注意：部分接口的请求体字段在不同环境可能略有差异，这里按接口文档/需求书
给出常见字段，跑通后可据响应日志微调（见 README）。
"""

from client import ApiClient, ApiResult


class Api:
    """绑定到单个角色客户端的接口集合。"""

    def __init__(self, client: ApiClient):
        self.c = client

    @property
    def label(self) -> str:
        return self.c.label

    # ----------------------------- 登录 / 公共 ----------------------------- #
    def login_check(self, username: str, password: str) -> ApiResult:
        return self.c.post("/login/check",
                           data={"username": username, "password": password},
                           auth=False)

    def user_index(self) -> ApiResult:
        return self.c.get("/user/index")

    def index_communal(self) -> ApiResult:
        return self.c.get("/index/communal", auth=False)

    # ----------------------------- 招标人邀请 ----------------------------- #
    # invite_project：邀请加入项目 / 招标人邀请
    def invite_tenderee(self, project_id, **extra) -> ApiResult:
        data = {"project_id": project_id}
        data.update(extra)
        return self.c.post("/invite_project/invite", data=data, is_write=True)

    def invite_list(self, page=1, limit=20) -> ApiResult:
        return self.c.get("/invite_project/getInviteList",
                          params={"page": page, "limit": limit})

    def invite_operation(self, invite_id, status: int) -> ApiResult:
        # status：1=同意 2=拒绝
        return self.c.get("/invite_project/invite_operation",
                          params={"id": invite_id, "status": status},
                          is_write=True)

    def tenderee_list(self, page=1, limit=20) -> ApiResult:
        return self.c.get("/invite_project/getTendereeList",
                          params={"page": page, "limit": limit})

    # ----------------------------- 公示/招标项目（项目经理） ----------------------------- #
    def publicity_cate(self) -> ApiResult:
        return self.c.get("/publicity/cate")

    def publicity_pattern(self) -> ApiResult:
        return self.c.get("/publicity/pattern")

    def publicity_company(self) -> ApiResult:
        return self.c.get("/publicity/company")

    def publicity_create(self, payload: dict) -> ApiResult:
        return self.c.post("/publicity/create", data=payload, is_write=True)

    def publicity_my_projects(self, page=1, limit=20, status="", keyword="") -> ApiResult:
        return self.c.get("/publicity/myProjectList",
                          params={"page": page, "limit": limit,
                                  "status": status, "keyword": keyword})

    def publicity_project_info(self, project_id) -> ApiResult:
        return self.c.get("/publicity/projectInfo", params={"project_id": project_id})

    def publicity_register_list(self, project_id, section_id, page=1, limit=20) -> ApiResult:
        return self.c.get("/publicity/getRegisterListNew",
                          params={"project_id": project_id, "section_id": section_id,
                                  "page": page, "limit": limit})

    def publicity_register_audit(self, register_id, status: int) -> ApiResult:
        # status：1=通过 0=拒绝
        return self.c.post("/publicity/registerAudit",
                           data={"register_id": register_id, "status": status},
                           is_write=True)

    # ----------------------------- 投标报名（投标人） ----------------------------- #
    def register_check(self, project_id, section_id) -> ApiResult:
        return self.c.post("/project_register/check",
                           data={"project_id": project_id, "section_id": section_id})

    def register(self, payload: dict) -> ApiResult:
        return self.c.post("/project_register/register", data=payload, is_write=True)

    def register_my_list(self, page=1, limit=20) -> ApiResult:
        return self.c.get("/project_register/myList",
                          params={"page": page, "limit": limit})

    def register_info(self, register_id) -> ApiResult:
        return self.c.get("/project_register/info", params={"id": register_id})

    def register_payment(self, payload: dict, v3: bool = True) -> ApiResult:
        path = "/project_register/paymentNew" if v3 else "/project_register/payment"
        return self.c.post(path, data=payload, is_write=True)

    # ----------------------------- 投标递交（投标人） ----------------------------- #
    def tender_my_list(self, page=1, limit=20, status="", keyword="") -> ApiResult:
        return self.c.get("/tender/myList",
                          params={"page": page, "limit": limit,
                                  "status": status, "keyword": keyword})

    def tender_get_project(self, tender_id, section_id) -> ApiResult:
        return self.c.get("/tender/getProject",
                          params={"tender_id": tender_id, "section_id": section_id})

    def tender_submit_file(self, payload: dict) -> ApiResult:
        # payload: tender_id, section_id, files, apply_id, (password)
        return self.c.post("/tender/submitFile", data=payload, is_write=True)

    def tender_get_file(self, tender_id, section_id) -> ApiResult:
        return self.c.get("/tender/getTenderFile",
                          params={"tender_id": tender_id, "section_id": section_id})

    def tender_withdraw(self, tender_id, section_id) -> ApiResult:
        return self.c.post("/tender/withdrawTenderFile",
                           data={"tender_id": tender_id, "section_id": section_id},
                           is_write=True)

    def tender_decrypt(self, tender_id, section_id, password) -> ApiResult:
        return self.c.post("/tender/decryptTenderFile",
                           data={"tender_id": tender_id, "section_id": section_id,
                                 "password": password}, is_write=True)

    def tender_signature(self, file_id, signature) -> ApiResult:
        return self.c.post("/tender/signature",
                           data={"id": file_id, "signature": signature}, is_write=True)

    def tender_two_offer(self, file_id, amount) -> ApiResult:
        return self.c.post("/tender/twoOffer",
                           data={"id": file_id, "amount": amount}, is_write=True)

    def tender_offer_list(self, project_id, section_id, page=1, limit=20, status="") -> ApiResult:
        return self.c.get("/tender/offerList",
                          params={"project_id": project_id, "section_id": section_id,
                                  "page": page, "limit": limit, "status": status})

    # ----------------------------- 项目经理-开标管理 ----------------------------- #
    def manage_project_list(self, page=1, limit=20, status="", keyword="") -> ApiResult:
        return self.c.get("/manage/getProjectList",
                          params={"page": page, "limit": limit,
                                  "status": status, "keyword": keyword})

    def manage_progress(self, project_id, section_id) -> ApiResult:
        return self.c.get("/manage/getProgress",
                          params={"project_id": project_id, "section_id": section_id})

    def manage_invite_expert(self, project_id, section_id) -> ApiResult:
        return self.c.get("/manage/inviteExpert",
                          params={"project_id": project_id, "section_id": section_id})

    def manage_random_extract(self, project_id, section_id, **extra) -> ApiResult:
        data = {"project_id": project_id, "section_id": section_id}
        data.update(extra)
        return self.c.post("/manage/randomExtract", data=data, is_write=True)

    def manage_add_expert(self, project_id, section_id, expert_id) -> ApiResult:
        return self.c.post("/manage/addExpert",
                           data={"project_id": project_id, "section_id": section_id,
                                 "expert_id": expert_id}, is_write=True)

    def manage_allow_offer(self, project_id, section_id) -> ApiResult:
        return self.c.post("/manage/allowOffer",
                           data={"project_id": project_id, "section_id": section_id},
                           is_write=True)

    def manage_get_candidate(self, project_id, section_id) -> ApiResult:
        return self.c.get("/manage/getCandidate",
                          params={"project_id": project_id, "section_id": section_id})

    def manage_get_report(self, project_id, section_id) -> ApiResult:
        return self.c.get("/manage/getReport",
                          params={"project_id": project_id, "section_id": section_id})

    def manage_save_report(self, project_id, section_id, content) -> ApiResult:
        return self.c.post("/manage/saveReport",
                           data={"project_id": project_id, "section_id": section_id,
                                 "content": content}, is_write=True)

    def manage_push_report(self, project_id, section_id) -> ApiResult:
        return self.c.get("/manage/pushTenderReport",
                          params={"project_id": project_id, "section_id": section_id},
                          is_write=True)

    def manage_company_list(self, project_id, section_id) -> ApiResult:
        return self.c.get("/manage/getCompanyList",
                          params={"project_id": project_id, "section_id": section_id})

    # ----------------------------- 专家评审 ----------------------------- #
    def expert_apply(self, payload: dict) -> ApiResult:
        return self.c.post("/expert/apply", data=payload, is_write=True)

    def expert_info(self) -> ApiResult:
        return self.c.get("/expert/info")

    def expert_my_list(self, page=1, limit=20, status="", keyword="") -> ApiResult:
        return self.c.get("/expert/myList",
                          params={"page": page, "limit": limit,
                                  "status": status, "keyword": keyword})

    def expert_confirm(self, invite_id, status: int) -> ApiResult:
        # status：1=出席 2=不出席
        return self.c.post("/expert/confirm",
                           data={"invite_id": invite_id, "status": status},
                           is_write=True)

    def expert_sign(self, project_id, section_id) -> ApiResult:
        return self.c.post("/expert/sign",
                           data={"project_id": project_id, "section_id": section_id},
                           is_write=True)

    def expert_check_sign(self, project_id, section_id) -> ApiResult:
        return self.c.get("/expert/checkSign",
                          params={"project_id": project_id, "section_id": section_id})

    def expert_leader_vote(self, project_id, section_id, uid) -> ApiResult:
        return self.c.get("/expert/leaderVote",
                          params={"project_id": project_id, "section_id": section_id,
                                  "uid": uid}, is_write=True)

    def expert_review_list(self, project_id, section_id, review_type, flowtype="") -> ApiResult:
        return self.c.get("/expert/reviewList",
                          params={"project_id": project_id, "section_id": section_id,
                                  "type": review_type, "flowtype": flowtype})

    def expert_save_review(self, payload: dict) -> ApiResult:
        return self.c.post("/expert/saveReview", data=payload, is_write=True)

    def expert_save_opinion(self, project_id, section_id, flow_type, opinion) -> ApiResult:
        return self.c.post("/expert/saveOpinion",
                           data={"project_id": project_id, "section_id": section_id,
                                 "flow_type": flow_type, "opinion": opinion},
                           is_write=True)

    def expert_check_review(self, project_id, section_id, flow_type) -> ApiResult:
        return self.c.post("/expert/checkReview",
                           data={"project_id": project_id, "section_id": section_id,
                                 "flow_type": flow_type}, is_write=True)

    def expert_get_offer_score(self, project_id, section_id) -> ApiResult:
        return self.c.get("/expert/getOfferScore",
                          params={"project_id": project_id, "section_id": section_id})

    def expert_allow_bargain(self, project_id, section_id) -> ApiResult:
        return self.c.post("/expert/allowBargain",
                           data={"project_id": project_id, "section_id": section_id},
                           is_write=True)

    def expert_check_offer(self, project_id, section_id) -> ApiResult:
        return self.c.post("/expert/checkOffer",
                           data={"project_id": project_id, "section_id": section_id})

    def expert_report(self, project_id, section_id) -> ApiResult:
        return self.c.get("/expert/report",
                          params={"project_id": project_id, "section_id": section_id})

    def expert_report_sign(self, project_id, section_id) -> ApiResult:
        return self.c.post("/expert/reportSign",
                           data={"project_id": project_id, "section_id": section_id},
                           is_write=True)

    def expert_quick_sign(self, project_id, section_id) -> ApiResult:
        return self.c.get("/expert/quickSign",
                          params={"project_id": project_id, "section_id": section_id},
                          is_write=True)
