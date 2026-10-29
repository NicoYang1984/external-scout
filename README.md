# External Scout

LazyMind 的生态机会发现与外联工作区，包含两个独立的 Python 组件、测试、参考资料和历史审计记录。

新增 [可恢复贡献 Pipeline](pipeline/README.md)：Scout → Contributor（Codex）→ GitHub PR → Outreach。三种 Campaign 分别验证资源收录、原生 Skill 修复和产品集成；沿用已有 SQLite 与脚本，历史贡献单独标识。[真实回归和升级结果](pipeline/REGRESSION.md)。

- **Ecosystem Scout**：从 GitHub 与显式目录清单收集机会，维护证据、评分、分页检查点和处理历史。
- **Outreach Agent**：只读导入 Scout 机会，管理联系渠道、草稿、批次审核、模拟发送与受控的网易 163 邮件接口。

两个组件使用各自的 SQLite 数据库。运行依赖仅为 Python 3.9+ 标准库。

## 目录导航

| 目录 | 用途 |
| --- | --- |
| [`lazymind-ecosystem-scout/`](lazymind-ecosystem-scout/) | 当前 Scout 源码、Skill 入口、参考资料与回归测试 |
| [`lazymind-outreach-agent/`](lazymind-outreach-agent/) | 当前 Outreach 源码、测试、操作说明与审核材料 |
| [`pipeline/`](pipeline/) | 统一交接契约、三条真实路线示例、使用说明与回归证据 |
| [`original/`](original/) | 原始 Scout 版本，供审计与行为对照 |
| [`audit/`](audit/) | 原版问题复现和升级验证记录 |
| [`evidence/`](evidence/) | 来源证据、仓库快照和评估记录 |
| [`first-run/`](first-run/) | 首轮扫描结果与机会摘要 |
| [`pr873-work/`](pr873-work/) | PR873 相关验证、修正及历史材料 |

历史报告描述其记录日期的状态；当前代码以两个主组件目录为准。保留原目录布局，便于现有脚本与证据引用继续使用。

## 快速开始

从仓库根目录执行以下命令，创建全新的本地状态库：

```bash
python3 lazymind-ecosystem-scout/scripts/registry.py init \
  --data-dir ./lazymind-ecosystem-scout/data
python3 lazymind-outreach-agent/scripts/outreach.py \
  --db ./lazymind-outreach-agent/data/outreach.sqlite3 init
```

这两步只初始化本地状态。扫描、机会导入和邮件配置请查看组件文档；历史运行数据库不随仓库提供。

## 运行测试

```bash
python3 -m unittest discover -s lazymind-ecosystem-scout/scripts -v
python3 -m unittest discover -s lazymind-outreach-agent/tests -v
```

两套测试分别发现，使用临时数据库与模拟接口。无需配置邮箱授权码或发送真实邮件。

## 主要文档

- [Scout Skill](lazymind-ecosystem-scout/SKILL.md)、[架构](lazymind-ecosystem-scout/ARCHITECTURE.md)、[迁移说明](lazymind-ecosystem-scout/MIGRATION.md)
- [Outreach 使用说明](lazymind-outreach-agent/README.md)、[架构](lazymind-outreach-agent/ARCHITECTURE.md)、[外联规则](lazymind-outreach-agent/OUTREACH_POLICY.md)
- [网易邮箱配置](lazymind-outreach-agent/NETEASE_SETUP.md)、[当前能力与发送节奏](lazymind-outreach-agent/references/operating-capabilities.md)

## 版本管理范围

提交源码、测试、文档、参考资料和可审阅的历史材料。`.gitignore` 排除本地 SQLite 状态库、账号运行数据、隔离运行目录（含第三方临时检出）、凭据文件、缓存及生成的压缩包。被排除的数据仍保留在本机；克隆仓库不会恢复既有账号、审批或发送状态。

历史资料中的本机绝对路径仅用于追溯旧运行；新运行请使用自己的路径。第三方来源材料保留原有 LICENSE、NOTICE 与来源标记。
