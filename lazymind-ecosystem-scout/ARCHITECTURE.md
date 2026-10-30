# ARCHITECTURE

## Repository Intelligence 与 Opportunity Ranking 增量

详见 [版本化筛选说明](../pipeline/SCREENING.md)。`repository_intelligence.py` 把元数据、实质活动、外部 PR cohort 和政策原文转为带来源、时间、可信度的字段；`screening.py` 先 Gate，再按配置生成分数或区间、中文及 JSON 报告。已有 `ranking.py` 分发 profile/screen，保留旧 collect/rank。未知政策不触发昂贵采集；既有租约和游标继续由原 scanner 管理，新层不手动推进。

没有新表或身份迁移；使用 source_observations 的 source 类型区分画像与评分，保留原始快照及策略 hash，同版本不同配置被拒绝。source_items 的当前视图不是评分历史的替代品。只读取已有 Pipeline state，导出原 Spec，不自动提升 validation_status、写审批或对外发布。原生产能力门禁保持当前事实与阈值，可选固定时间和事实参数仅使离线回放确定性。

## 范围与数据流

这是原 Scout 的可靠性与团队复用升级。发现/筛选 → 证据化机会 → 用户审查 → 后续独立贡献执行。扫描本身没有外部写入工具、产品运行器或后台调度。

```text
GitHub GET / 已授权连接器原始响应       显式公开 Skill 目录 JSON
                ↓                              ↓
           GitHubAdapter                 CatalogAdapter
                └──────── 统一 item ────────────┘
                              ↓
             source_observations（保留来源与修订）
             source_items（规范主题当前视图）
                              ↓
        能力事实 + 具体 runnable_path + support_level
                              ↓
                A 技术适配 / B 用户与传播价值
                              ↓
        opportunities + history + 行动证据 → 独立 Contributor 交接
```

原包的 GitHub Scanner 主要是 SKILL.md 中的执行流程，没有独立网络抓取脚本。V2 保留该流程，将分页、去重和入库约束固化为小型 adapter/runner。

## 保留与新增模块

- `scripts/registry.py`：保留原命令、表结构和 JSON 历史；新增租约/别名/处理结论命令，调用状态和策略模块。
- `scripts/state.py`：SQLite 事务、租约、深合并、来源观察、分页记录、待办与改名。
- `scripts/sources.py`：统一来源 Schema、只读传输接口、GitHub、目录清单和连接器快照适配。
- `scripts/scan.py`：有限分页扫描，默认每仓库最多 2 页、每次请求最多 4 MB；接受显式仓库 ID。
- `scripts/policy.py`：六类事实准入、双轴评分、行动结果的结构化证据要求。
- `scripts/migrate.py`：只读打开旧数据库，用 SQLite backup 创建新副本，再升级副本。

Python 3.9+，运行和测试仅用标准库。Skill 格式验证器本身可依赖 PyYAML，但它不是本 Skill 的运行依赖。

## SQLite 不变量

原有 opportunities/history/runs/repositories/repository_history/repository_visits 保留。新增 claims、repo_ids/repo_aliases、source_items/source_observations、scans、dispositions。

- 初始化 schema 与 user_version=2 在同一事务提交。非 V2 旧库不能原地 init。
- 同一仓库只允许一个未过期 claim；BEGIN IMMEDIATE 序列化领取。repo-start 同时写初始 partial，崩溃不会留下“已领取但无检查点”。
- 每次重新领取生成新 token；repo-put、heartbeat、分页写入和 dispose 验证 repo/run/token/expiry。租约过期后旧写者被拒绝。
- 同轮已完成仓库 skip；活动租约同轮 skip、其他轮 busy；过期 partial 返回 resume。
- 每页所有观察、待办、扫描页号和检查点同事务提交。页序错误、非法对象、写入失败整页回滚。
- 未完整分页不得推进 last_issue_number/updates_checked_through；只有 scanner-owned ingest_page 可推进。repo-put 禁止任意水位变化。
- 所有真实 Issue 要么有对应版本处理结论，要么进入 pending；PR 单独分型。空数组不清空待办。dispose + resolved_issue_numbers 才能移除；Issue 更新可重新入队。
- memory/coverage/cursor 嵌套对象递归合并，列表并集，null/省略保留；不提供隐式删除接口。标量更新仍在 repository_history 留完整版本。
- GitHub 数字 ID 识别改名；冲突或活动租约阻止合并。当前机会 URL 重定向到新名，原历史不改写。库不支持多机器共享网络盘并发：团队复制 Skill，每人/任务指定数据目录；同机器 SQLite 可串行协调多个进程。

## 分页与增量的实际边界

GitHub Issues all-state 按 updated 升序枚举，包含 PR。完整扫描后记录开始时刻为水位；下一轮回退 5 分钟，旧 Issue 更新不会因编号较小被跳过。编号不是连续计数，也不代替更新时间。

崩溃后从查询第一页重枚举元数据，按 canonical subject/revision 去重，避免直接续用已经漂移的 offset。有限预算留下 partial 和 pending。搜索补充使用 ingest_findings，只追加待办，不建立覆盖证明。

GitHub REST 列表不提供事务性快照。扫描期间删除、转移或大量重排仍可能使 offset 漂移，5 分钟重叠不能给出数学上的零遗漏保证。关键审计范围应再做 bounded reconciliation；不得把本工具称为 GitHub 完整备份。这里保证的是：已获取记录不会因崩溃/空数组/未完成分页丢失，代码不会把不完整查询当成完成。

连接器快照输入保留来源与读取时间，即便尾页不足 100 也不推进当前 live 水位。本轮真实扫描采用这一保守路径，未冒充 HTTP transport 的网络测试。

## 团队使用

所有命令从 Skill 目录运行，路径也可换为安装后的绝对路径。

```bash
python3 scripts/registry.py init --data-dir ./team-scout-data
python3 scripts/registry.py repo-start --data-dir ./team-scout-data --repo owner/repo --run-id run-001
# 将返回的 claim_token 带入心跳及 checkpoint；不要把示例 TOKEN 当真值。
python3 scripts/registry.py repo-heartbeat --data-dir ./team-scout-data --repo owner/repo --run-id run-001 --claim-token TOKEN
python3 scripts/registry.py repo-put --data-dir ./team-scout-data --file checkpoint.json --claim-token TOKEN
```

使用完整 scanner 时由它领取和保存，不要先手动 repo-start 占用同一任务：

```bash
python3 scripts/scan.py --data-dir ./team-scout-data github --repo owner/repo --repo-id 123 --run-id run-001 --max-pages 2
python3 scripts/scan.py --data-dir ./team-scout-data catalog --file references/public-catalog.json
python3 scripts/registry.py list --data-dir ./team-scout-data
python3 -m unittest discover -s scripts -v
```

repo-id 必须先从公开仓库元数据核实。HTTP transport 可使用显式环境变量 GITHUB_TOKEN，不读取个人钥匙串，不打印 token；401/403/429 停止，不切换凭据绕过配额。元数据/原始页也可由宿主授权连接器取得，再用 `--snapshot capture.json` 只读解析。

目录来源本期是显式 JSON 清单导入，不是自动发现远程目录的爬虫。Discussions、社区、行业和授权产品反馈只完成 Schema/接口，平台采集留待实际需求。没有外部网络条件也能运行全部单测。

## 能力与业务范围

十四类地图保留，但不把每类全部产品叙述当成已通过 E2E。事实按细粒度路径和版本维护；PR873 只校准它实际涉及的路径。业务领域映射不提供新的业务能力。文档、源码、单测与 E2E 各有证据边界。

状态 Schema 只能校验结构和约束，不能自动鉴定一个链接/文字是否真实证明能力或转化。维护者仍需读原证据；runnable_path 与能力不能错配。首次所有机会都保持 source_reviewed，没有捏造产品试用。
