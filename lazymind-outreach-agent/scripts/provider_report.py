"""Render non-secret provider checks without changing campaign or Scout state."""
import json
from pathlib import Path

from outreach_core import utcnow


def render_provider_reports(store, output_dir: Path):
    checks = list(store.conn.execute(
        "SELECT phase,status,details_json,checked_at FROM provider_checks ORDER BY id"
    ))
    accounts = list(store.conn.execute(
        "SELECT account,authorized,live_enabled FROM sender_accounts ORDER BY account"
    ))
    real_count = store.conn.execute("SELECT COUNT(*) FROM send_requests WHERE mode='real'").fetchone()[0]
    active_approvals = store.conn.execute("SELECT COUNT(*) FROM approvals WHERE revoked_at IS NULL").fetchone()[0]
    lines = [
        "# Provider Integration Test — NetEase Personal 163", "", f"Updated: {utcnow()}", "",
        "## Verified engineering results", "",
        "- Original V1 regression tests retained; see TEST_REPORT.md for the current test count.",
        "- Native macOS Keychain create/update/read-back/delete tested successfully with a unique temporary synthetic item. It was removed after the test.",
        "- Credential repair reads a fresh authorization code in a hidden local prompt, validates it, saves it through native SecItem calls, and verifies read-back equality.",
        "- The same in-memory adapter is reused across phase 1 and phase 2. Storage failure is reported honestly as memory_only.",
        "- SMTP 535 is recorded as authentication failure before message submission.",
        "- Accepted/uncertain self-tests are reconciled by Message-ID when rerun, never blindly resent.", "",
        "- IMAP ID (RFC 2971) identifies this client truthfully before reading; the connection probe also checks read-only INBOX access.",
        "- Sent discovery preserves the server-declared quoted/modified-UTF-7 mailbox name; no guessed Unicode mailbox names.", "",
        "## Real-account checks", "",
        "| Time (UTC) | Phase | Result | SMTP result | Diagnostic |", "|---|---|---|---|---|",
    ]
    for row in checks:
        data = json.loads(row["details_json"])
        # Use only controlled fields; never render arbitrary exception text or credentials.
        diagnostic = data.get("error_type") or data.get("imap_error_type") or ""
        if data.get("smtp_details", {}).get("smtp_code"):
            diagnostic = f"SMTP {data['smtp_details']['smtp_code']} / {data['smtp_details'].get('stage', '')}"
        elif "535" in (data.get("error") or ""):
            diagnostic = "SMTP 535 (legacy diagnostic)"
        lines.append(f"| {row['checked_at']} | {row['phase']} | {row['status']} | {data.get('smtp_result', '')} | {diagnostic} |")
    if not checks:
        lines.append("| — | — | Not run | — | — |")
    owner_checks = [row for row in checks if row["phase"] == "phase2_owner_self_test"]
    if owner_checks:
        latest = owner_checks[-1]
        data = json.loads(latest["details_json"])
        lines += [
            "", "## Latest owner-only test evidence", "",
            f"- Account / recipient: `{data.get('recipient', '')}`.",
            f"- Message-ID: `{data.get('rfc_message_id', '')}`.",
            f"- Check result: `{latest['status']}`; SMTP submission result: `{data.get('smtp_result', '')}`.",
            f"- INBOX found: {data.get('inbox_found', False)}; Sent found: {data.get('sent_folder_found', False)}.",
            f"- Owner INBOX receipt verified independently of SMTP: {data.get('owner_inbox_receipt_verified', False)}.",
            f"- Reconciled existing message without resend: {data.get('reconciled_without_resend', False)}.",
        ]
        for key in ("chinese_subject", "chinese_body", "link", "utf8_plain_text", "exact_message_identity"):
            lines.append(f"- MIME/header check `{key}`: {data.get('mime_checks', {}).get(key, False)}.")
        lines += ["", "Only the exact self-test message was read for these checks. No synthetic Sent copy was appended."]
    reply_checks = [row for row in checks if row["phase"] == "related_reply_scan"]
    if reply_checks:
        data = json.loads(reply_checks[-1]["details_json"])
        lines += ["", "## Related reply scan", "",
                  f"- Authorized real-outreach threads available: {data.get('threads_checked', 0)}.",
                  f"- Replies recorded: {len(data.get('replies_recorded', []))}.",
                  "- No outreach has been sent; live external-reply classification is therefore not claimed. Correlation/classification is covered by offline regression tests.",
                  "- No follow-up was sent."]
    owner_reply_checks = [row for row in checks if row["phase"] == "owner_reply_read"]
    if owner_reply_checks:
        data = json.loads(owner_reply_checks[-1]["details_json"])
        lines += ["", f"Owner self-test reply lookup: {owner_reply_checks[-1]['status']}; "
                  f"matching real replies: {data.get('matching_reply_count', 0)}. "
                  "This ran real IMAP In-Reply-To/References searches for the self-test Message-ID, without generating a reply."]
    lines += [
        "", "SMTP acceptance is not final delivery. A passing owner self-test requires the exact Message-ID in both INBOX and Sent, with Chinese subject/body and link checks passing.",
        "", "The earlier 535 failures are retained as historical results. They are not replaced by a claim of success.", "",
        f"Outreach real send requests: {real_count}. Active batch approvals: {active_approvals}.", "",
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "PROVIDER_INTEGRATION_TEST.md").write_text("\n".join(lines), encoding="utf-8")
    ready = any(row["authorized"] and row["live_enabled"] for row in accounts)
    readiness = [
        "# SEND READINESS REPORT", "", f"Updated: {utcnow()}", "",
        f"- Provider owner self-test complete: {'yes' if ready else 'no'}.",
        f"- Active exact-batch approvals: {active_approvals}.",
        f"- Outreach real send requests: {real_count}.",
        "- V1 batch remains invalidated; no third-party batch was approved by this repair workflow.", "",
        "## Channel review", "",
        "- OpenEng: research inquiry draft remains pending sender identity review and explicit batch approval.",
        "- Composio: identity_hold; company work-email/user-journey requirements remain unresolved.",
        "- Opensource.com: stale_channel; legacy draft excluded.",
        "- OpenSource.net: membership-gated form; membership unverified.", "",
        ("The owner self-test is complete; no repeat repair or resend is needed." if ready else
         "The owner self-test is not complete; accepted or uncertain tests must be reconciled without resending."),
        "A passing provider test does not approve third-party outreach.", "",
    ]
    readiness += ["## Sending cadence", ""]
    for account in accounts:
        pacing = store.get_send_pacing(account["account"])
        readiness += [
            f"- `{account['account']}`: at most one real batch attempt per {pacing['min_interval_seconds']} seconds.",
            f"- Next eligible slot: {pacing['next_allowed_at'] or 'no real-batch slot reserved yet'}.",
        ]
    readiness += ["- Persisted per account across batches/restarts. Exact approval and suppression checks still apply.",
                  "- Local cooldown is not a provider quota or delivery guarantee.", ""]
    (output_dir / "SEND_READINESS_REPORT.md").write_text("\n".join(readiness), encoding="utf-8")
