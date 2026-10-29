# TEST_REPORT

核验日期：2026-10-27。环境：macOS arm64、系统 Python 3.9，SQLite、unittest；所有业务代码仅使用标准库。所有单测使用 TemporaryDirectory 下隔离 SQLite，未访问同事真实数据库。

## 结果

| 验证 | 实际结果 |
|---|---|
| 原包未改动的 test_registry.py | 2/2 通过 |
| 原版缺陷复现 | 已复现无 checkpoint 领取无法续跑、未完成分页游标推进、嵌套记忆/数组/coverage 覆盖 |
| V2 全测试 | 39/39 通过，最后一次耗时 1.226 秒 |
| 官方 Skill quick_validate.py | Skill is valid! |
| Python compileall | 通过；缓存写入隔离 /tmp 目录 |
| 三个真实候选只读取证与快照 adapter 入库 | 完成，170 个主题实体、172 条来源观察、3 条候选、2 条 Issue 处理结论 |
| LazyMind 产品 E2E | 本次没有运行；PR873 只是已有证据审读 |

原测试保留在输入 ZIP/原版目录并先原样执行。V2 `test_registry.py` 保留原两个测试场景；增量测试的 fixture 调整为 claim token + 分页记录，因为原版允许手写游标的行为正是要修复的问题。未隐藏旧测试失败，也未声称 V2 无协议变化。

## 复现命令

```bash
# 在升级后 Skill 目录内
python3 -m unittest discover -s scripts -v
PYTHONPYCACHEPREFIX=/tmp/scout-pycache python3 -m compileall -q scripts
```

官方 quick_validate.py 初次因环境缺少 PyYAML 无法启动；将 PyYAML 6.0.3 安装到临时验证目录后成功运行。未将其变为 Skill 运行依赖。compileall 初次尝试系统缓存目录受到沙箱限制，改用隔离缓存后通过。这两项环境失败与单测结果分开记录。

## 问题—回归测试对应

| 原问题/需求 | 回归证据 |
|---|---|
| 领取后没 checkpoint 就崩溃 | test_crash_before_first_checkpoint_is_resumable；test_actual_process_crash_after_claim 使用子进程 os._exit(19) |
| 旧进程覆盖新检查点 | 过期重领生成新 token；旧写入拒绝；heartbeat CLI 测试 |
| 同轮去重/团队并发 | concurrent_claim_same_run_only_one_wins、cross_run_active_worker_not_stolen、concurrent_fresh_initialization |
| 未完成分页错误推进 | unfinished_page_never_advances_cursor、out_of_order_page_and_failed_batch_roll_back、budgeted scan |
| 未处理 Issue 丢失 | pages_complete_pending_survives_and_pr_not_issue、pending_cannot_be_removed_without_disposition、supplemental_search_finding_is_pending_without_watermark |
| 跨轮增量和旧 Issue 新更新 | cross_run_old_updated_issue_reopens_pending、原 incremental 场景 |
| memory/cursor/coverage 覆盖 | deep_memory_and_coverage_keep_prior_history；类型替换拒绝、数组并集、完整历史 |
| 个人路径与原数据保护 | portable_paths、old_database_refused_without_writing、migration_readonly_source_preserves_history_and_orphan_claim |
| 仓库改名 | rename_keeps_memory_and_same_run_dedup、CLI action_history_and_rename、renamed_repo_rejects_disposition_older_than_observation |
| 跨来源去重 | different_sources_same_subject_dedup_without_losing_provenance；精确主题合并，观察不丢 |
| 能力虚假升级 | known_failures_documented_and_unavailable_are_excluded、stale_evidence_requires_refresh、catalog_has_version_sources_date_and_scoped_failures |
| 评分混淆 | high_stars_low_fit_never_recommended、small_project_keeps_collaboration_potential_not_top_channel |
| PR=合并、评论=转化误判 | pr_creation_and_comments_do_not_imply_results、ready_requires_actual_validation、CLI 历史保留和非法 merge 写入回滚 |
| API/权限边界 | rate_limit_stops_no_retry、github_only_get_rejects_other_hosts、feedback_requires_authorization |
| 新来源只读 | catalog_readonly_and_source_schema；真实公开目录清单导入 |
| 网络快照不伪装完整扫描 | snapshot_replay_does_not_advance_live_watermark |

## 原版审计的准确结论

原版 SQLite 的 history/repository_history 本身仍保留旧快照，并非历史表被删除。但最新 materialized payload 中，嵌套对象、数组、coverage 会被新输入整体替换，导致续跑只看当前记忆时丢信息。V2 修复当前视图合并并继续保留历史。

原版 score 没有使用 Star 公式；问题是一个合成分数承载了交付性、价值、证据和成本，没有单独表达传播/目标用户价值，容易把技术 Demo 的高分直接当成宣传优先级。V2 新增 B 轴，未声称原代码按 Star 自动排名。

## 仍未证明的范围

- 未在 Windows/Linux 上运行；路径和标准库实现具备可移植设计，但不等于跨平台实测。
- 没有跨机器/网络文件系统 SQLite 并发测试，不推荐共享网络盘写库。
- HTTP transport 的限流、预算、错误由模拟测试覆盖；本机匿名 GitHub 请求实际返回 403 配额耗尽后即停止。真实内容从已授权连接器 GET 获取，不能据此宣称 Python HTTP 网络路径全部通过。
- REST offset 分页在上游并发删除/重排下不是一致性快照。已获取项、事务恢复和不完整游标保护有测试；不保证任意上游变化下零漏项。
- 状态/证据 Schema 不会自动鉴定外部资料真伪；业务事实仍需阅读原来源。

原始测试日志和结构化审计摘录见 [validation](validation/)；实际扫描边界见 [FIRST_RUN_REPORT.md](FIRST_RUN_REPORT.md)。
