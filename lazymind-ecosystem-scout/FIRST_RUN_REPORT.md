# FIRST_RUN_REPORT

时间：2026-10-27（Asia/Shanghai）。结论：完成三个指定仓库的真实、有界只读取证，保留 3 条候选评估，**本轮可优先深入/推广机会为 0**。没有运行这些仓库的代码，没有安装它们的 Skill，没有外部评论、邮件或 PR。

## 取证与执行方式

本机匿名 GitHub REST 首次联网检查返回 403 rate limit exceeded，随后停止该路径。通过现有授权 GitHub 连接器 GET 读取仓库元数据、README、根目录、贡献规则、Issue/PR 页面和必要关联关系；不轮换身份重试限流请求。连接器本身的限额仍适用。

原始响应保存在交付工作区 evidence/，随后由实际 GitHubAdapter + SnapshotTransport 进入隔离 SQLite。此过程测试了真实响应的解析、分型、持久化与待办；不是直接 Python HTTP transport 的完整联网测试。快照不推进 live 水位。

| 仓库 | 当时 Star | 已取的 all-state 首页 | 补充检查 | 本轮覆盖边界 |
|---|---:|---:|---|---|
| [TheStreamCode/agentic-rd-skill](https://github.com/TheStreamCode/agentic-rd-skill) | 1 | 14 条，均为 PR | README、CONTRIBUTING、AGENTS、当前 main commit | 页长不足 100；无真实 Issue，但没有扫描 Discussions |
| [sensein/agent_skills](https://github.com/sensein/agent_skills) | 1 | 51 条：2 Issue、49 PR | #35 评论/timeline、全部返回的 6 条 open PR、README、根目录 | 页长不足 100；#9 已关闭，#35 已有对应 open PR |
| [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills) | 28,795 | 100 条：49 Issue、51 PR | 近期开放项另取 2 条（Issue #1051、PR #999），贡献规则、README、根目录 | 历史列表未完整分页，不能声称穷尽；所有扫描水位保持 0 |

观测到的 main commits：

- TheStreamCode：`c8b5f521572a3036149a9cdb491d25c1d0cd9fc3`
- sensein：`1dafcb10cb0e44930d35a6ab8c8534320e65514f`
- alirezarezvani：`5434623a788ec3105d238328cfe554e1e2242ff7`

另通过新 CatalogAdapter 导入 3 条显式整理的公开 Skill 目录记录；这是只读目录清单来源，不是声称已经实现 skills.sh 或其他网站在线爬虫。

最终隔离库：170 个主题实体、172 条来源观察（含两条补充项的再次记录）、3 条机会、3 条机会历史、2 条 Issue 处理结论。sensein 两条 Issue 已有明确分流结论而退出 pending；大仓库仍有 50 个未深入处理的 Issue pending。快照期间所有 live cursor 均未推进。

## 双轴评估

分数用于当前证据范围下的判断，不是产品性能测量；未知项不补猜测。A 门槛为 ≥8 且 capability_match≥3，并须先满足能力准入。

| 候选 | A 技术适配 | B 生态/用户价值 | 状态 | 具体结论 |
|---|---:|---:|---|---|
| agentic-rd-skill | 6/10 | 4/10 | verification_pending | 技术合作假设可保留，但没有证明对方缺运行层，也无目标受众传播证据 |
| sensein/agent_skills | 4/10 | 4/10 | verification_pending | 限定目录安装/preflight 可做后续验证；专业研究业务 E2E 未验证，现有 #35 不能重复贡献 |
| claude-skills | 3/10 | 4/10 | rejected（当前自动业务交付/推广方案） | 大 Star 无法补足现成能力缺口；README 推广链接还被明确禁止 |

### TheStreamCode：不要把已有能力写成缺口

[README](https://github.com/TheStreamCode/agentic-rd-skill/blob/c8b5f521572a3036149a9cdb491d25c1d0cd9fc3/README.md) 已描述八阶段流程、独立 Artifact、确定性 CLI、状态校验和人工审阅记录。不能仅因它是小型 Skill 就说缺少 workflow、gate 或可追溯性。

窄候选只映射 LazyMind `workflow_observation`：若对方确认需要可视化观测，可设计现有 session projection/steps/artifacts 的薄适配验证。尚未证明新增价值；A=2+2+1+1，B=2+2+0。1 Star 不排除合作，也不支持“最佳宣传渠道”。非文档代码改动须先按其 CONTRIBUTING 开 Issue 讨论；本次未执行。

### sensein：已有明确在途方案

[#35](https://github.com/sensein/agent_skills/issues/35) 的评论明确指向 [PR #36](https://github.com/sensein/agent_skills/pull/36)。当时 PR 仍 open，不能写成已合并，也不能把该 Issue 当成待抢占的无人处理问题。

仓库级线索只映射 `skill_directory_install` / `conversion_preflight`：可在后续授权试验中检查一个固定 Skill 的安装和依赖完整性。A=2+1+1+0，B=3+1+0。没有证明 LazyMind 已能完成 SynthScholar、MeSH 检索或学术审查；不访问机构登录或非公开论文资料。

### claude-skills：曝光不抵消门槛

[贡献规则](https://github.com/alirezarezvani/claude-skills/blob/5434623a788ec3105d238328cfe554e1e2242ff7/CONTRIBUTING.md) 要求 PR 目标为 dev，明确拒绝 README 第三方 repo/tool 推广链接。原文中的历史 Skill/Star 数与当前 README/元数据不同，因此不拿旧宣传数字作为本轮指标。

本轮评估的“将 Skill 自动转为业务交付并据此推广”依赖 `skill_autonomous_delivery`，当前事实库存在已记录失败，support_level=needs_product_work，因此 rejected。A=1+1+1+0，B=3+0+1；audience 仅承认公开目录覆盖，不从 Star 推导可触达用户。仓库本身并未被永久淘汰，未来可重新评估具体窄问题。

[#1051](https://github.com/alirezarezvani/claude-skills/issues/1051) 是依赖文件/命名一致性的上游线索；本轮未完成源码复现和撞车审查，保持待办，不冒充 LazyMind 的现成业务机会。

## 行动状态与下一步

三条候选均保存十项行动字段：validation_status=planned；无 public_contribution_url；review_status=not_requested；outreach_permission=not_granted；reply_status=not_contacted；trial_status=not_started；conversion_evidence 为空；next_follow_up=null。没有把本地保存建议当作对外行动，也没有自动安排跟进。

建议下一阶段先选一个明确缺口，冻结输入、产品部署版本和验收标准，做单一兼容性/观测试验；同时核实相对原生流程的新增价值。确认可运行并符合维护者规则后，才进入独立贡献执行。PR873 的失败不能用“转换成功”掩盖，也不能泛化成所有产品路径失败。

结构化结果见 [validation/first-run-summary.json](validation/first-run-summary.json)。
