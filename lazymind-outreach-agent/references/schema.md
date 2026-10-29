# Outreach SQLite schema

核心实体：

- `organizations`：组织级去重键。
- `leads` / `lead_versions`：候选当前视图与完整版本。
- `scout_records`：Scout 来源 ID、当前 payload、历史和源库哈希。
- `drafts` / `draft_versions`：正文版本及 SHA-256。
- `batches` / `batch_items` / `approvals`：小批次审核与发件账号、收件人、主题、正文的精确指纹绑定。
- `suppressions`：组织或联系人排除，不因换渠道失效。
- `send_requests` / `send_attempts`：幂等请求和每次实际尝试，区分 `simulated` 与 `real`。
- `sender_accounts` / `provider_checks`：非秘密账号配置和分阶段验证记录；不含授权码。
- `send_pacing`：账号级最小发送间隔、上次占位与下次允许时间；仅影响真实批次发送，默认 300 秒。在同一 SQLite 事务内与发送请求一起占位，跨批次/重启保留；没有触碰 Scout schema。
- `replies`：授权邮箱内相关回复及分类。
- `events`：状态证据和人工时间，用于成本指标。

状态：`discovered`, `qualified`, `drafted`, `review_pending`, `approved`, `queued`, `smtp_accepted`, `delivery_unknown`, `failed`, `sent`, `replied`, `interested`, `trial_started`, `declined`, `suppressed`, `stale_channel`。

联系许可：`explicit_opt_in`, `official_submission_channel`, `official_collaboration_channel`, `prior_correspondence` 可以进入审核；`unknown`, `not_granted`, `requires_membership`, `stale_channel`, `revoked` 不能发送。许可只是必要条件，仍需通过用途、重复、语言、排除、发件账号和审批检查。

Outreach 不把 Scout 的分数重算成许可。Scout `technical_fit`、`ecosystem_value`、`capability_evidence`、来源 URL 和历史以来源 payload 保留；联系人补充信息只写 Outreach。
