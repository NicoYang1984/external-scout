---
name: lazymind-outreach-agent
description: 为 LazyMind 从 Scout V2 和用途明确的官方渠道筛选推广/合作对象，生成证据化个性邮件，执行批次审核、受控发送、回复归类和效果统计。用于媒体投稿、开发者协作和自愿业务试用；不用于未经许可的群发、抓取私人联系方式或自动催促。
---

# LazyMind Outreach Agent

默认只读发现和 dry-run。未同时满足用途许可、组织级去重、排除检查、网易个人邮箱两阶段自测、精确批次审批和授权发件账号时，不执行真实外发。V1.1 仅对通过门禁的个人 `@163.com` 账号开放受控接口，其他 provider 仍保持关闭。

## 运行入口

1. 定位 Scout V2 的 `opportunities.sqlite3`，先读其 `SKILL.md`、`ARCHITECTURE.md`、`references/source-schema.md` 和 SQLite `user_version`。通过 `scripts/scout_adapter.py` 只读导入；不得修改 Scout schema 或把 `not_granted` 提升为许可。
2. 按场景选择 `editorial_pitch`、`developer_collaboration` 或 `business_trial`。筛选与写作差异见 [references/campaigns.md](references/campaigns.md)。
3. 只采用官方投稿/合作入口、已有正式往来或主动申请试用记录。公开邮箱本身不构成许可；GitHub commit 邮箱、私人资料和推测身份一律不用。
4. 语言只根据官网、README、官方联系页或既有正式通信判断；证据不足写 `language_unknown` 并停止起草。不得记录或推测国籍、民族、族裔。
5. 草稿必须从对方已证实的痛点出发，提出可讨论的工作流，再说明 LazyMind 的真实能力、验证链接、已知限制、身份和单一步骤。没有真正相关的差异化内容就放弃。
6. 用 `scripts/outreach.py` 生成批次清单并由用户一次审批小批次。审批指纹绑定收件人、发件账号、主题和正文；其中任何一项变化都使旧审批失效。
   真实小批次默认每账号间隔 300 秒，跨批次与重启保留冷却；待发送和异常不算成功。需要在当前本机进程按节奏继续时使用 `--wait-for-interval`，不能以调整间隔绕过服务商限制。
7. 个人 163 账号先按 [NETEASE_SETUP.md](NETEASE_SETUP.md) 完成仅登录的阶段一，再完成只发给账号自身的阶段二。授权码只通过本机隐藏输入或 macOS Keychain 进入内存。
8. 回复只按本系统 RFC Message-ID 从已授权邮箱读取相关线程。拒绝或退订立即排除；有实质问题或兴趣时只生成待审后续稿，不对沉默对象自动追发。

## 资料与命令

- 数据表、状态和指标口径：[references/schema.md](references/schema.md)
- 网易 163、Gmail/企业邮箱接口与凭据边界：[references/adapters.md](references/adapters.md)
- 对外联系政策：[OUTREACH_POLICY.md](OUTREACH_POLICY.md)
- 初始化与首轮复现：[README.md](README.md)
- 回答批量拟稿、中英文、垂直媒体、GitHub 官方联系渠道或设置发送间隔时，读 [references/operating-capabilities.md](references/operating-capabilities.md)，明确区分 Agent 查证/写作与脚本自动化；不要宣称已有后台邮箱爬虫或独立语言检测器。

常用命令：

```bash
python3 scripts/outreach.py --db data/outreach.sqlite3 init
python3 scripts/outreach.py --db data/outreach.sqlite3 import-scout --scout-db /absolute/path/opportunities.sqlite3
python3 scripts/netease_cli.py --db data/outreach.sqlite3 probe
python3 scripts/netease_cli.py --db data/outreach.sqlite3 self-test
python3 -m unittest discover -s tests -v
```

`smtp_accepted` 只代表服务器接受提交，系统记录为 `delivery_unknown`，不算最终投递成功，也禁止盲目重试。模拟结果永远不计为发送、回复或转化；简单回复不等于转化，`trial_started` 必须有实际开始试用的证据。
