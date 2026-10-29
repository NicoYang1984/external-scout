# 当前能力与发送节奏

这是 Agent 驱动、代码负责执行约束的 Skill，不是已经部署的全天候采集/生成/群发服务。

| 能力 | 已有实现 | 边界 |
|---|---|---|
| 批量拟稿 | Agent 根据每条证据与 Campaign 撰写 zh-CN/en 草稿；SQLite 保存版本与内容哈希 | 脚本没有独立 LLM 调用或后台自动生成器；首轮脚本导入的是已准备的草稿，不是运行时自动写作 |
| 小批次发送 | 最多 10 封的批次清单、一次批次审批、个人 163 SMTP、幂等与回复接口 | 当前具体批次必须获明确批准；SMTP 接受不是最终投递成功 |
| 交流语言 | `zh-CN`、`en`、`language_unknown`；草稿语言必须匹配线索 | Agent 依据官网、README、官方联系页、偏好或正式往来判断；没有独立自动语言检测模块，不推测国籍；未知时不得绕过线索语言直接起草 |
| 垂直媒体 | `editorial_pitch` 可用于技术、行业等垂直媒体；按读者问题、征稿范围与规则定制 | 没有自动登录投稿平台、自动注册或通用表单提交器；禁止 AI 投稿的渠道停止 AI 起草 |
| GitHub 项目渠道 | Scout 只读导入后，Agent 查官方组织页、仓库 README/CONTRIBUTING 和项目官网的合作入口 | 没有全网/个人邮箱采集器；不取 commit 邮箱、私人联系方式；公开邮箱必须另有用途依据 |
| 发送节奏 | 默认 300 秒/次，SQLite 持久化，按账号跨批次共享，原子占位 | 属于本地节流，不代表网易额度或送达承诺；服务商拒绝和不确定结果停止本轮，不能靠修改节奏绕过限制 |

## 可配置发送间隔

设置或查看都不会读取授权码、访问邮箱或发送邮件：

```bash
python3 scripts/netease_cli.py --db data/outreach.sqlite3 --account lazymind_agent@163.com configure-pacing --interval-seconds 300
python3 scripts/netease_cli.py --db data/outreach.sqlite3 --account lazymind_agent@163.com show-pacing
```

可设置 60–86400 秒；默认 300 秒。调短配置不会缩短已经生效的冷却；调长会延长当前冷却。此范围是项目防误操作限制，不是网易官方限额。批次上限保持 10，实际每批数量可更少。

底层 `send_batch` 不阻塞等待：尚未到时间时返回 `deferred_rate_limit`、`retry_after_seconds` 和 `next_allowed_at`；不会创建假发送记录或消耗新发送名额。模拟发送不消耗真实冷却。提交前真实尝试会保留冷却，即使登录或网络失败，也不能马上连续重试。

只有已明确批准的具体批次才可以使用如下执行方式：

```bash
python3 scripts/netease_cli.py --db data/outreach.sqlite3 --account lazymind_agent@163.com send-batch --batch-id APPROVED_BATCH_ID --wait-for-interval
```

`--wait-for-interval` 在本次本机进程中分段等待，确认一次后按节奏继续同批次；每次提交前重新读取审批、账号、内容、渠道和排除状态。Ctrl-C 可停止，关闭进程不会在后台继续执行，也没有新建定时任务。恢复同批次时跳过已接受或不确定的请求，不重复投递。

不加该参数时遇到冷却即返回，CLI 退出码为 3（待发送，不是投递失败）；异常/不确定返回 2。本命令不生成审批。原批准一旦失效，等待不会使它重新生效。
