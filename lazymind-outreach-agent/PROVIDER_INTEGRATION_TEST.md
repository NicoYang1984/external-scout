# Provider Integration Test — NetEase Personal 163

Updated: 2026-10-28T09:21:28+00:00

## Verified engineering results

- Original V1 regression tests retained; see TEST_REPORT.md for the current test count.
- Native macOS Keychain create/update/read-back/delete tested successfully with a unique temporary synthetic item. It was removed after the test.
- Credential repair reads a fresh authorization code in a hidden local prompt, validates it, saves it through native SecItem calls, and verifies read-back equality.
- The same in-memory adapter is reused across phase 1 and phase 2. Storage failure is reported honestly as memory_only.
- SMTP 535 is recorded as authentication failure before message submission.
- Accepted/uncertain self-tests are reconciled by Message-ID when rerun, never blindly resent.

- IMAP ID (RFC 2971) identifies this client truthfully before reading; the connection probe also checks read-only INBOX access.
- Sent discovery preserves the server-declared quoted/modified-UTF-7 mailbox name; no guessed Unicode mailbox names.

## Real-account checks

| Time (UTC) | Phase | Result | SMTP result | Diagnostic |
|---|---|---|---|---|
| 2026-10-28T07:29:48+00:00 | phase1_connection | passed |  |  |
| 2026-10-28T07:30:12+00:00 | phase2_owner_self_test | failed | failed | SMTP 535 (legacy diagnostic) |
| 2026-10-28T07:39:22+00:00 | phase1_connection | passed |  |  |
| 2026-10-28T07:39:37+00:00 | phase2_owner_self_test | failed | failed | SMTP 535 (legacy diagnostic) |
| 2026-10-28T08:48:44+00:00 | phase1_connection | passed |  |  |
| 2026-10-28T09:00:41+00:00 | phase2_owner_self_test | passed | smtp_accepted |  |
| 2026-10-28T09:00:34+00:00 | phase2_imap_diagnostic | resolved |  |  |
| 2026-10-28T09:00:40+00:00 | phase1_connection | passed |  |  |
| 2026-10-28T09:00:46+00:00 | related_reply_scan | completed |  |  |
| 2026-10-28T09:02:41+00:00 | owner_reply_read | passed |  |  |

## Latest owner-only test evidence

- Account / recipient: `lazymind_agent@163.com`.
- Message-ID: `<179317773964.98404.4115800709899450906@163.com>`.
- Check result: `passed`; SMTP submission result: `smtp_accepted`.
- INBOX found: True; Sent found: True.
- Owner INBOX receipt verified independently of SMTP: True.
- Reconciled existing message without resend: True.
- MIME/header check `chinese_subject`: True.
- MIME/header check `chinese_body`: True.
- MIME/header check `link`: True.
- MIME/header check `utf8_plain_text`: True.
- MIME/header check `exact_message_identity`: True.

Only the exact self-test message was read for these checks. No synthetic Sent copy was appended.

## Related reply scan

- Authorized real-outreach threads available: 0.
- Replies recorded: 0.
- No outreach has been sent; live external-reply classification is therefore not claimed. Correlation/classification is covered by offline regression tests.
- No follow-up was sent.

Owner self-test reply lookup: passed; matching real replies: 0. This ran real IMAP In-Reply-To/References searches for the self-test Message-ID, without generating a reply.

SMTP acceptance is not final delivery. A passing owner self-test requires the exact Message-ID in both INBOX and Sent, with Chinese subject/body and link checks passing.

The earlier 535 failures are retained as historical results. They are not replaced by a claim of success.

Outreach real send requests: 0. Active batch approvals: 0.
