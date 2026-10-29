# ARCHITECTURE

## 数据流与信任边界

```text
Scout V2 SQLite (read-only)       官方投稿/合作页       授权试用/既有往来
          │                              │                    │
          └──────────── evidence-backed lead ────────────────┘
                                 │
                        independent Outreach DB
                                 │
          qualify → draft/version → batch/review → approval(exact fingerprint)
                                 │
                mock adapter / gated NetEase 163 adapter
                                 │
          authorized mailbox replies → classify → draft follow-up
                                 │
                    metrics / explicit Scout outcome file
```

Scout 是技术机会事实源，不是联系许可源。`scout_adapter.py` 只读打开数据库，要求 V2 表，保留来源 ID、当前 payload、历史 payload 和源库 SHA-256；导入线索一律为 `not_granted`。`export_outcomes()` 只写 JSON 交接文件，不打开 Scout 写连接。

## 模块

- `scripts/outreach_core.py`：SQLite schema、版本历史、组织/联系人去重、精确审批指纹、排除、受控发送状态、回复状态和指标。
- `scripts/scout_adapter.py`：Scout V2 只读导入与显式 outcome 导出。
- `scripts/adapters.py`：邮件接口、确定性 Mock、禁用状态的 Gmail OAuth Adapter、企业邮箱抽象接口。
- `scripts/netease163.py`：个人 `@163.com` 的 SMTP SSL/IMAP SSL 实现、Keychain 凭据读取、回复关联与投递不确定性分类。IMAP 登录后使用 RFC 2971 ID 声明真实客户端身份；probe 包含只读 INBOX 检查；Sent 保留服务器声明的 modified-UTF-7 名称与引号。
- 账号级 `send_pacing` 在 Outreach 库持久化冷却，默认 300 秒；请求与冷却同事务占位、网络调用在事务外。真实执行逐封重新取审批/状态，底层返回待发送而非长时间阻塞；CLI 可显式选择本机分段等待模式。模拟不使用真实冷却。
- `scripts/netease_cli.py`：阶段一登录验证和阶段二账号所有者自发自收测试。
- `scripts/macos_keychain.py`：原生 SecItem 读写，区分条目缺失与访问失败；保存后必须读回一致。
- `scripts/provider_report.py`：由非秘密验证记录生成 provider / readiness 报告。
- `scripts/outreach.py`：日常 CLI。
- `scripts/first_run.py`：首轮可复现导入和交付物渲染。

## 审批与幂等

批次最多 10 封，同一组织或同一联系人不能在一个批次出现两次。审核清单包含完整正文、允许用途、证据、发件账号、SHA-256、风险和去重检查。审批存储 `sender + recipient + subject + body` 的 SHA-256 指纹；任一字段变化都会使旧审批失配，正文新版本还会显式撤销旧审批。

幂等键为 `batch_id + draft_id + approval_fingerprint + mode` 的 SHA-256。明确失败且安全重试时才允许恢复；`smtp_accepted` 或连接在 DATA 提交阶段中断都进入 `delivery_unknown`，相同请求只返回原记录，禁止盲目重试。模拟适配器产生 `sim-*` 标识，但不写 `last_contact_at`，也不把线索改成 `sent`。

## 回复与状态

主流程为 `discovered → qualified → drafted/review_pending → approved → queued → smtp_accepted/delivery_unknown → replied/interested → trial_started`，并可进入 `failed`, `stale_channel`, `declined`, `suppressed`。只有独立投递证据才可从不确定状态推进；拒绝和退订以组织与联系人双重排除。

## 凭据与网络

个人 163 使用客户端授权码，不使用网页登录密码；授权码只从隐藏终端输入或 macOS Keychain 读入内存。数据库只保存非秘密的账号、provider 和验证状态。非精确 `@163.com` 域名会在连接前停止，企业邮箱必须单独核验主机和策略。Gmail 仍计划使用最小 OAuth scopes；企业邮箱实现同一 `MailAdapter`，两者当前均保持关闭。

`repair` 路径跳过旧 Keychain 值，直接隐藏输入当前授权码。阶段一验证成功后才覆盖保存，并在内存中比对读回值；阶段二复用同一 Adapter，不重新读取另一个凭据来源。自测提交前持久化 Message-ID，SMTP 接受后立即记录，后续重跑仅查询记录。
