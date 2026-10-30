# Opportunity-first：发现与排序

> 这是保留的旧 60 天策略与接口说明。新一轮默认使用 [版本化 Repository Intelligence / Screening](SCREENING.md) 的 `profile/screen`，原 `collect/rank` 仍可复现历史结果。

这是现有 Pipeline 的前置排序步骤，不改变 OpportunitySpec、SQLite schema、贡献政策、去重、测试、产品能力门禁或发布授权。分数表示审查优先级，不是 PR 接受概率或真实用户数。

## 两阶段读取

1. 用元数据、README 相关类别、CONTRIBUTING/AGENTS/AI 政策、目标 Issue 和近期 PR 做快速核对。明确政策禁止、无适用类别、已有条目/修复或无法验证的候选先退出；有疑点保留 `needs_evidence`。要求预先许可而尚未取得的候选不能标记 policy pass。上游的项目 Stars 要求仍须核验。
2. 读取最近 60 天关闭 PR，按 updated 降序翻页到窗口外，分别按 merged_at 和 closed_at 计数；当前 open PR 单独完整分页。默认每个列表最多 3 页。样本触顶时 coverage=false，不把“未发现”记作零，也不能断言不活跃。必要时对高价值候选提高分页预算。
3. 默认分支提交读取 since/until 窗口，剔除机器人和 merge commit。先不取每个提交的文件列表；对政策合适的候选按需补代码活跃度，最多 100 个提交。资源列表以文档维护为主要活动，因此排序使用 human commits；代码活动另列。Skill 修复和产品集成只有代码统计完整时才能正式评分。
4. 使用下列分类型排名分配审查名额；建议总共 8 个（例如资源 4、原生修复 3、集成 1），总数上限 12。CLI 输出的是各类型候选队列，不是自动执行许可。资源 45 分钟、原生修复 90 分钟、集成 180 分钟为投入参考，超预算保存状态并重新评估范围，不能缩短必要测试来凑数。
5. 仅入选者进入完整 OpportunitySpec → handoff → gate → run/完整 dossier 和 Codex 审查 → commit → 具体审批 → authorize → publish → track。60 天初筛不能替代执行前全历史重复检测。已有 committed/historical/submitted 状态先读取并恢复或追踪，不重复执行。

工具仅使用已有 GitHub REST transport 和 SQLite cache；不更新 opportunity_specs、pipeline_state、pipeline_events 或旧 opportunities。API 访问错误直接失败，不生成零值；输出记录时间和覆盖范围。超过 7 天、未来时间或部分窗口不能获得正式分数。

## 评分（每类独立比较）

| 类型 | 匹配/缺陷测试 | 外部 PR 接受信号 | 活跃度 | Stars/Forks | 成本 |
| --- | ---: | ---: | ---: | ---: | ---: |
| resource_listing | 受众匹配 25 | 25 | 20 | 20 | 10 |
| native_skill_fix | 缺陷与测试可行性 35 | 25 | 20 | 10 | 10 |
| product_integration | 受众匹配 25 | 25 | 20 | 20 | 10 |

产品集成必须先通过现有 `opportunity.gate`，包括原技术适配 A≥8、capability_match≥3、已验证能力等；排序键为 `(现有 technical_fit 总分, 上表后置分数)`。缺失完整 Spec 或技术门禁失败时，不计算 Stars 分数。不同类型的总分不作为统一排行榜。

所有分量归一化为 0–1，再乘权重：

- **外部 PR**：排除 GitHub Bot、OWNER、MEMBER、COLLABORATOR。外部是 API author_association 的操作性定义，不证明每个账号身份或独立用户。设 M=60 天外部合并 PR，U=60 天外部关闭未合并 PR，B=当前全部待审 PR：`0.5*M/(M+U+2) + 0.3*min(M/10,1) + 0.2*(M+U)/(M+U+B+1)`。同时保存全部关闭未合并数；未合并关闭不一定代表质量拒绝，可能重复/撤回。无近期合并会降分，但不自动判定不活跃。
- **活跃度**：`0.5*min(C30/10,1) + 0.5*min(C60/20,1)`。资源取人工非 merge 提交数；原生修复/集成取代码提交数。代码是常见代码/脚本后缀或 `.github/workflows/` 文件变更，包含测试和 CI；并非语义代码量或生产活跃用户数。提交文件分页不全且未发现代码时保留 unknown；已发现代码即可确认该提交。
- **传播触达信号**：`0.75*min(log1p(stars)/log1p(10000),1) + 0.25*min(log1p(forks)/log1p(1000),1)`。对数压缩避免大型仓库压倒技术价值；10k/1k 是封顶尺度，不是最低门槛。零 Stars 可以入选。
- **成本**：`max(0, 1-预计分钟/该类型预算)`，必须给出大于零的估计及范围依据。它是人工预算，不把上一轮工具运行时间当端到端投入，也不改变测试超时。
- **受众匹配**（0–5）：0 无共同用户任务；1 只有泛 AI 关联；2 间接相关；3 有明确相关用户；4 类别和用户任务直接对应；5 README 类别及已验证能力均直接对应。category 快检失败仍先淘汰，不能靠其他分量补分。
- **缺陷/测试**（0–5）：0 无具体问题；1 推测；2 明确 Issue 但缺验证路径；3 可执行最小复现和测试计划；4 已复现且可以执行针对性回归；5 已复现、修复回归通过且范围符合维护者明确需求。初筛分数可随实际证据升级，不凭空赋 5。

人工评分必须附来源和理由。native_skill_fix 的目标用户是该上游 Skill 用户：相关性由类别/Issue/expected_user_value 核验，不要求与 LazyMind 营销相关。评分没有统一最低 Stars；例如 aloth 要求的是**被收录项目** 100 Stars，不是列表仓库自身 100 Stars。

## 调用与复现

沿用已有 GITHUB_TOKEN 环境注入；勿把凭据放在命令行或 JSON。

```bash
python3 lazymind-ecosystem-scout/scripts/ranking.py collect \
  --repo OWNER/REPO --data-dir pipeline/data --output /tmp/metrics.json
# 对已初筛通过的候选补代码变更；不足仍保持 unknown：
python3 lazymind-ecosystem-scout/scripts/ranking.py collect \
  --repo OWNER/REPO --data-dir pipeline/data --max-code-commits 100 --output /tmp/metrics.json

python3 lazymind-ecosystem-scout/scripts/ranking.py rank \
  --input legacy-ranking-input.json \
  --output /tmp/ranking-results.json --limit 8
```

旧接口输入包含 key、campaign_type、四项 quick_checks、metrics、ratings、rating_evidence；产品另须已有完整 spec。实际成本估计还应有 estimate_basis。历史快照超过 7 天会拒绝评分；重新验证要重新 collect，不能只改 checked_at。已有旧排名及本次新策略的差异见 [固定历史回放](campaigns/repository-intelligence-replay/README.md)。
