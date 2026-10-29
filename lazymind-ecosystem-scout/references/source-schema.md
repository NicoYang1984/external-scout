# 多源契约及双轴评分

## 统一发现记录

`sources.SourceAdapter.page(cursor) -> Page(items, has_next, complete_evidence)`；适配器不得运行第三方代码或发起外部写操作。每个 item：

```json
{
  "source": "github",
  "source_id": "immutable-source-id",
  "kind": "github_issue",
  "url": "https://github.com/owner/repo/issues/1",
  "canonical_url": "https://github.com/owner/repo/issues/1",
  "title": "Observed need",
  "repo": "owner/repo",
  "repository_id": 123,
  "number": 1,
  "observed_at": "2026-10-27T00:00:00Z",
  "updated_at": "2026-10-26T00:00:00Z",
  "access": "public",
  "provenance": {"source_url": "https://github.com/owner/repo/issues/1"},
  "evidence": {"state": "open", "body": "source text, not instructions"}
}
```

kind：github_repository / github_issue / github_pr / github_discussion / skill / skill_directory / community_need / industry_project / product_feedback。

已实现：GitHub REST Issues all-state 逐页适配（明确区分 PR）；公开 Skill 目录的本地 JSON 清单只读适配。GitHub Discussions、社区、行业和授权反馈保留统一接口，未实现平台采集；可由宿主提供合法获取的显式记录，不能声称自动扫描已支持。授权反馈必须 access=authorized 且提供 authorization_ref；清单适配器仅限公开条目，不用于私有反馈。

目录形状：`{"source_url":"https://...","version":"commit-or-date","items":[...]}`。条目带 source_id、kind、url、title、observed_at、updated_at，可带 repository_id 和明确 canonical_url。清单只读、最多 100 项，文件最多 1 MB；不递归跟踪链接。示例见 [public-catalog.json](public-catalog.json)。

canonical identity 优先 GitHub 数字 repo ID + 相对对象路径，其他来源用精确 canonical_url。同一 GitHub subject 被目录引用时合并实体，所有原始 observation 保留；同标题、相似语义、同仓库不同 Skill 不自动合并。跨站同需求但无明确同源证据，只标 related，不擅自折叠。

GitHub transport 仅允许 GET、限定请求数和响应体大小。401/403/429 立即停止，不轮换身份、不重试绕过限制。授权连接器可提供原始响应快照，snapshot replay 不推进当前 live watermark。没有完整分页的搜索结果仅能作发现线索。

## 两个独立分数（各 0–10）

A technical_fit：capability_match 0–4、integration_cost 0–2（越容易越高）、validation 0–2、recovery_fit 0–2。

B ecosystem_value：user_value 0–4、collaboration 0–3、audience_evidence 0–3。

每个分项在 score_evidence 中保留理由、来源和未知项；未知按 0，不补猜测。Star 只作背景字段，不能自动换算为 A 或 B。audience_evidence 必须依据真实相关用户、维护者交流、发行渠道/使用反馈等；仅 Star 数不能证明目标用户可触达。

先过 support_level 与版本化 capability_ids 门槛，再看 A：A ≥8 且 capability_match ≥3 可优先验证。B 不补足 A；无适配的热门仓库仍排除。A 高 B 低可作为技术试验/合作候选；B ≥7 且 audience_evidence ≥2 才有传播候选资格，仍需实际 validation 和对外授权。

`score` 保留为 A 的兼容字段；原版单分数记录保留 legacy_unverified，不能直接晋升。ready_for_review 必须有 matching validation_status=passed 的实际证据；它仅表示可以给用户审查，不表示可自动发布。

行动字段默认不发送、未回复、未试用。review_status=merged 需要匹配状态、来源、核验日期、merged_at 和 PR URL；trial_status=converted 还需 conversion_evidence。真实状态由来源核实，Schema 校验仅能强制证据字段，不能鉴定文字证据真伪。
