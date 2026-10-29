# LazyMind Outreach Agent

这是一个独立、可复用的 Outreach Skill。它把 Scout V2 的技术机会与官方联系渠道结合起来，但使用自己的 SQLite 状态库；默认只做发现、筛选、草稿和模拟。V1.1 新增网易个人 163 邮箱的受控 SMTP/IMAP 接口，未完成两阶段自测和精确批次审批时不会外发。

## 目录

```text
lazymind-outreach-agent/
├── SKILL.md
├── ARCHITECTURE.md
├── OUTREACH_POLICY.md
├── FIRST_RUN_REPORT.md
├── LEADS.csv
├── DRAFTS.md
├── OUTREACH_TRACKER.csv
├── TEST_REPORT.md
├── NETEASE_SETUP.md
├── PROVIDER_INTEGRATION_TEST.md
├── UPDATED_LEADS.csv
├── UPDATED_DRAFTS.md
├── SEND_READINESS_REPORT.md
├── references/
├── scripts/
├── tests/
└── data/outreach.sqlite3
```

## 首次运行

要求 Python 3.9+，运行依赖仅为标准库。

```bash
# 从仓库根目录进入组件目录
cd lazymind-outreach-agent
python3 scripts/first_run.py \
  --db data/outreach.sqlite3 \
  --scout-db ../first-run/isolated-data/opportunities.sqlite3 \
  --candidates references/first-run-candidates.json \
  --output-dir .
python3 scripts/v11_update.py \
  --db data/outreach.sqlite3 \
  --scout-db ../first-run/isolated-data/opportunities.sqlite3 \
  --output-dir .
python3 -m unittest discover -s tests -v
```

首轮脚本会校验 Scout `user_version=2`，使用 SQLite `mode=ro&immutable=1` 和 `query_only=ON` 导入机会及历史，并比较导入前后 Scout 文件 SHA-256。随后 V1.1 更新脚本降级过期渠道、记录替代入口并重评合作草稿；它同样只比较 Scout 文件哈希，不打开写连接。Outreach 数据库不共享 Scout 的事务、表或迁移。

以上命令用于复现已有首轮数据，要求本机已存在对应 Scout 数据库；该运行数据库不纳入 Git。新克隆请先按[根目录说明](../README.md#快速开始)初始化空数据库，再使用自己的 Scout 数据路径。`first_run.py` 和 `v11_update.py` 会更新输出目录内的报告，建议把新报告写入单独的本地目录。

## 审核与模拟发送

先通过 CLI 或代码创建小批次，再查看完整清单。审批是批次级操作，但每一项分别绑定内容哈希。

```bash
python3 scripts/outreach.py --db data/outreach.sqlite3 review --batch-id BATCH_ID
python3 scripts/outreach.py --db data/outreach.sqlite3 approve --batch-id BATCH_ID --approved-by REVIEWER
python3 scripts/outreach.py --db data/outreach.sqlite3 simulate-send --batch-id BATCH_ID
```

审批绑定发件账号、收件人、主题和正文。V1.1 只允许完成 [网易两阶段配置](NETEASE_SETUP.md) 的个人 `@163.com` 账号进入真实接口；Gmail 和企业邮箱仍不可执行。授权码不写入代码、SQLite、命令参数、清单或日志。

## 网易个人 163 账号自测

已有账号遇到“阶段一成功、阶段二 535”的情况，直接双击项目中的
`修复163邮箱.command`。它只询问一次隐藏授权码，自动验证并修复 Keychain，
用同一份已验证凭据继续自发自收检查。详细说明见 [NETEASE_SETUP.md](NETEASE_SETUP.md)。

```bash
python3 scripts/netease_cli.py --db data/outreach.sqlite3 probe
python3 scripts/netease_cli.py --db data/outreach.sqlite3 self-test
```

第一条命令只验证 SMTP SSL 465 和 IMAP SSL 993，不发送邮件；第二条命令只允许向已认证账号自身发送一封中文 MIME 自测。两条命令均在终端隐藏读取客户端授权码，并优先使用 macOS Keychain。企业邮箱域名会被拒绝，必须单独核验参数。

## 批量拟稿与低频发送

草稿与官网/GitHub 官方渠道查证由 Agent 按证据完成；脚本负责版本、审批、发送、节流和结果记录，并未部署独立 LLM 生成器或个人邮箱采集器。中英文采用证据化 `zh-CN` / `en`，未知则停止起草。垂直媒体走 `editorial_pitch`，不自动注册或登录投稿平台。

真实批次最多 10 封；默认每账号间隔 300 秒，跨批次和重启保留冷却。当前账号已设置为 300 秒。需要更改时可使用：

```bash
python3 scripts/netease_cli.py --db data/outreach.sqlite3 --account lazymind_agent@163.com configure-pacing --interval-seconds 600
```

该命令只配置本地节奏，不代表批准或发送。具体批次获批后，`send-batch --wait-for-interval` 可在本机分段等待并逐封重查门禁；异常停止。本地节流不代表网易额度或送达保证。完整说明见 [当前能力与发送节奏](references/operating-capabilities.md)。

## 明确不做

- 不抓取 GitHub commit 邮箱、私人联系方式或个人资料。
- 不把公开邮箱解释成营销许可。
- 不对无回复对象自动连续催促。
- 不把模拟结果、邮件投递、简单回复或试用分别混成同一个“转化”指标。
- 不直接改 Scout 数据库；需要回传时只生成显式 outcome JSON，由 Scout 侧另行审核导入。
