#!/bin/zsh
# Local owner-only repair launcher; contains no credentials.
cd -- "${0:A:h}" || exit 1
print '将验证 lazymind_agent@163.com，修复 Keychain，并自发自收一封测试邮件。'
print '授权码仅在隐藏输入提示处输入；无需删除 Keychain 或再次生成授权码。'
python3 scripts/netease_cli.py --db data/outreach.sqlite3 --account lazymind_agent@163.com --report-dir . repair
repair_status=$?
if [[ $repair_status -eq 0 ]]; then
  print '自测完成。报告已写入 PROVIDER_INTEGRATION_TEST.md 和 SEND_READINESS_REPORT.md。'
else
  print '本次尚未全部通过，具体结果已保存到报告。不要重新发送已接受或状态不确定的邮件。'
fi
read -r '?按回车关闭窗口。'
exit $repair_status
