# 招投标全流程接口模拟器

用接口（REST API）按业务顺序**模拟跑通一整条招投标流程**——不是断言式自动化测试，
而是以各角色身份依次调用平台 `/api/*` 接口，把"发布→邀请→报名→缴费→递交→开标→
评审→中标→报告签名"这条链路真实执行一遍，并打印每一步结果。

依据文档：
- 接口：《招标担保平台（ZJGJ）项目结构与接口文档》（ThinkPHP6，`/api`，Token 鉴权）
- 业务：《掌上微采购项目（三期）需求规格说明书 v1.4》（开标及评标章节）

## 目录

```
api_tests/
├── requirements.txt        # 依赖：requests, PyYAML
├── config.example.yaml     # 配置样例（复制为 config.yaml 后填写）
├── client.py               # ApiClient：Token 鉴权 / 统一返回码解析 / 日志
├── endpoints.py            # 按模块封装的接口方法
├── flow.py                 # TenderSimulator：全生命周期编排
├── run.py                  # 入口：加载配置、各角色登录取 token、跑整条流程
└── README.md
```

## 使用

```bash
cd api_tests
pip install -r requirements.txt
cp config.example.yaml config.yaml      # Windows: copy
# 编辑 config.yaml：填 base_url 与各角色账号(token 或 用户名/密码)

# 1) 演练模式（默认）：写操作只打印不发送，先看流程编排是否正确
python run.py

# 2) 真实执行：会创建项目/报名/递交等正式数据
python run.py --allow-writes

# 缴费处理：real(真实支付,通常跑不通) / mock(假定已缴) / skip(跳过)
python run.py --allow-writes --payment-mode skip
```

## 角色与流程

模拟器按 `flow.py::TenderSimulator.run()` 顺序编排：

| 步骤 | 角色 | 接口 |
|------|------|------|
| 1 发布招标项目 | 项目经理 | `publicity/cate,pattern,company,create` |
| 2 邀请招标人/接受 | 项目经理→招标人 | `invite_project/invite,getInviteList,invite_operation` |
| 3 确认专家资质 | 专家 | `expert/info,apply` |
| 4 投标报名 | 投标人 | `project_register/check,register` |
| 5 缴费 | 投标人 | `project_register/paymentNew`（按 payment_mode） |
| 6 审核报名 | 项目经理 | `publicity/getRegisterListNew,registerAudit` |
| 7 递交投标文件 | 投标人 | `tender/getProject,submitFile` |
| 8 开标后解密 | 投标人 | `tender/decryptTenderFile`（需到开标时间） |
| 9 邀请/抽取专家 | 项目经理 | `manage/inviteExpert,addExpert,randomExtract` |
| 10 确认+签到 | 专家 | `expert/confirm,sign` |
| 11 组长推选 | 专家 | `expert/leaderVote` |
| 12 各阶段评审 | 专家 | `expert/reviewList,saveReview,checkReview,getOfferScore` |
| 13 最终候选人 | 项目经理 | `manage/getCandidate` |
| 14 报告/签名 | 项目经理+专家 | `manage/getReport,saveReport,pushTenderReport`,`expert/quickSign,reportSign` |

## 重要约束（接口本身的限制）

- **缴费**：微信/支付宝支付无法纯接口自动完成。`payment_mode` 控制降级（skip/mock/real）。
  若后端有测试态或管理员确认入口，可在 `endpoints.py` 增补后改 mock。
- **开标时间**：项目"已开标"由开标时间到达触发，接口无法快进时间。第 8 步若未到点会
  失败/跳过，属预期；可在后台把开标时间改到过去，或等定时任务推进后重跑后续步骤。
- **字段差异**：部分写接口的请求体字段在不同环境略有出入（评审阶段 `type` 取值尤其如此）。
  模拟器对返回做了防御式解析并打印 `code/msg/data`，**先跑演练模式看日志，再据实微调**
  `flow.py` 里对应步骤的 payload。
- **数据隔离**：`config.yaml` 已建议加入 `.gitignore`，避免把真实 token 提交到仓库。
