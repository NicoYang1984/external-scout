# FIRST RUN REPORT

运行日期：2026-10-28（Asia/Shanghai）  
模式：只读发现、草稿、测试和记录；无真实发送、无模拟发送、无外部写入。

## 结果摘要

- 候选共 19 个：Scout V2 只读导入 8 个，官方公开来源补充 11 个，没有超过 20。
- 形成 3 封真正差异化的待审草稿：OpenEng Labs、Composio、Opensource.com。
- 另有 2 个用途明确但本轮不应起草：IEEE Spectrum 缺少作者身份/作品链接且要求人工创作；AAIF 只开放项目提案表单且需要更强的采用、治理和路线图证据。
- 少数派和 InfoQ 按用户说明登记为历史已联系，状态为 `sent`，没有新草稿，也没有进入批次。
- `business_trial` 为 0：没有找到主动申请、明确 opt-in 或既有授权试用联系人，因此没有用公开名单补齐。
- 首轮批次 ID 为 `3c853713-3fa4-4f62-96cf-0095dcd2b5a8`。3 封草稿均为 `review_pending`；发件账号是 `UNCONFIGURED`，所以审批检查全部明确阻止。

## Scout V2 只读复用

来源数据库：`../first-run/isolated-data/opportunities.sqlite3`，`PRAGMA user_version=2`。

- 导入前 SHA-256：`81cf0053df14cb1e182adbd322c2ea4a8b9285b50f8b24a432eda4e406b49d3b`
- 导入后 SHA-256：`81cf0053df14cb1e182adbd322c2ea4a8b9285b50f8b24a432eda4e406b49d3b`
- 结果：字节级不变。

8 个机会保留了 Scout 来源 ID、当前 payload、history、技术适配度、生态价值、能力证据和来源链接。Outreach 没有继承其发送资格；所有 Scout 线索导入后仍是 `not_granted`，因此不会进入发件队列。

## 待审对象

### OpenEng Labs — developer_collaboration

官方联系页明确将 `hello@openeng.ai` 用于 agentic systems 和 governed execution 的 research collaboration，并要求首封说明当前栈、可量化目标、数据约束和目标时间。[官方依据](https://openeng.ai/contact)

草稿提出固定公开输入、失败注入、状态一致性和限定重试的兼容性研究；明确没有进行过 OpenEng 兼容测试，也不暗示对方认可。

### Composio — developer_collaboration

官方合作页明确邀请 AI framework、agent platform 和 developer platform 讨论合作，并发布 `partnerships@composio.dev`；兼容页公开 remote MCP 与 Codex 支持。[合作依据](https://composio.dev/partnerships) · [兼容性依据](https://composio.dev/works-with)

草稿只提出“同一 Codex 宿主中的边界测试”，不声称 LazyMind 已直接集成 Composio；通过后，案例和联合传播仍需双方另行审核。

### Opensource.com — editorial_pitch

官方编辑页邀请通过 `open@opensource.com` 提交文章想法，主题包括 automation、machine learning / AI、programming 和 tools。[官方依据](https://opensource.com/resources/editorial-calendar)

草稿以“失败的 Agent Workflow 如何暴露状态观测与恢复边界”为非广告式选题，附开源仓库和真实负面结果。风险是页面仍保留 2021 footer；在任何审批前必须重新确认邮箱仍活跃。

## 未进入草稿批次

- IEEE Spectrum：官方页面允许工程技术 pitch，但首次作者需作品链接，并强调人类研究与创作；当前没有足够身份材料，故不自动起草。[规则](https://spectrum.ieee.org/guidelines-freelancers)
- AAIF：官方项目提案入口与 LazyMind 的 observability/governance 方向高度相关，但需采用、社区健康、开放治理和 6–12 月路线图；本轮只保留资格线索。[规则](https://aaif.io/submit-a-project)
- TechRadar Pro Perspectives：明确禁止 AI 起草并要求非宣传内容，已排除本 Skill 自动起草。[规则](https://www.techradar.com/pro/perspectives-how-to-submit)
- DZone：禁止 AI-generated 和主要宣传内容，且个人账号不能代表组织，已排除。[规则](https://dzone.com/writers-zone)
- IAPP：AI 生成内容需事先书面许可且文章不得宣传，当前无许可，已排除。[规则](https://iapp.org/news/write-for-us)
- The New Stack：当前没有核实到一般开放的 contributor channel，保留发现状态。
- Scout 中 Anthropic knowledge-work-plugins 等机会：技术上有价值，但 Scout 明确记录 `not_granted` 或上游政策不允许当前行动，没有外联。

## 指标

| 指标 | 首轮结果 |
|---|---:|
| 发现候选 | 19 |
| 具有用途依据的联系渠道 | 7 |
| 待审个性化草稿 | 3 |
| 审核通过草稿 | 0 |
| 真实发送成功 | 0 |
| 有效回复 | 0 |
| 明确合作/试用意向 | 0 |
| 实际开始试用 | 0 |
| 平均人工审核时间 | 尚无审核事件，0 |
| 单个有效线索人工时间 | 尚无有效线索，N/A |

这里的 7 个渠道包括历史往来、表单和当前不具备完整内容材料的投稿入口，不等于 7 个可立即发送对象。`sent` 的两条历史记录也不计入本系统的真实发送成功，因为缺少本系统 provider Message ID。

## 产物与下一门禁

完整线索见 `LEADS.csv`，草稿见 `DRAFTS.md`，状态见 `OUTREACH_TRACKER.csv`，机器可读审核清单见 `review-checklist.json`。下一步只有在配置并核验授权发件账号、补齐真实发件人身份、重新核验页面/邮箱、用户批准整个小批次后，才能进行模拟发送；V1 仍会拒绝真实发送。

