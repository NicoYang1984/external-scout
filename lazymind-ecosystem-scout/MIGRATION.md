# MIGRATION

## 不触碰原同事数据库

本次只使用原始 Skill ZIP、临时测试库和工作区内的 first-run/isolated-data。没有读取或修改同事实际 SQLite。原 ZIP 保留，SHA-256：

`6ef142bb2cf261ef270f760eb69d27dc63d9e3ad2216b3765b710cee836daeb5`

V2 的默认目录与 V1 不同，不自动搜索或迁移 `~/.codex/lazymind-ecosystem`。即使显式指到旧格式库，registry.py 也会拒绝原地写入。

## 迁移副本

停止 V1 写者后，用明确的旧文件路径和**不存在的新目录**运行：

```bash
python3 scripts/migrate.py --source /path/to/v1/opportunities.sqlite3 --destination /path/to/new-scout-v2
python3 scripts/registry.py repos --data-dir /path/to/new-scout-v2
python3 scripts/registry.py history --data-dir /path/to/new-scout-v2
```

源库以 SQLite `mode=ro` 打开；backup API 将内容复制到新库。目标存在就拒绝，不覆盖任何文件。旧 config 不复制，避免携带同事路径；新 config 使用便携默认值。团队自行填写项目路径、seed 和预算，产品仓库也可由 LAZYMIND_PROJECT_ROOT 指定。

副本的升级策略：

- 原 opportunities、history、runs、仓库历史和访问记录保留。
- 原 cursor 移到 legacy_cursor，未证实的扫描水位从 0 开始重建；旧 pending 保留。再次枚举元数据时利用旧已读 URL/结论，避免把未知历史当成完成。
- 有访问记录却无仓库检查点的 V1 崩溃情况补 partial，可沿用原 run_id 续领。
- 旧 validated/ready_for_review 的当前视图降为 verification_pending，原值保存在 legacy_status；旧历史不改。原证据未自动升级为 V2 能力或业务验证。
- 行动字段在后续 put 时添加默认值；V1 score 只保留作历史，新的推荐必须提供 A/B、capability_ids、runnable_path 和证据。

## CLI 协议变化

repo-start 返回 claim_token 和 lease_expires_at；repo-put、repo-heartbeat、dispose 需要该 token。默认租约 300 秒，可设 1–3600 秒。崩溃后租约过期重新领取，旧 token 不可继续使用。

repo-put 不允许推进 last_issue_number/updates_checked_through。由 scan.py 完整分页推进；手工搜索结果只保存 findings 和 pending。数组不会被空数组清除，处理完成的待办要先 dispose，再用 resolved_issue_numbers 显式移除。历史失误需在副本上审计，不能用空对象抹掉原事实。

回滚：停止 V2，保留 V2 目录作为审计材料，继续使用未被修改的 V1 原库。不要把 V2 文件覆盖回 V1，也不要让两个版本写同一个目录。迁移是一次性动作，不是双向同步。

验证覆盖源文件 hash 不变、旧 runs/history 保留、孤立领取恢复、目标存在拒绝，以及原地 init 旧库拒绝。SQLite 跨设备传输建议用 backup 得到一致副本，不在活动 WAL 写入期间仅复制主文件。
