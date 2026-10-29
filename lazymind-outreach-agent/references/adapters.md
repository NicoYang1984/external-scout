# Mail adapters

`MailAdapter` 定义 `create_draft`, `send`, `list_sent`, `read_replies`。`MockMailAdapter` 返回 `simulated`，不能推进真实发送状态。

`NetEase163MailAdapter` 是 V1.1 唯一可进入真实分支的实现，只适用于精确的个人 `@163.com` 地址：SMTP SSL `smtp.163.com:465`，IMAP SSL `imap.163.com:993`。它使用客户端授权码而非网页登录密码，并在连接前拒绝企业或其他域名。阶段一登录两台服务器、声明真实 IMAP ID 并验证只读收件箱访问，不发送邮件；阶段二只允许账号所有者自发自收。授权码从 macOS Keychain 或隐藏终端输入进入内存，不进入参数、SQLite、清单或日志。

SMTP 无拒绝返回时记录 `smtp_accepted`，但请求状态仍是 `delivery_unknown`；网络在邮件提交阶段断开同样禁止自动重试。只有明确的提交前失败才标记为安全重试。回复读取同时匹配 `In-Reply-To`/`References` 和预期发件地址，不扫描或分析无关邮件。

`GmailApiAdapter` 预留 Gmail API：将来由宿主传入 OAuth token provider，使用最小 scopes 创建草稿、读取指定 thread/query、查询 sent 和发送已审批 MIME。实现不得打印 token，不得在数据库保存 refresh token，也不得扩大到整个邮箱的无关内容。

`EnterpriseMailAdapter` 供公司批准的 Microsoft Graph、SMTP relay 或其他服务实现相同契约。网易企业邮箱也属于该路径，不得复用个人邮箱假设；必须先验证实际域名、服务器、端口、授权方式和公司政策。

回复读取必须限制到本系统真实 Message ID、thread ID 或专用标签。分类只产生状态建议；`prepare_follow_up_draft()` 只为兴趣或问题回复生成 `review_pending` 草稿，技术问题和承诺类答复不自动发送。
