# LazyMind Scout 第二轮：产品能力反向找机会

2026-10-27，北京时间；run_id：`round2-20261027`。扫描 **5 个新仓库，深入 2 个**。结论是 **1 个优先验证的 Example，1 个低优先级收录备选，3 个排除**；当前可直接对外发布或提交的机会为 **0**。

使用工作区现有 V2 和上轮状态库。未发现标准安装目录中的另一份 Scout，未重新开发或修改 Skill。按本轮要求跳过首轮三个仓库，未再次访问它们；这不代表本轮重新确认它们没有更新。

| 方向 / 仓库 | A 技术 / B 生态（各10分） | 门槛与结论 |
|---|---:|---|
| 产品方案、售前、Skill：[anthropics/knowledge-work-plugins](https://github.com/anthropics/knowledge-work-plugins) | **8 / 4** | easy_extension；优先做团队自有 Example，非上游修复 PR |
| 分发：[e2b-dev/awesome-ai-agents](https://github.com/e2b-dev/awesome-ai-agents) | **6 / 3** | existing；保留收录备选，未达 A≥8 优先阈值 |
| 招投标：[xinsuifan-web/Tender-Assistant-V2.5](https://github.com/xinsuifan-web/Tender-Assistant-V2.5) | 2 / 2 | not_applicable；没有核实到可薄适配解决的需求 |
| Agent Runtime：[langchain-ai/deepagents](https://github.com/langchain-ai/deepagents/issues/6122) | 1 / 4 | upstream_only；缓存缺陷不能用 LazyMind 现成能力替代 |
| MCP 分发：[punkpeye/awesome-mcp-clients](https://github.com/punkpeye/awesome-mcp-clients) | 1 / 3 | not_applicable；缺少 LazyMind MCP **客户端**证据 |

分数按现有 V2 分项计算，没有把 Star 换算成分数；约 3 万 Star 的 DeepAgents 和 E2B 都未因此晋升。详细分项及证据保存在同目录的 `registry-results.json`。

**第一优先：把 Competitive Brief 做成诚实、可复现的 LazyMind Example。**

- **真实需求与版本：** [Issue #1381](https://github.com/anthropics/knowledge-work-plugins/issues/1381) 仍 open，报告 Skill 单独安装后丢失父目录 CONNECTORS。固定源 commit `c75fda00ff0e41c8ee331ae312c8a07f1967653b` 的 [competitive-brief](https://github.com/anthropics/knowledge-work-plugins/blob/c75fda00ff0e41c8ee331ae312c8a07f1967653b/product-management/skills/competitive-brief/SKILL.md) 仍引用该文件；业务用途明确包括产品策略、销售 battle card 和竞争方案。当前 finance/financial-statements 也保留该引用；sales/account-research 则已有文件输入降级说明，不能把所有 Skill 一概判成相同缺陷。
- **解决方式：** 在团队自有 Example 中保留来源/许可，补齐依赖文本和相对路径，提供固定离线事实卡与工具配置清单；用目录安装、步骤/Artifact 观测、官方步骤辅助重试这些已有路径展示实际行为。这是样例打包与验收工作，不改 Core，也不声称解决 claude.ai 安装器问题。
- **能力依据：** 事实库的 `skill_directory_install`、`workflow_observation`、`assisted_retry` 有同一 Competitive Brief 类型的既往运行记录。A=4+2+1+1：匹配明确、包装改动小，但目标包装未重跑，恢复也仍需辅助。B=3+0+1：有真实跨插件痛点，尚无维护者合作或有效触达规模证据。
- **必须实际验证：** 固定 Skill hash、模型/配置、事实卡和预算；原生与包装后的方案各至少 3 次。验收依赖解析、安装、真实步骤/产物状态；失败时记录重试是否复用前序产物，分别保留 session 与 external task 状态。检查引用、算术、事实/推断标签；不通过则只展示观测与失败诊断，不包装成业务成功案例。小样本不能证明稳定性或成本优势。
- **投稿渠道与行动类型：** **可制作 LazyMind Example**，先本地验证、再由用户审查团队自有 examples 文档/演示稿；**不推荐向该上游提交技术修复 PR**。[PR #1389](https://github.com/anthropics/knowledge-work-plugins/pull/1389) 已关闭且 `merged=false`。[当前关闭策略](https://github.com/anthropics/knowledge-work-plugins/blob/c75fda00ff0e41c8ee331ae312c8a07f1967653b/.github/workflows/close-external-prs.yml) 的外部例外仅覆盖特定已上线插件源的 marketplace 条目增补，不覆盖本方案。机器人给出的新插件申请入口不能当作 LazyMind 已符合收录资格；本轮不联系维护者。

这里使用 PR #873，是因为它恰好记录了 Competitive Brief 的安装、转换、观测和恢复边界，适合校准这个机会的能力表述。[EVALUATION](https://github.com/NicoYang1984/LazyMind/blob/fde2e68437caffa8dc6d706271dabc6073183938/examples/competitive-brief-skill2workflow/EVALUATION.md) 与 [ISSUES](https://github.com/NicoYang1984/LazyMind/blob/fde2e68437caffa8dc6d706271dabc6073183938/examples/competitive-brief-skill2workflow/ISSUES.md) 同时记录：自主执行停在 2/5、辅助恢复后 session 为 5/5 但原 task 仍 failed、编辑失败、生成图无强制审批。**这些记录不是本轮新 E2E，也不代表当前部署或所有业务能力已验证。**

**第二顺位备选：E2B 目录产品收录，暂不投入投稿。**

- **入口及痛点：** [README](https://github.com/e2b-dev/awesome-ai-agents/blob/main/README.md) 欢迎通过 PR 或其链接表单新增 AI 助手/Agent，解决产品发现问题；SDK/框架被指向其他目录。本轮没有发现该目录用户明确要求 LazyMind 的需求。
- **最小做法：** 等第一项通过验收后，以“可查看步骤和产物的工作流助手”准备一条归类正确、按字母排序的条目，附公开安装和可复现 Example。只复用 `workflow_observation` 的已有证据，不需要 Runtime 集成。
- **验证与风险：** 干净环境核实公开入口、安装和真实演示；提交前重查所有产品别名与现有 PR。本轮 LazyMind 的 Issue/PR 分开搜索均无结果，README 无同名项，但这不是别名穷尽检查。近期抽取的 5 个 closed PR 均未合并；检索中最新 updated 的 merged PR 是 [#1419](https://github.com/e2b-dev/awesome-ai-agents/pull/1419)，合并于 8 月 21 日且只是文档链接调整。[#1790](https://github.com/e2b-dev/awesome-ai-agents/pull/1790) 还显示 CLA 要求，不能把 PR 创建或关闭算作收录成功。
- **行动类型：** **适合保留为产品收录渠道**；不是技术修复 PR，也没有维护者合作承诺。投稿入口为 README 的 PR 或 [表单](https://forms.gle/UXQFCogLYrPFvfoUA)，本轮未打开/提交表单。A=3+2+1+0，B=1+1+1；低于优先阈值，不能与第一项等同推荐。

其余候选排除理由：

- **Tender-Assistant：** README 已有 Trace、人工确认、审阅/采纳流程，本轮 Issue API 返回 0 条；作者称其为原型，其自报测试不等于我们验证。没有明确可补足的薄适配缺口，不能把“能观察工作流”扩张为“已支持整套投标”。有真实需求或既有适配证据再评估，不因 86 Star 淘汰。
- **DeepAgents：** 已具备持久化、checkpoint、HITL 和 Skills。#6122 是上游 MemoryMiddleware 缓存一致性问题，作者已有分支并等待 assignment；技术修复应作为独立 Contributor 任务，不能借此推广替换 Runtime。其他已返回的路径验证和 QuickJS 启动策略需求也不匹配现成能力。
- **awesome-mcp-clients：** [示例投稿 #374](https://github.com/punkpeye/awesome-mcp-clients/pull/374) 需要连接 MCP server 的客户端能力。LazyMind 对外提供工作流工具的证据方向不同；先补客户端连接/发现/调用证据再判断，而不是断言产品绝对没有该能力。

本轮覆盖了产品/售前 Skill、财务报表样例、投标原型、Agent Runtime 和分发目录；**没有找到符合当前证据门槛的金融研究推广机会**。财务报表源码不能替代金融研究或财务准确性的运行证据。

**状态与续跑：** 已写入现有 V2 数据库 `first-run/isolated-data/opportunities.sqlite3`：5 条候选/排除记录、5 份仓库记忆、89 个本轮目标来源实体、8 个实际 Issue 的逐项结论。近期列表最多每仓库 20 条，旧历史未完整枚举，所有 Issue 水位保持原值；未深查 PR 保存在仓库记忆中，不冒充已分析。首轮三个仓库记录保持原样。

SQLite integrity_check 为 ok；5 个仓库同轮再领取均返回 skip_this_run；原 28 个 Skill 文件 SHA-256 未变。没有运行新的业务 E2E、修改生产 Core、发送邮件/评论或创建 PR。候选均未标记验证通过、合并、试用或转化。下轮先比较更新元数据和已看版本，只读取变化内容；优先验收第一项，第二项在 Example 通过后重评。

