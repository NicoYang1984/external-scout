# Scout → 独立贡献执行阶段

已实现可执行入口：[Pipeline](../../pipeline/README.md)。新交接包使用 [OpportunitySpec JSON Schema](../../pipeline/schemas/opportunity.schema.json)，由 `registry.py handoff` 保存，`pipeline.py run/commit/authorize/publish/track/outreach` 分阶段执行并保留历史。下文保留旧交接约束；LazyMind 能力映射仅对产品集成路线必需，原生 Skill Bug 不要求匹配。默认发布授权从不由 Scout 或导入文件自动推导。

参考 [ASu-skills Contributor](https://github.com/Hisn00w/ASu-skills/blob/main/skills/contributor/SKILL.md)；2026-10-27 读取，文件 Git blob `932f5cd04763b306add9bb79f4f71fa8cd782a10`。只采用真实问题检查、最小 Diff、验证、PR、CI、review 的流程思想，不引入求职、简历和面试功能；不依赖安装 Contributor。

Scout 在此停止于只读发现和交接，不 fork、push、创建 PR、评论或发邮件。用户后续授权独立贡献阶段时，再按具体授权执行，不因 proposed_action 自动执行。

交接包包括：

- 仓库及默认分支/目标贡献分支、读取时间、commit、许可证、CONTRIBUTING、AGENTS/AI_POLICY 和适用限制。
- 原始 Issue 状态、创建/更新时间、assignees、评论中的认领。不能把空 assignees 当作无人认领。
- Issue timeline 中关联 PR、当前 open PR 全量标题、相关 closed PR/commit；有限搜索和不完整分页写明缺口。
- 可复现触发条件、上游当前代码证据、最小拟改文件、验证命令。必须先确认尚未修复、无相同方案的在途 PR。
- LazyMind 能力映射、两轴分数及证据；upstream_only 可以形成独立贡献线索，但不是 LazyMind 产品机会。
- proposed_action、validation_status、public_contribution_url、review_status、outreach_channel、outreach_permission、reply_status、trial_status、conversion_evidence、next_follow_up。

后续阶段的工作顺序：核对贡献规则和前置维护者许可 → 专用分支上的最小 Diff → 按项目配置本地验证 → 展示目标仓库、Diff、PR 标题正文 → 在具体授权范围内发布 → 分别跟踪 CI、review、merge。若仓库要求先开 Issue/claim，未满足时不准备代码补丁。

CI 的 success、pending、action_required、failure 分开记录；本地通过不能代替远端 CI。PR URL 只证明存在，合并要记录真实 merged_at 和查询来源。评论发布、维护者回复、试用开始、试用完成、转化各自独立；转化需有约定定义与直接结果证据。

本次真实扫描的规则示例：TheStreamCode 非文档代码改动要求先开 Issue；alirezarezvani 要求目标分支 dev，禁止 README 第三方推广链接。它们是具体仓库当时的规则，不泛化为所有项目政策。
