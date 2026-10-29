# SEND READINESS REPORT

Updated: 2026-10-28T12:29:43+00:00

- Provider owner self-test complete: yes.
- Active exact-batch approval records: 3 for `review-2026-10-28-small-01`, explicitly approved by the account owner in chat.
- Outreach real send requests: 3; attempts: 3; SMTP accepted: 3; final delivery unknown: 3.
- All three real Sent copies passed exact header, complete decoded body and UTF-8 MIME checks. No repeat submissions.
- The original V1 batch remains invalidated. Approval of this new batch does not authorize any other batch or a repeat send.
- Full results and Message-IDs: [first approved batch report](reviews/2026-10-28-small-batch/SEND_REPORT.md).

## Channel review

- OpenEng: the approved research inquiry was SMTP-accepted and its Sent copy verified; final delivery is unknown.
- 汇智网 and AI中国网: approved editorial inquiries were SMTP-accepted and their Sent copies verified; final delivery is unknown.
- Composio: identity_hold; company work-email/user-journey requirements remain unresolved.
- Opensource.com: stale_channel; legacy draft excluded.
- OpenSource.net: membership-gated form; membership unverified.

The owner self-test is complete; no repeat repair or resend is needed.
A passing provider test does not approve third-party outreach.

## Sending cadence

- `lazymind_agent@163.com`: at most one real batch attempt per 300 seconds.
- Last batch slot: 2026-10-28T10:05:13.431881+00:00. Recorded cooldown ended at 2026-10-28T10:10:13.431881+00:00; this does not authorize new mail.
- Actual recorded inter-attempt intervals: 301 seconds and 301 seconds.
- Persisted per account across batches/restarts. Exact approval and suppression checks still apply.
- Local cooldown is not a provider quota or delivery guarantee.

## Reply check

- A read-only check of the three recorded Message-ID threads completed at 2026-10-28T12:29:43+00:00; no matching expected-sender replies were found.
- This restricted query does not rule out bounces or replies from other addresses. No automatic follow-up was sent and no background monitoring was created.
- An initial Keychain read error (-60008) resolved on one read-only retry; SMTP was not retried.
- Human review duration was not measured. Existing approval-record duration defaults must not be interpreted as measured zero-time review.
