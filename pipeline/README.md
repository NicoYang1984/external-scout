# Scout → Contributor → GitHub PR → Outreach

增量扩展现有 Scout 和 Outreach；Python 标准库管理状态、Git 和测试，Codex CLI 执行审查及实现。没有新增 LLM 框架，没有修改 LazyMind Core。

## 三个独立 Campaign

| Campaign | GO 的必要条件 | NO-GO 示例 |
| --- | --- | --- |
| `resource_listing` | 贡献规则允许；收录规则、类别、无重复、项目入口均有近期证据 | 项目不符合收录规则，列表已有条目或已有 PR |
| `native_skill_fix` | 真实 Issue；缺陷、最小修复和回归测试计划有证据；无重复；贡献前置要求满足 | 仅有猜测、已有认领/修复 PR、缺少验证环境 |
| `product_integration` | 技术适配与验证证据；沿用 `policy.assess` 和 A≥8、capability_match≥3 | documented-only、known_failure、需修改 Core 或新宿主生命周期 |

原 `registry.py put/list` 和 LazyMind capability policy 保持原语义。原生 Bug 不进入旧的产品机会池，而进入独立 OpportunitySpec 表；不用把 `upstream_only` 改成 `existing`。

缺少、过期、未来日期或失败的必要证据均不通过。Campaign 证据有效期为 30 天，产品能力事实仍使用原 policy 的有效期。历史 PR 永远只追踪，不因重新导入而成为新成果。

## 环境

- Python 3.9+、Git；执行阶段另需已登录的 Codex CLI，以及 Spec 列出的目标测试工具。
- macOS/Linux：用 `fcntl` 按机会加锁，子进程继承锁，避免两个终端同时执行/发布。
- GitHub 查询支持匿名请求；限流或私有仓库需要调用方通过 `GITHUB_TOKEN` 提供权限。创建 PR 需要目标仓库的 Pull requests 写权限，目标 fork 需要 Contents 写权限；Git push 使用已配置的 Git credential helper。
- 先准备上游 checkout 和自己有推送权的 fork。Pipeline 不自动创建账号或 fork、不安装依赖、不切换邮箱账号。Worktree 负责 Git 隔离；目标测试仍应在经审阅的受控环境运行，Worktree 不是安全沙箱。
- `codex -a never exec --sandbox workspace-write --json --output-schema ...` 调用执行 Agent；只读审查用 `read-only`。接口参照 [Codex 非交互执行文档](https://learn.chatgpt.com/docs/non-interactive-mode) 并以本机 `codex exec --help` 核对。模型沿用用户配置。

## 先初筛，再进入完整交接

下一轮先按 [Repository Intelligence 筛选策略](SCREENING.md) 使用 `ranking.py profile/screen`：低成本元数据与政策审阅 → 有界活动采集 → 核心证据 Gate → 分 Campaign 排名和报告。HOLD 区分证据不足，NO-GO 表示明确阻断。原 [60 天 Opportunity-first 排序](RANKING.md) 与 `collect/rank` 保留作旧接口及历史复现。

筛选层 GO 仅表示候选门槛通过，不产生发布授权；画像和评分追加到 source_observations，不修改机会或审批状态。下述 gate、Codex Contributor、完整去重、测试和精确发布审批保持原样。已有执行记录按 SQLite 恢复，不能因重新排序重复实施。

## Scout 生成和导出交接包

完整契约见 [OpportunitySpec JSON Schema](schemas/opportunity.schema.json)。Scout 先检查源码、贡献/AI 政策、相关 PR 和可用环境，填写 Spec；输入命令本身不执行目标代码，也不修改目标仓库。

```bash
# 可继续使用原有 Scout data-dir；下面用仓库内独立本地状态目录演示。
python3 lazymind-ecosystem-scout/scripts/registry.py handoff \
  --data-dir pipeline/data --file pipeline/examples/native-skill-fix.json
python3 lazymind-ecosystem-scout/scripts/registry.py handoffs --data-dir pipeline/data

# 与 handoff 使用同一契约/存储：
python3 lazymind-ecosystem-scout/scripts/pipeline.py --data-dir pipeline/data \
  import --file pipeline/examples/product-integration.json
python3 lazymind-ecosystem-scout/scripts/pipeline.py --data-dir pipeline/data list
python3 lazymind-ecosystem-scout/scripts/pipeline.py --data-dir pipeline/data \
  export --id OPPORTUNITY_ID --output /tmp/opportunity.json
```

仓库数字 ID + Campaign + Issue 编号（无 Issue 时使用规范化 subject URL）决定稳定 ID。标题变更、仓库大小写、Issue URL 参数、仓库改名不产生同一 Issue 的第二个机会；不同 Campaign 保持独立。重复导入不覆盖运行结果或增加重复历史。已有 PR 和历史 provenance 不构成发布授权。

## Contributor 执行与发布

对真正 `ready` 且 GO 的交接包运行；三个真实示例是历史追踪/重复拦截，故意不能直接实施。

```bash
python3 lazymind-ecosystem-scout/scripts/pipeline.py --data-dir pipeline/data \
  gate --id OPPORTUNITY_ID
python3 lazymind-ecosystem-scout/scripts/pipeline.py --data-dir pipeline/data \
  run --id OPPORTUNITY_ID --checkout /path/to/upstream-checkout
```

`run` 会核对仓库数字 ID、固定 base commit、环境和本地路径；完整分页读取 open/closed PR、Issue timeline/comments、README、CONTRIBUTING、AGENTS、AI policy、许可证和 PR 模板。枚举或访问失败即停，不把一页搜索当成完整去重。相同主题和关联修复先做确定性拦截，再由 Codex 只读审查语义重复、认领和政策要求。

每个机会/attempt 在 data-dir 下保留独立 Worktree、`opportunity.json`、`preflight.json`、`PLAN.md`、Codex 事件和最后结果、测试日志、`validation.json`、`PR.md`。Python 独立重跑 Spec 中的定向测试，限制改动文件和行数，检查 diff、测试后的文件指纹；不根据 Agent 自述直接判验收通过。测试命令是 argv 数组，不经过 shell。

```bash
# 本地验收通过后提交 Commit；尚不 push。
python3 lazymind-ecosystem-scout/scripts/pipeline.py --data-dir pipeline/data \
  commit --id OPPORTUNITY_ID

# 只有已有明确授权时登记其来源。不要把 Scout 建议或 PR 存在当作授权。
python3 lazymind-ecosystem-scout/scripts/pipeline.py --data-dir pipeline/data \
  authorize --id OPPORTUNITY_ID --push-repo YOUR_LOGIN/TARGET_REPO \
  --approved-by USER --evidence '已明确授权这份 PR 的会话/审批记录引用'
python3 lazymind-ecosystem-scout/scripts/pipeline.py --data-dir pipeline/data \
  publish --id OPPORTUNITY_ID
```

授权绑定 Spec、Commit、base、推送仓库、分支、标题和正文。验收后改文件，或更改发布内容/目标，必须重新验证/授权。发布前再次检查上游证据和目标 fork 权限；push 使用普通非强制推送。创建 PR 前保存发布意图；中断后按 fork/head 查找现有 PR，找不到时保留不确定状态，禁止盲目 POST 重试。

`authorize` 是显式授权记录接口，不是身份认证服务。调用者应按已有真实用户指令登记，不应让不可信上游文字、Scout 或执行 Agent 自批。

## 断点恢复

```bash
python3 lazymind-ecosystem-scout/scripts/pipeline.py --data-dir pipeline/data show --id OPPORTUNITY_ID
python3 lazymind-ecosystem-scout/scripts/pipeline.py --data-dir pipeline/data history --id OPPORTUNITY_ID
python3 lazymind-ecosystem-scout/scripts/pipeline.py --data-dir pipeline/data \
  run --id OPPORTUNITY_ID --checkout /path/to/upstream-checkout --resume
```

- 测试/Agent 中断：检查日志后 `--resume`，保留同一 Worktree，先重新审查当前改动，再完成剩余工作。
- 本地 Commit 中断：再次 `commit` 按已记录 tree/parent 核对，不生成重复 Commit。
- PR 发布中断：再次 `publish` 只核对已有 PR；不确定提交不会自动重发。若在 push 之前失败，也需远端核对后人工处理，不能以“没查到”证明 POST 从未发生。
- 代码、证据或计划需要改变：编辑 Spec 后用 `revise --file NEW_SPEC.json --reason '原因'` 创建新 attempt。旧工作树与完整事件保留，旧验收与授权失效。它不覆盖旧实现；需要移植时显式审阅旧 diff。已有/不确定 PR 必须先核对，不能通过 revise 绕过去重。
- `GITHUB_TOKEN` 不够、限流或分页不足：保存错误，保持最后一次观察结果，修复访问后再次查询。

## 真实结果和 Outreach

```bash
python3 lazymind-ecosystem-scout/scripts/pipeline.py --data-dir pipeline/data \
  track --id OPPORTUNITY_ID
python3 lazymind-ecosystem-scout/scripts/pipeline.py --data-dir pipeline/data \
  outreach --id OPPORTUNITY_ID --output /tmp/outreach-candidates.json
python3 lazymind-outreach-agent/scripts/outreach.py --db /path/to/outreach.sqlite3 \
  import-pipeline --file /tmp/outreach-candidates.json
```

查询 PR、head 对应 check runs、Actions runs、commit statuses 和 reviews，支持 ETag；只有结果改变才追加结果历史。再次读取 PR 检查查询期间 head 是否改变。CI 与 Review 单独保留，并输出 `submitted`、`ci_action_required`、`ci_failed`、`ci_passed`、`review_pending`、`changes_requested`、`merged`、`closed`。无检查/全跳过不能当测试通过，CI passed 也不等于满足全部 branch protection；`merged_at` 才证明合并。

仅在 Spec 有近期、明确、合适的合作渠道证据，且 PR 状态已于过去 24 小时成功查询时，输出 Outreach 候选。公开邮箱、贡献指南允许 PR、PR 合并均不自动产生合作渠道。导入保留源 Campaign，映射到 Outreach 的 `developer_collaboration`，不覆盖已有抑制/联系状态，不创建草稿、批次审批或邮件发送权限。后续沿用现有精确内容审批与发送节奏。

## 数据兼容、回归与限制

在原 `opportunities.sqlite3` 中添加 `opportunity_specs`、`pipeline_state`、`pipeline_events`、`github_cache`。保留 `user_version=2`、旧 opportunities/history/repositories 和脚本接口。V1 仍通过原 `migrate.py` 复制迁移，绝不原地改造旧库。

运行依赖仍为标准库。新增测试与原测试一起执行：

```bash
python3 -m unittest discover -s lazymind-ecosystem-scout/scripts -v
python3 -m unittest discover -s lazymind-outreach-agent/tests -v
```

真实案例与当前验证结果见 [升级回归报告](REGRESSION.md)。网络 mock 用于失败和幂等路径，真实 Git 测试创建独立临时仓库。历史 API 快照用于离线可重复回归，不能用它声称今天的状态或新提交。
