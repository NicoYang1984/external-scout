# NetEase 163 Personal Mail Setup

This integration is restricted to personal addresses whose exact domain is `@163.com`.
It uses SMTP over implicit TLS on `smtp.163.com:465` and IMAP over implicit TLS on
`imap.163.com:993`. The credential must be the mail client's authorization code,
not the web-login password.

## Before running

1. In 163 Mail settings, enable the required SMTP/IMAP client access and create a
   client authorization code.
2. Do not put that code in a command, environment file, SQLite database, source
   file, issue, screenshot, or chat.
3. Run the commands in an interactive local terminal. The code prompt uses hidden
   input. After a successful connection, the CLI can store it in macOS Keychain
   under service `lazymind-outreach-agent:netease163`.
4. If the actual account is a NetEase enterprise mailbox, stop. Do not use this
   adapter or guess from the personal settings. Validate the domain, SMTP/IMAP
   hosts, ports, authorization method, and company policy separately.

The implementation accepts the authorization code only in memory. Keychain reads
and writes use native macOS SecItem APIs and every write must pass an in-memory
read-back equality check. No credential-bearing subprocess is launched. SQLite
stores only the account, provider name, non-secret verification timestamps, and gate state.

## Repair an existing 535 / Keychain problem

Double-click `修复163邮箱.command`, or run this command from any directory:

```bash
/Users/liangziyang/external-scout/lazymind-outreach-agent/修复163邮箱.command
```

This local launcher already selects `lazymind_agent@163.com`. Enter the current
client authorization code once in the hidden prompt. It ignores the old stored
value, validates SMTP and IMAP, replaces the stored value through native APIs, and
verifies equality before reporting that it is saved. There is no need to delete
the old item manually. macOS may display its own Keychain access/unlock dialog;
that is distinct from the client authorization code prompt.

The one-message owner test still requires typing
`SEND TEST TO lazymind_agent@163.com`. Both phases use the same already-validated
in-memory credential. If storage is unavailable, the workflow reports
`memory_only` and can complete the current self-test without claiming that a
credential was saved. Results automatically update `PROVIDER_INTEGRATION_TEST.md`
and `SEND_READINESS_REPORT.md`.

For another personal 163 account:

```bash
python3 scripts/netease_cli.py --db data/outreach.sqlite3 --account YOUR_ACCOUNT@163.com --report-dir . repair
```

If the previous self-test was accepted or its outcome is uncertain, rerunning
only looks up the recorded Message-ID. It does not send a second test message.

## Phase 1 — connection and account authorization

```bash
cd /Users/liangziyang/external-scout/lazymind-outreach-agent
python3 scripts/netease_cli.py --db data/outreach.sqlite3 probe
```

The CLI uses the saved Keychain credential when available; otherwise it asks for
the personal 163 address and authorization code securely. It logs in to SMTP and
IMAP, sends truthful RFC 2971 client identification when advertised by the server,
and verifies read-only INBOX access before closing both sessions. It does not
construct or submit a message. A successful result records `phase1_connection=passed` but keeps
`live_enabled=0`.

To run phase 1 and then, only after the separate exact confirmation, phase 2 in a
single secure terminal session, use:

```bash
python3 scripts/netease_cli.py --db data/outreach.sqlite3 wizard
```

## Phase 2 — one owner-only message

```bash
python3 scripts/netease_cli.py --db data/outreach.sqlite3 self-test
```

V1.1 deliberately requires the test recipient to equal the authenticated sender.
The user must type an exact confirmation phrase. The CLI sends one message with a
Chinese subject, Chinese plain-text body, an HTTPS link, and UTF-8 MIME encoding,
then searches both INBOX and the server-declared Sent folder by the exact RFC
Message-ID. It verifies the decoded Chinese text/link, UTF-8 plain-text MIME,
exact Message-ID and matching sender/recipient in both copies. Only when both
copies and all MIME/header checks pass does it set
`live_enabled=1`.

The attempt and its Message-ID are recorded before SMTP submission. Acceptance is
persisted before IMAP checks, so a later read failure or process interruption
cannot turn a repeat run into an unnoticed duplicate send.

An SMTP acceptance is recorded as `smtp_accepted`; it is not proof of final
delivery. If a connection ends during SMTP submission, the result is
`delivery_unknown` and the system will not retry automatically.

## Resolved IMAP compatibility issue (2026-10-28)

The real account authenticated successfully but returned
`EXAMINE Unsafe Login` when the old adapter selected INBOX without declaring its
identity. All IMAP paths now send RFC 2971 `ID` with the actual application name
and version before selecting a mailbox. No other email client is impersonated.
The probe now tests mailbox access, not just LOGIN success.

Sent-folder discovery preserves the quoted modified-UTF-7 name returned by
`LIST` (this account returns `"&XfJT0ZAB-"`). It no longer guesses a raw Chinese
folder name. A failed mailbox selection is reported as an error, not an empty
mailbox. The `self-test` command exits nonzero if checks remain incomplete.

The owner-only live test passed after read-only reconciliation of the original
accepted Message-ID. There was no repeat SMTP submission and no artificial Sent
copy. See `PROVIDER_INTEGRATION_TEST.md` for the exact evidence. An empty answer to
the original `SEND TEST TO ...` prompt intentionally sends nothing; it is not an
authentication failure.

## Phase 3 — a reviewed third-party batch

Real batches default to a persisted, account-wide 300-second minimum interval.
Use `configure-pacing --interval-seconds 300` or `show-pacing` after the normal
global account/database options to configure or inspect it. These commands do
not read credentials or send mail. See [sending cadence](references/operating-capabilities.md)
for the optional `--wait-for-interval` mode, interruption, and exit codes.

Phase 2 does not authorize any outreach. A separate batch must contain the exact
sender, recipient, subject, body, evidence, permission basis, and risk checks. The
approval fingerprint is:

```text
SHA-256(lower(sender) + "\n" + lower(recipient) + "\n" + subject + "\n" + body)
```

The user must explicitly approve that specific batch. Changing any fingerprint
input invalidates the prior approval. Suppression, duplicate-contact, stale-channel,
provider, and permission checks run again immediately before submission.

After an exact batch has separately been reviewed and approved, the only execution
entry point is:

```bash
python3 scripts/netease_cli.py --db data/outreach.sqlite3 send-batch --batch-id APPROVED_BATCH_ID
```

It requires a second exact terminal confirmation and re-runs all gates. Do not run
this command for the current V1 batch: it is invalidated and no V1.1 batch has been
approved. Nothing in the phase 1 or phase 2 commands approves a third-party batch.

After an approved real send exists, correlated replies can be read without sending
anything:

```bash
python3 scripts/netease_cli.py --db data/outreach.sqlite3 check-replies
```

Only messages whose `In-Reply-To` or `References` matches a recorded real RFC
Message-ID and whose sender matches the original recipient are considered. Interest
or questions may create a review need, but this command never sends a follow-up.

## Credential removal

To remove the stored authorization code without exposing it:

```bash
security delete-generic-password -s lazymind-outreach-agent:netease163 -a YOUR_ACCOUNT@163.com
```

Then revoke the client authorization code in 163 Mail settings. Deleting a
Keychain item does not change historical non-secret verification records; those
records must not be treated as current authorization after revocation.

## References

- [RFC 2971 — IMAP4 ID extension](https://www.rfc-editor.org/info/rfc2971/) defines
  the implementation-identification handshake. The observed NetEase rejection
  and successful handshake were verified directly against this authorized account.
- [Python imaplib](https://docs.python.org/3/library/imaplib.html) documents read-only
  mailbox selection and extension commands.
- NetEase personal-mail client settings are also documented in the
  [Huawei Cloud WeLink mailbox guide](https://support.huaweicloud.com/faq-welink/faq-welink.pdf):
  `smtp.163.com:465` and `imap.163.com:993` with SSL/TLS.
- The project policy and exact runtime gates are defined in
  `OUTREACH_POLICY.md`, `scripts/netease163.py`, and `scripts/outreach_core.py`.
