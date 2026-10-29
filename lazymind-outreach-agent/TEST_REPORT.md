# TEST REPORT

测试日期：2026-10-28  
运行时：Python 3.9.6，标准库实现。

## 自动测试

命令：

```bash
python3 -m unittest discover -s tests -v
PYTHONPYCACHEPREFIX=/tmp/lazymind-outreach-pyc python3 -m compileall -q scripts tests
```

V1 原有结果：9/9 通过。V1.1 增量测试：9/9 通过。凭据与自测回归：8/8 通过。IMAP 兼容性回归：6/6 通过。发送节奏与语言门禁：13/13 通过。总计 45/45，源码编译检查通过。

| 测试 | 结果 | 验证内容 |
|---|---|---|
| duplicate email/project | PASS | 邮箱规范化后唯一；重复联系人不能建第二条同 Campaign 线索 |
| same organization, multiple channels | PASS | 同组织不同渠道不能在同批次重复触达 |
| nationality inference | PASS | 敏感推测字段被拒绝，schema 也没有国籍/族裔字段 |
| missing permission | PASS | `not_granted` 无法审批 |
| approval invalidation | PASS | 主题/正文变化产生新 SHA-256 并撤销旧审批 |
| failure recovery/idempotency | PASS | 首次 provider 失败可恢复；成功后重复调用不重复尝试 |
| decline suppression | PASS | 拒绝立即写入组织/联系人排除并进入 `suppressed` |
| simulated vs real | PASS | 模拟不推进 `sent`/`last_contact_at`；非 163 或未通过门禁的 real 入口硬拒绝 |
| Scout immutability | PASS | V2 fixture 以只读方式导入，前后文件 SHA-256 相同，许可不提升 |

V1.1 增量覆盖：企业邮箱不会误套个人配置、阶段一只登录不发送且端口正确、中文主题/正文/链接与 UTF-8 MIME、相关回复 Message-ID 与发件人关联、收件人变化使旧审批失效、`delivery_unknown` 不盲重试、进程在 queued 后中断时转人工核验、Keychain 写入不把密钥放入进程参数、授权码不进入 SQLite。

## 535 / Keychain 修复验证

- 新增失败测试先复现了“写入返回成功但读回不一致仍报成功”和“535 未标明认证阶段”两项缺陷，修复后通过。
- 完整两阶段回归验证：只读取一次新授权码、两个阶段复用同一 Adapter、保存失败可保留内存自测、报告和 SQLite 均不包含凭据。
- SMTP 接受后 IMAP 出错的回归验证：重复运行只核验旧 Message-ID，发送调用仍只有一次。
- 隐藏输入不可用时直接停止，不触发 getpass 的可回显降级。
- 使用真实 macOS SecItem API 的临时随机条目完成 create/update/read-back/delete 测试并清理，结果 PASS。
- 沙盒中的 Keychain 访问返回 OSStatus -50；相同测试在获准的本机上下文成功。它说明沙盒失败不能作为“用户 Keychain 条目不存在”的证据。
- 本机只读健康检查确认当前邮箱条目存在且非空；未输出值，也未将此检查视为邮箱认证成功。

## IMAP 实机缺陷与修复回归

- 实机复现：LOGIN 返回 OK，但只读 INBOX 选择返回 `EXAMINE Unsafe Login`。原 probe 只验证 LOGIN，漏掉了后续邮箱读取条件。
- 先新增 5 个失败测试，复现缺失 ID 握手、中文 Sent 文件夹处理、带空格文件夹引号、读取被拒误当空收件箱等问题；修复后全部通过。
- 追加 ID 被拒时停止读取、MIME 编码不符及搜索返回不同 Message-ID 不得通过等回归，合计 8 个新增用例。
- 实机复核：SMTP/IMAP 认证、只读 INBOX 访问均通过；同一自测 Message-ID 在 INBOX 和服务器 Sent 中均找到；中文主题/正文/链接、UTF-8 text/plain、精确收发身份与 Message-ID 均通过。
- SMTP 实际接受 1 封本人自测邮件；后续核验没有重发。未通过 IMAP APPEND 制造 Sent 副本。
- 回复扫描流程执行完成，但第三方真实发送为 0，因此相关回复为 0；不声称已完成真实合作回复的分类验证。
- 自测不完整时 CLI 现返回非零退出码；历史 535 失败记录保留。

## 发送节奏与语言门禁更新

- 新增 13 项离线测试：默认 300 秒冷却、跨批次/重启持久化、另一连接无法重复占位、未批准不占位、模拟不消耗真实额度、等待中正文变更/拒绝联系/账号撤销均阻止提交、配置值校验与已有冷却不可缩短、失败停止本轮、未知异常不盲重试、CLI 单次确认且最多 30 秒一段等待、未知语言不得通过指定草稿语言绕过。
- 测试只使用临时 SQLite 和模拟 Adapter；未访问真实 SMTP、IMAP 或 Keychain。
- 本账号本地节奏设为 300 秒；没有建立新批次、没有新审批，也没有新增第三方发送。
- 本次 Skill 官方 `quick_validate.py` 因缺少可选 PyYAML 未能运行；已使用系统 Ruby YAML 安全解析器核验真实 frontmatter、必需/允许字段、名称与描述约束，通过。项目运行仍只依赖 Python 标准库；这与下方首轮历史兼容模块验证分别记录。

## Skill 与首轮验证（历史）

- `quick_validate.py`：`Skill is valid!`。本机缺少生成器可选依赖 PyYAML，因此验证时使用只实现 `safe_load` 的临时兼容模块；命名、frontmatter、允许字段、描述长度和 TODO 检查均由官方脚本执行。
- 未完成占位检查：`rg` 未发现 TODO/FIXME。
- V1.1 数据库：20 leads、3 历史/待审 drafts、1 个已失效 V1 batch、0 approvals、0 send attempts。
- Scout 实库哈希：导入前后均为 `81cf0053df14cb1e182adbd322c2ea4a8b9285b50f8b24a432eda4e406b49d3b`。
- 首轮复跑：相同草稿按 lead + content hash 复用，没有重复草稿；批次内容相同则复用原 batch。

## Provider 集成边界

Gmail API 仅有 Adapter 契约，企业邮箱仅有抽象接口。个人 163 的离线测试与本账号真实阶段一/二自测均已通过，真实证据单列于 `PROVIDER_INTEGRATION_TEST.md`。当前没有获批的第三方批次；自测通过不等于推广获批，未批准的外发仍被阻止。
