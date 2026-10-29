# 第一批真实发件结果

批次：`review-2026-10-28-small-01`  
批次 ID：`44a1d850-84e5-4503-b0f2-58f356947a7d`  
发件账号：`lazymind_agent@163.com`  
最终核验：2026-10-28 20:29:43（北京时间）

## 结果

**3/3 封已由网易 SMTP 接受，3/3 封已在真实 Sent 文件夹核验。** 实际提交各一次，无重发、无模拟发送、无新增收件人。两次提交间隔分别为 301 秒、301 秒，满足至少 300 秒要求。

| 对象 | 收件人 | SMTP 接受记录时间（北京时间） | SMTP 结果 | 已发送副本 |
| --- | --- | --- | --- | --- |
| AI中国网 | editor@cnaiplus.com | 2026-10-28 17:55:12 | smtp_accepted | 已核验 |
| OpenEng | hello@openeng.ai | 2026-10-28 18:00:13 | smtp_accepted | 已核验 |
| 汇智网 | support@hubwiz.com | 2026-10-28 18:05:14 | smtp_accepted | 已核验 |

请求仍保留 `delivery_unknown`：这表示**尚未确认对方最终收件箱投递**，不是本次 SMTP 提交失败。SMTP 接受和本账号 Sent 副本都不能证明对方已经收到或阅读，因此不计为合作、用户或试用转化。已接受请求 `safe_to_retry=0`，不得自动重发。

## 精确内容与审批

- 用户原话：批准批次 review-2026-10-28-small-01。
- [审批凭据](APPROVAL_RECEIPT.json)保存三个收件人对应的有效审批及指纹。
- [冻结审核稿](REVIEW.md)与[机器清单](review-checklist.json)保持原样；其中“待审、未发送”是生成时的历史状态，以本结果报告和 SQLite 当前状态为准。
- 真正提交前再次检查用途许可、排除记录、组织级历史联系、授权账号和精确内容。
- 三封收件人、主题、正文与批准版本一致。IMAP 对完整正文进行了比对，仅忽略传输添加的末尾换行；发件人、收件人、主题、Message-ID、UTF-8 纯文本 MIME 均通过。
- 全程使用 macOS Keychain 读取已有客户端授权码至进程内存，没有把凭据写入命令、报告或数据库。

## 真实邮件标识

### AI中国网

- 收件人：`editor@cnaiplus.com`
- 主题：案例选题｜Agent 做出了简报，为什么还不能算业务任务完成？
- RFC Message-ID：`<179318131228.14700.15358129563878990245@163.com>`
- 内容 SHA-256：`0e640514dc51f644e050921eee0314a2823a4b7eaf1ba029c117529c3631ef9f`
- 状态：SMTP 接受、Sent 副本已核验、最终投递未知。

### OpenEng

- 收件人：`hello@openeng.ai`
- 主题：Research collaboration: when a recovered agent session still leaves a failed task
- RFC Message-ID：`<179318161287.14700.5996488933747002609@163.com>`
- 内容 SHA-256：`631d5873e8fd2236944c5db640a62f55fe66f1ca508c161445661625c57a12b8`
- 状态：SMTP 接受、Sent 副本已核验、最终投递未知。

### 汇智网

- 收件人：`support@hubwiz.com`
- 主题：选题投稿｜报告生成了，Agent 就算跑完了吗？一次 Skill 工作流实测
- RFC Message-ID：`<179318191343.14700.542310745062646008@163.com>`
- 内容 SHA-256：`1fec13608d69173b8416a8e572908908ad44c052579fff5d4811a2c079ef675f`
- 状态：SMTP 接受、Sent 副本已核验、最终投递未知。


## 回复检查

截至 2026-10-28 20:29:43，已对三个线程做一次成功的相关回复查询，匹配回复数为 0。只读取引用本批 Message-ID 且发件地址符合预期的邮件；未扫描无关邮件。此结果不能排除来自其他地址的回复或系统退信，不表述为“邮箱完全没有任何回复”。

首次查询遇到 Keychain 内部错误（OSStatus -60008），一次只读重试后恢复。该错误不影响已经完成的发送，没有重试 SMTP。未自动回复、未催促，未配置后台持续监控。

## 验证与留痕

- 回归测试：45/45 通过。
- 真实尝试：3；SMTP 接受：3；发送错误：0；重复尝试：0；新增跟进邮件：0。
- 全部正文和审批指纹未变；历史线索许可未提升。
- Scout 数据库字节哈希保持不变：`81cf0053df14cb1e182adbd322c2ea4a8b9285b50f8b24a432eda4e406b49d3b`。
- 人工审核耗时未测量，不把系统默认值 0 当成实际审核耗时。
- [完整机器可读发送回执](SEND_RECEIPTS.json)保存请求、尝试、审批、IMAP 核验和回复查询结果。

## 渠道与执行边界

本次仅回应[汇智网的官方投稿邀请](https://www.hubwiz.com/blog/contribute/)、[AI中国网的案例投稿入口](https://www.cnaiplus.com/about/contribute/)及[OpenEng 的研究合作邀请](https://openeng.ai/contact)。用途依据来自这些明确邀请，不是邮箱公开本身。

已参考[网易反垃圾邮件政策说明](https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac2f946d58b326f7f3f)。本地 300 秒间隔不是网易额度承诺或完整法律合规认证；本批未遇到服务商拒绝，也未绕过限额或改变服务器参数。
