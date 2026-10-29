#!/usr/bin/env python3
"""Apply evidence-backed V1.1 channel corrections and render updated artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from outreach_core import OutreachStore, sha256_text, stable_json, utcnow


OPENENG_BODY = """Your research-collaboration page asks a first note to state the current stack, target outcome, data boundaries, and timeline: https://openeng.ai/contact. Our current stack is LazyMind's open-source Codex Skill/workflow surface with local workflow state and human review; the specific issue we can evidence is that session-level completion can diverge from step, artifact, or external-task state.

We would like to discuss a bounded governed-execution study, not announce an integration. The measurable target would be one fixed public input, one injected recoverable failure, and a complete before/after record in which every session, step, artifact, and external-task state is mutually consistent after at most one authorized retry. The study would fail if either system hides a failed transition or requires credential transfer.

LazyMind can provide the implementation at https://github.com/LazyAGI/LazyMind and the limited prior evaluation at https://github.com/NicoYang1984/LazyMind/blob/fde2e68437caffa8dc6d706271dabc6073183938/examples/competitive-brief-skill2workflow/EVALUATION.md. That run is not a success claim: autonomous execution stopped at 2/5, and assisted recovery did not change the original external task's failed state. We have not tested OpenEng compatibility and do not imply OpenEng endorsement.

I am writing on behalf of the LazyMind project. We would use public or synthetic data only, provide no credentials or production data, and propose a two-week evidence window after both sides accept a one-page test plan. If this is relevant to your agentic-systems and governed-execution research route, would reviewing that plan be an appropriate next step?"""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--scout-db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    before = file_sha256(args.scout_db)
    store = OutreachStore(args.db)
    store.init()
    now = utcnow()

    # The old channel is downgraded, never promoted or silently repurposed.
    store.conn.execute("""
      UPDATE leads SET permission_status='stale_channel',status='stale_channel',
      risk_notes=?,updated_at=? WHERE id='editorial-opensource-com'
    """, (
        "Opensource.com daily publication ceased in April 2023. The legacy email/page is retained only as history and must not be used.", now,
    ))
    store.conn.execute("""
      UPDATE drafts SET status='stale_channel',updated_at=?
      WHERE lead_id='editorial-opensource-com'
    """, (now,))
    store.conn.execute(
        "INSERT INTO events(lead_id,event_type,payload,occurred_at) VALUES(?,?,?,?)",
        ("editorial-opensource-com", "channel_marked_stale", stable_json({
            "evidence": "https://dev.opensource.com/about",
            "finding": "daily publication no longer supported as of April 2023",
        }), now),
    )

    # Replacement is membership-gated. Record it as not sendable; do not create a draft.
    store.upsert_lead({
        "id": "editorial-opensource-net", "organization": "OpenSource.net",
        "project_name": "OpenSource.net member post submission",
        "campaign_type": "editorial_pitch", "source_kind": "official_web",
        "source_url": "https://opensource.net/submit-a-post/",
        "pain_point": "The publication seeks ideas and articles about open source software, hardware, culture, and knowledge, but pitches are restricted to signed-in OSI individual members.",
        "evidence": [{
            "url": "https://opensource.net/submit-a-post/",
            "finding": "Submission requires sign-in and OSI individual membership; free or $50+ supporting membership options are described.",
        }],
        "contact_channel": "form", "contact_value": "https://opensource.net/submit-a-post/",
        "allowed_purpose": "member article pitch through the official form",
        "permission_status": "requires_membership", "permission_verified_at": "2026-10-28",
        "language": "en", "technical_fit": 7, "ecosystem_value": 7,
        "recommended_capability": "evidence-led article on observable agent workflow recovery",
        "case_links": [
            "https://github.com/LazyAGI/LazyMind",
            "https://github.com/NicoYang1984/LazyMind/blob/fde2e68437caffa8dc6d706271dabc6073183938/examples/competitive-brief-skill2workflow/EVALUATION.md",
        ],
        "risk_notes": "No membership or sign-in status has been verified. Do not submit or create an account automatically.",
        "status": "discovered",
    })

    # OpenEng remains a valid research route. Update the draft to match all four requested inputs.
    store.conn.execute("""
      UPDATE leads SET evidence_json=?,risk_notes=?,permission_verified_at='2026-10-28',
      status='review_pending',updated_at=? WHERE id='collab-openeng'
    """, (
        stable_json([{
            "url": "https://openeng.ai/contact",
            "finding": "Official page lists hello@openeng.ai for research collaboration and asks for current stack, measurable outcome, data boundaries, and timeline.",
        }]),
        "Current official route is suitable for a narrowly scoped research inquiry. No integration, result, or endorsement may be implied.", now,
    ))
    openeng = store.conn.execute(
        "SELECT id,content_hash FROM drafts WHERE lead_id='collab-openeng' ORDER BY created_at LIMIT 1"
    ).fetchone()
    expected_openeng_hash = sha256_text(
        "Research collaboration: a bounded governed-execution compatibility study\n" + OPENENG_BODY
    )
    if openeng and openeng["content_hash"] != expected_openeng_hash:
        store.update_draft(
            openeng["id"],
            "Research collaboration: a bounded governed-execution compatibility study",
            OPENENG_BODY,
        )

    # Composio's route is current, but the personal mailbox and evidence do not satisfy its application fields.
    store.conn.execute("""
      UPDATE leads SET evidence_json=?,risk_notes=?,permission_verified_at='2026-10-28',
      status='qualified',updated_at=? WHERE id='collab-composio'
    """, (
        stable_json([
            {"url": "https://composio.dev/partnerships", "finding": "Official partnership application covers AI frameworks/agent platforms and requests a company work email, partnership idea, and expected user journey."},
            {"url": "https://docs.composio.dev/kb/guide/faqs", "finding": "Official FAQ directs company integration requests to the partnership form with company and product details."},
        ]),
        "Channel is legitimate, but a personal @163.com sender is not the requested company work email. Verified company identity and a concrete expected user journey are missing; hold the draft without changing permission level.", now,
    ))
    store.conn.execute(
        "UPDATE drafts SET status='identity_hold',updated_at=? WHERE lead_id='collab-composio'",
        (now,),
    )

    # Any V1 batch that contains corrected material is no longer reviewable.
    store.conn.execute("""
      UPDATE batches SET status='invalidated' WHERE id IN (
        SELECT DISTINCT bi.batch_id FROM batch_items bi JOIN drafts d ON d.id=bi.draft_id
        WHERE d.lead_id IN ('editorial-opensource-com','collab-openeng','collab-composio')
      )
    """)
    store.conn.execute("""
      UPDATE approvals SET revoked_at=? WHERE revoked_at IS NULL AND draft_id IN (
        SELECT id FROM drafts WHERE lead_id IN ('editorial-opensource-com','collab-openeng','collab-composio')
      )
    """, (now,))
    store.conn.commit()

    rows = [dict(row) for row in store.conn.execute("""
      SELECT l.id,o.name organization,l.project_name,l.campaign_type,l.source_kind,l.scout_source_id,
      l.source_url,l.pain_point,l.contact_channel,l.contact_value,l.allowed_purpose,
      l.permission_status,l.permission_verified_at,l.language,l.technical_fit,l.ecosystem_value,
      l.recommended_capability,l.evidence_json,l.case_links_json,l.risk_notes,l.status,l.last_contact_at
      FROM leads l JOIN organizations o ON o.id=l.organization_id
      ORDER BY l.source_kind='scout_v2' DESC,l.technical_fit DESC,o.name
    """)]
    write_csv(args.output_dir / "UPDATED_LEADS.csv", rows, list(rows[0].keys()))

    drafts = list(store.conn.execute("""
      SELECT d.*,o.name organization,l.contact_value,l.allowed_purpose,l.permission_status,
      l.source_url,l.risk_notes FROM drafts d JOIN leads l ON l.id=d.lead_id
      JOIN organizations o ON o.id=l.organization_id
      WHERE l.id IN ('editorial-opensource-com','collab-openeng','collab-composio')
      ORDER BY o.name
    """))
    doc = [
        "# UPDATED DRAFTS — V1.1", "",
        "> No message has been approved or sent. These are review records, not a send queue.", "",
        "## Channel decisions", "",
        "- **OpenEng Labs:** current official research route verified; revised draft below matches its four requested inputs. Still blocked on sender setup, owner self-test, and a new exact-batch approval.",
        "- **Composio:** official route is current, but the application requests a company work email and concrete company/user-journey fields. A personal `@163.com` identity does not satisfy that request; the historical draft is on `identity_hold`.",
        "- **Opensource.com:** `stale_channel`; daily publication ended in April 2023. The historical draft is permanently excluded.",
        "- **OpenSource.net:** possible successor, but submission requires sign-in and OSI individual membership. Membership is unverified, so no draft or submission was created.", "",
    ]
    for row in drafts:
        doc += [
            f"## {row['organization']}", "",
            f"- Draft status: `{row['status']}`", f"- To: `{row['contact_value']}`",
            f"- Permission record: `{row['permission_status']}` (not elevated in V1.1)",
            f"- Allowed purpose: {row['allowed_purpose']}", f"- Evidence: {row['source_url']}",
            f"- Content SHA-256: `{row['content_hash']}`", f"- Risk: {row['risk_notes']}", "",
            f"Subject: {row['subject']}", "", row["body"], "",
        ]
    (args.output_dir / "UPDATED_DRAFTS.md").write_text("\n".join(doc), encoding="utf-8")

    batch = store.conn.execute(
        "SELECT id,status,sender_account FROM batches ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    checklist = store.review_checklist(batch["id"]) if batch else []
    (args.output_dir / "review-checklist.json").write_text(
        json.dumps(checklist, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    checks = list(store.conn.execute(
        "SELECT phase,status,checked_at,details_json FROM provider_checks ORDER BY checked_at"
    ))
    readiness = [
        "# SEND READINESS REPORT", "", f"Generated: {now}", "",
        "## Outcome", "",
        "**Not ready for third-party sending. No V1 or V1.1 message has been externally sent.**", "",
        f"- V1 batch `{batch['id'] if batch else 'none'}`: `{batch['status'] if batch else 'missing'}`.",
        "- Current formal V1.1 batch: none.",
        "- Active provider account with completed phase 2: " + ("yes" if any(row["phase"] == "phase2_owner_self_test" and row["status"] == "passed" for row in checks) else "no"),
        "- Active exact batch approval: no.",
        "- Third-party messages sent: 0.", "",
        "## Lead-level result", "",
        "| Target | Channel | Decision | Third-party send eligibility |", "|---|---|---|---|",
        "| OpenEng Labs | `hello@openeng.ai` | Revised and relevant | Blocked pending provider phase 1/2 and a new exact-batch approval |",
        "| Composio | partnership application / email | Legitimate route, identity and user-journey evidence insufficient | Hold |",
        "| Opensource.com | legacy email | `stale_channel` | Permanently blocked |",
        "| OpenSource.net | membership-gated form | Requirements recorded, membership unverified | Blocked |", "",
        "## Required gates", "",
        "1. Complete phase 1 SMTP/IMAP authentication with a personal `@163.com` account.",
        "2. Complete the single self-addressed phase 2 message and verify INBOX, Sent, Chinese MIME, and link.",
        "3. Configure the true sender identity in the draft; create a new small batch.",
        "4. Review exact recipient, sender, subject, body, evidence, risk, duplicate/suppression checks, and approval fingerprint.",
        "5. Obtain explicit user approval for that exact batch. Any sender, recipient, subject, or body change invalidates it.",
        "6. Treat `smtp_accepted` as `delivery_unknown` until independent evidence or a reply exists; never blind-retry uncertainty.", "",
        "## Provider check log", "",
    ]
    if checks:
        readiness += ["| Phase | Status | Checked at |", "|---|---|---|"] + [
            f"| {row['phase']} | {row['status']} | {row['checked_at']} |" for row in checks
        ]
    else:
        readiness.append("No account verification has been performed; secure local input is still required.")
    (args.output_dir / "SEND_READINESS_REPORT.md").write_text(
        "\n".join(readiness) + "\n", encoding="utf-8"
    )
    store.close()
    after = file_sha256(args.scout_db)
    if after != before:
        raise RuntimeError("Scout V2 database changed")
    print(json.dumps({
        "updated_leads": len(rows), "scout_before": before, "scout_after": after,
        "scout_unchanged": before == after, "third_party_messages_sent": 0,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
