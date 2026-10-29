# 2026-10-29 Pipeline 升级与真实回归

本轮交付是工作流代码升级。**外部新建 PR 0、外部新合并 0、外联发送 0**。两条既有 PR 的创建/合并属于历史事实，没有计入本轮成果。

## 实际代码改动

- `opportunity.py` 和 JSON Schema：独立 Campaign、稳定机会 ID、证据引用、GO/NO-GO、历史来源及渠道门槛。
- `pipeline_store.py`：在既有 V2 SQLite 追加契约、执行状态、事件历史、GitHub ETag 缓存；旧表和 user_version 不变。重复导入、失败恢复、显式新 attempt 和历史保存。
- `pipeline_github.py`：有界完整分页、政策/PR/Issue 取证、重复检测，以及 PR / Commit / CI / Review / merge 的分轴查询。
- `contributor.py`、`pipeline.py`：环境和权限预检、独立 Worktree、最小计划、Codex 审查/实现、定向测试、符合上游模板的 PR 草稿、Commit 与授权绑定、发布前复查及不确定提交恢复。
- Scout 原 CLI 增加 `handoff/handoffs`；Outreach 增加 `import-pipeline`，复用原数据库、抑制和审批机制。未重写任何原组件，`policy.py` 和 LazyMind Core 未改。
- 删除 3 份完全重复的旧日志，保留对应原件与 [校验索引](../audit/retained-duplicates.json)。其他历史审计、来源、许可证和原版代码保留。

## 三条真实路线

最终 GitHub API 复核时间：**2026-10-29 09:27 UTC（17:27 中国时间）**。原始采集字段投影见 [github-cases.json](regression/github-cases.json)，最终复核见 [final-live-check.json](regression/final-live-check.json)。

| 路线 | 真实来源 | 结果与交接 |
| --- | --- | --- |
| `resource_listing` | [awesome-agents #895](https://github.com/kyrolabs/awesome-agents/pull/895) | 已于 2026-10-27 10:54:08 UTC 合并；历史收录，`merged`。无 CI 不伪造 ci_passed；不再次提交。 |
| `product_integration` | [marketingskills #916](https://github.com/coreyhaines31/marketingskills/pull/916) | PR open，head `f5d70c5b…`；[Regression Tests](https://github.com/coreyhaines31/marketingskills/actions/runs/40839332628) 为 `action_required`，review pending。需维护者处理 CI，不是“已合并”或“代码测试失败”。 |
| `native_skill_fix` | [marketingskills #913](https://github.com/coreyhaines31/marketingskills/issues/913) | 原生 JS 缺陷，真实复现；不要求 LazyMind 能力匹配。已有 open 修复 [#914](https://github.com/coreyhaines31/marketingskills/pull/914)，故 `blocked` / NO-GO，交接为跟踪及回归覆盖审查。 |

固定 `main` commit `0cd9b3a0ef4c411a1d690419ce843f2a1da32cce` 上，确认页初次到达、刷新、Back 返回分别发出 **1、1、1** 个转换事件，预期为 **1、0、0**。本轮用经过阅读的上游 snippet 在独立 Node VM 中复现；这是无浏览器的逻辑复现，不宣称完成真实网站浏览器验证。代码与结果见 [复现脚本](regression/reproduce-native.cjs)、[结果](regression/native-reproduction.json)。该版本在最终 API 复核时仍是上游 main。

三份可导入交接包位于 [examples](examples/)。两份历史包带 `historical_import`，原生 Bug 包保留重复拦截证据。三者没有明确合适合作渠道，因此产生 **0 个 Outreach 联系任务**；PR 合并不自动授权外联。

可复现的离线回放，不修改真实数据库：

```bash
python3 pipeline/regression/replay.py
```

回放验证分类、稳定 ID、重复导入、状态变化去重与外联门槛，结果见 [replay-result.json](regression/replay-result.json)。离线快照不替代下一次实时查询。

## 完整验证结果

| 验证 | 结果 |
| --- | --- |
| 升级前 Scout / Outreach 基线 | 39 / 45 项通过 |
| 升级后 Scout（含 Pipeline） | 73 项通过 |
| 升级后 Outreach | 49 项通过 |
| 保留原版 Scout 的独立回归 | 2 项通过 |
| 总计 | **124 项通过，0 失败**；其中当前组件 122 项 |
| 独立 JSON Schema 验证 | jsonschema 4.23.0 检查 3 份 Draft 2020-12 Schema 和 3 份规范化示例通过；仅安装于 /tmp，未新增运行依赖 |
| 源码及 Diff | 全部当前 Python 源码 AST 解析、`git diff --check` 通过 |
| 真实 Codex CLI 冒烟 | 临时合成仓库中完成文件修改并通过字节级校验；JSON events / schema / final result 正常 |

完整测试输出：[tests.txt](regression/tests.txt)。[Codex 冒烟回执](regression/codex-smoke.json)。执行回归使用真实临时 Git Worktree、真实本地测试和 Commit，Agent/网络边界用替身测试中断、重复、授权和失败路径；没有为测试向上游创建 PR。

已连接 GitHub 工具的真实 REST 查询成功。新增 CLI 的匿名在线 GET 遇到 HTTP 403，已记录错误并保留上次结果；在此机器独立运行 `track/publish` 前需配置合适的 `GITHUB_TOKEN` 和 Git 推送凭据。没有声称完成“通过新 CLI 发布真实上游 PR”的端到端验收。GitHub 创建 PR 的成功/响应丢失路径由离线测试覆盖。

## 下一轮可直接执行的任务

1. **集成追踪**：导入 `product-integration.json` 后对 `opp_1be5f8e79f0a57c3a332ce80` 执行 `track`；维护者允许 Actions 后读取真实 CI。仅在 checks/review 有具体问题时准备修订；不重复开 PR、不替维护者审批运行。
2. **原生修复审查**：围绕 #913 → #914 核对 refresh、back/forward、第二次真实转换、SPA、`COUNT_EVERY_VIEW` 的测试覆盖。结果先保存在本地；当前不创建竞争修复 PR，也不自动评论。
3. **收录维护**：`opp_96dbecec0e237c960802ab2f` 保留 merged 历史和 canonical 项目入口，不再次收录；将来只在链接/类别变化时刷新证据。
4. **新机会**：Scout 使用同一 Schema 继续收集无重复、证据充分的候选。本轮没有把现有 PR 或已有人修复的问题冒充可直接新开 PR 的机会。获得新的真实 GO 后，按 [run → commit → authorize → publish](README.md#contributor-执行与发布) 执行。

## 减少的人工步骤

- 不再在 Scout、Contributor 和外联之间手工复制问题、证据、规则、环境与验收计划。
- 自动生成稳定 ID、识别重复导入和既有 PR，保留失败位置与历史，避免中断后从头重建上下文。
- 自动建立独立分支/Worktree、生成计划、调用 Codex、重跑定向测试和整理 PR 正文。
- 把验收、Commit、授权和发布内容绑定；自动核对不确定提交，避免重复开 PR。
- 自动查询并区分 CI 待批准、测试失败、Review 与合并；只在状态变化时追加结果。
- 只为有证据的合适渠道生成待审候选，省去无效外联筛查。发送审批仍由现有 Outreach 流程处理。

这些是已实现的步骤替代，没有测量或承诺节省多少分钟、提升多少合并率。
