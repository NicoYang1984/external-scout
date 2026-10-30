# Repository Intelligence 与 Campaign Ranking V1

本层负责候选画像、证据准入和审查优先级。没有执行 Agent、目标代码运行、Git push、PR/评论/邮件发送或定时入口。运行依赖只有 Python 3.9+ 标准库。旧 `ranking.py collect/rank` 保留用于原始 60 天报告复现；新流程使用同一入口的 `profile/screen`。

## 架构审计与扩展位置

已有可执行机制：`scan.py` / `sources.py` 有界只读采集，`state.py` 负责仓库数字 ID、别名、租约、观察历史、待办和扫描游标；`policy.py` 保留 A/B 产品能力门禁；OpportunitySpec 和 Contributor 已有完整去重、验证、精确 Commit 授权、发布与真实 PR 跟踪。

此前待人工解释的部分：受众和贡献政策的结论、Bot/实质活动区分、样本不足如何处理、优先级公式、缓存寿命和报告口径。已有未提交 `ranking.py` 提供固定权重、60 天聚合和临时 JSON，不能当作新增 90/180 天画像，也未维护版本化评分历史。

本次增量：

- `repository_intelligence.py`：证据 envelope、有界画像采集和现有 source observation 持久化。
- `screening.py`：版本化配置校验、硬 Gate、确定性分量、Top N、中文/JSON 报告及本地 Spec 导出。
- `ranking.py`：只增加 `profile/screen` 分发，旧接口和历史资料保留。
- `policy.assess` 与 `opportunity.gate` 增加可选固定时间/能力事实参数，供离线复现；默认生产调用仍读取当前事实库，门槛不变。产品筛选输入必须含固定 `capability_facts`；Contributor 发布不使用筛选分数或该快照授权。

不新增数据库表或第二套仓库身份。画像和评分分别以 `repository_intelligence` / `repository_screening` source 追加到 `source_observations`；`source_items` 只是仓库实体的最新观察视图。历史查询按 source 过滤，不依赖最新视图一定是画像。完整原始采集快照随画像保留（仓库元数据采用白名单，不保留临时 clone token）。不改 opportunities、Spec、Pipeline 状态、审批、Issue 游标或 PR873 材料。旧 V1 库继续先用原 `migrate.py` 复制迁移。

## 0–6 阶段

0. Discovery：现有 GitHub/Catalog/显式候选清单。此层不另建搜索爬虫。
1. Pre-screen：读取元数据和默认分支；Archived/Disabled 立即停止。没有统一最低 Stars。
2. Policy：有界读取 README、CONTRIBUTING、AGENTS、AI 政策、PR 模板、Actions/自动关闭配置。只采集原文，不用关键词宣告“允许贡献”。需要人工或 Agent 审阅后提交绑定 revision 的结构化事实。明确禁止即停止；政策未知时不抓深层 PR/Commit 样本。
3. Deep verification：按批次预算读取活动样本；具体 Issue、重复、当前复现、环境、能力证据继续由现有 Scout/Contributor 验证。历史 pending/partial/未完成执行先排队，其次政策已具备的候选。默认最多 5 仓库、前 2 个深查名额；不足的留待下一批，不假装完成。
4. Ranking：硬门槛全过才计算总分。仅统计性非核心数据缺失时，可 GO 并输出区间；政策、重复、认领、复现、环境、完整 Spec 等未知则 HOLD，无总分。
5. Handoff：只导出输入中已通过的完整 Spec，保持 normalize 的原稳定 ID；不根据排名生成“已通过”证据，不自动导入/改写执行状态。
6. Contributor：原 gate → run → commit → 具体授权 → publish → track。当前任务仅授权本地工作，不能调用发布动作。

已提交、历史 PR 均只跟踪，独立于是否具备高排名。HOLD 是筛选层状态；原 OpportunitySpec 不增加枚举，现有 gate 仍保持 GO/NO-GO。缺失证据保留 verification_pending，明确阻断用 blocked；排名不会改变这些值。

## 配置、权重和阈值

稳定配置路径：`lazymind-ecosystem-scout/references/screening-policy.json`，版本 `repository-screening/v1`。这是初始工程策略，未经统计优化。

| 维度 | resource_listing | native_skill_fix | product_integration |
|---|---:|---:|---:|
| audience_fit |20|5|20|
| reach_potential |20|10|10|
| maintainer_activity |15|15|10|
| external_pr_friendliness |20|20|15|
| technical_value |0|30|15|
| execution_feasibility |15|20|20|
| direct_exposure_path |10|0|10|

各维度 0–5，总分 `sum(weight × dimension / 5)`，上限 100。没有通用最低 Stars 或“达到某分自动发布”的阈值。

- **触达潜力**：90% Stars、10% Forks 的 `log1p` 封顶归一化，默认封顶尺度 10,000/1,000。Forks 仅辅助；不是曝光、用户人数或转化。
- **维护活动**：60% 来自 30/90 天实质人工提交（封顶 10/20），25% 近期维护者响应、15% 近期 Release。pushed_at 不计分。仅 GitHub User 作者及提交者且具有可读非生成代码/文档 patch 的变更可计入；Bot、链接/UTM/badge 行、lock/changelog/generated 等不作为正面实质证据。此为保守、可解释代理指标，不是语义代码质量判定；无法识别身份/文件分页/patch 时给 unknown 和观测下界。GitHub User 不能证明现实身份，confidence 为 medium。
- **外部 PR 友好度**：50% 来自 180 天创建 cohort 的观测 merged 占比、30% 同样本外部 PR 的维护者回复、20% 当前 PR 中非长期积压比例（90 天）。Bot/OWNER/MEMBER/COLLABORATOR 不算外部；只有可识别 User 和明确外部 association 才入样本。分页完整、身份可辨且 n≥10 才给观测比例；其余给 unknown。关闭未合并不等于质量拒绝，比例不代表未来接受概率。
- **受众/技术/曝光路径**：按配置中的命名事实类别映射 0–5，禁止输入自由分数。类别仍须人工提供可核验来源、时间及理由；代码不能证明文字真实。native 技术价值与个人工程贡献独立于 LazyMind 提及。
- **实施可行性**：环境已验证时 `5 × max(0,1−预计分钟/预算)`；参考预算分别 45/90/180 分钟。预估不是实测耗时，不能缩短必要测试。缺环境 HOLD。
- **不确定性**：已知部分相加作为下界，未知部分按配置最大权重给上界。只在所有非零权重维度完整时输出精确总分；Top N 按保守下界降序，同分按稳定 key 排序，并分 Campaign 展示。

默认 24 小时画像缓存、7 天核心审阅证据、每类 Top 3；每列表最多 2 页 × 100 项、最多 20 个提交文件详情、20 份政策/工作流文件、每类响应 1 页；每仓库最多 60 请求，每批最多 200。所有参数在配置中。缓存复用前用条件 GET 核对当前 metadata 和 HEAD；数据变化、审阅变化或策略 hash 变化均失效。限流、访问失败、预算不足不会成为零结果；新一轮重枚举有界页，复用 transport ETag，不从漂移 offset 假续读。

同一策略版本不得对应不同配置 hash；升级配置需改 policy_version。旧画像、评分和审批保留。重评分是新的观察记录，不覆盖原结果。

## 输入与本地命令

在根目录使用。令牌由调用方放入环境变量，程序不访问钥匙串、不打印凭据。命令只做 GET 或本地写入。

```bash
# 先建候选清单，不需要凭空填分数。
# [{"key":"owner/repo:resource_listing","repo":"owner/repo",
#   "campaign_type":"resource_listing"}]
python3 lazymind-ecosystem-scout/scripts/ranking.py profile \
  --input candidates.json --data-dir pipeline/data \
  --run-id research-001 --output pipeline/data/research-001/profiles.json
```

首次通常停在政策待审。`profiles.json` 的 candidates 元素保留 repo/campaign，加 profile 和完整 documents/raw_snapshot。阅读材料后加入 `review`（不应只刷新时间）：

```json
{
  "revision": "与画像一致的40位Commit",
  "facts": {
    "accepts_external_pr": {
      "value": null,
      "source_url": "https://github.com/owner/repo/blob/COMMIT/CONTRIBUTING.md",
      "observed_at": "2026-10-30T12:00:00Z",
      "unknown_reason": "尚未审阅；不得复制为通过项"
    }
  }
}
```

事实 envelope 使用 value、source_url、observed_at，以及 confidence=high/medium 或 unknown_reason；建议 finding 写清原文与判断。必须核查的布尔事实：accepts_external_pr、ai_allowed、prerequisites_met、no_duplicate、not_already_fixed、scope_fit、environment_ready、maintainer_claimed、permission_required、auto_close_external；认领/前置许可需 permission_granted，自动关闭需有效 auto_close_exception。原生还需 real_defect/regression_test，产品需 requires_new_core=false 与 capability_facts。所有审阅绑定 profile.revision。缺项 HOLD。

政策文档分页或树覆盖不足时，不能仅填几个 pass 就通过。必须补齐采集，或提供独立完整审阅的 `policy_coverage_complete=true` 证据。旧仓库名的历史快照不会触发反向改名；真实改名继续由已有 `repo-identify` 核实数字 ID 后处理。

评分事实：audience_fit、technical_value、direct_exposure_path 使用配置 rubric 的命名类别；estimated_minutes 必须正数并说明依据。可附 target_users、distribution_entry、actions_restrictions、user_feedback。完整 spec 仍按原 Schema 生成，不把手工评分当作测试执行证据。

继续 `profile` 时传入包含 review 的候选文件，补采 30/90/180 天统计。具体机会证据齐全后附上原 spec，再执行：

```bash
python3 lazymind-ecosystem-scout/scripts/ranking.py screen \
  --input reviewed-candidates.json --data-dir pipeline/data \
  --run-id research-001 --output pipeline/data/research-001/report.json \
  --handoff-dir pipeline/data/research-001/handoffs
```

同时生成 `report.md`。只导出 GO 的原 Spec，不改稳定 ID、验证等级或审批。导出后仍需原 `registry.py handoff` / `pipeline.py import` 检查现有进度；已 committed 的应恢复审核，不重做实现。

历史离线回放不发请求：

```bash
python3 lazymind-ecosystem-scout/scripts/ranking.py screen \
  --input pipeline/campaigns/repository-intelligence-replay/input.json \
  --data-dir /tmp/external-scout-screening-replay \
  --run-id replay-001 --at 2026-10-30T12:00:00+00:00 \
  --output /tmp/external-scout-screening-replay/report.json
```

`--at` 仅适用于 screen，禁止回填在线采集时间。固定输入、固定策略（含产品能力快照）、固定评估时刻生成固定评分；真实数据库中的已有 PR/执行状态另作为额外输入读取，优先防重复。复现整份报告请使用同一数据库快照或新的隔离库。

## 报告和历史回放

JSON 含所有字段来源/时间/可信度、policy version/hash/snapshot、画像 hash、gate reasons、breakdown、分数区间、实际进度和证据链接。Markdown 展示主要指标和每机会细节。两条价值分轨为 Personal Engineering Contribution / LazyMind Marketing Value；无 LazyMind 关系的修复不会被标成曝光。

Funnel：discovered → prescreened → deeply_verified → GO → submitted → merged → observed_engagement。screen 不会提交或联系他人，所以本轮新增后三项为 0；已有 PR、历史贡献、已有 merged 分开计数。PR 状态只引用已持久化 GitHub REST 观察，不将旧合并算作本次成果。

[历史回放](campaigns/repository-intelligence-replay/README.md)：30 个旧候选重判为 12 NO-GO / 18 HOLD / 0 GO。这是证据要求差异，不是新扫描结果或撤销此前验证。旧 60 天排名仍保留，不能重标成新窗口；需要补证据才能按新权重比较。
