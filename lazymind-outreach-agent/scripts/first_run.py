#!/usr/bin/env python3
"""Load the curated first run and render the required review artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List

from outreach_core import OutreachStore
from scout_adapter import import_scout


def write_csv(path: Path, rows: List[Dict[str, Any]], fields: List[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--scout-db", type=Path, required=True)
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    store = OutreachStore(args.db)
    store.init()
    scout_result = import_scout(store, args.scout_db)
    data = json.loads(args.candidates.read_text(encoding="utf-8"))
    lead_ids: Dict[str, str] = {}
    for lead in data["leads"]:
        lead_ids[lead["id"]] = store.upsert_lead(lead)
    draft_ids = []
    for draft in data["drafts"]:
        draft_ids.append(store.add_draft(
            lead_ids[draft["lead_id"]], draft["subject"], draft["body"], draft["language"]
        ))
    batch_id = store.create_batch(
        "first-run-2026-10-28", "UNCONFIGURED", draft_ids
    )
    checklist = store.review_checklist(batch_id)
    (args.output_dir / "review-checklist.json").write_text(
        json.dumps(checklist, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lead_rows = [dict(row) for row in store.conn.execute("""
      SELECT l.id,o.name organization,l.project_name,l.campaign_type,l.source_kind,l.scout_source_id,
      l.source_url,l.pain_point,l.contact_channel,l.contact_value,l.allowed_purpose,
      l.permission_status,l.permission_verified_at,l.language,l.technical_fit,l.ecosystem_value,
      l.recommended_capability,l.evidence_json,l.case_links_json,l.risk_notes,l.status,l.last_contact_at
      FROM leads l JOIN organizations o ON o.id=l.organization_id
      ORDER BY l.source_kind='scout_v2' DESC,l.technical_fit DESC,o.name
    """).fetchall()]
    write_csv(args.output_dir / "LEADS.csv", lead_rows, list(lead_rows[0].keys()))

    tracker_rows = [dict(row) for row in store.conn.execute("""
      SELECT l.id,o.name organization,l.campaign_type,l.status,l.permission_status,
      l.last_contact_at,d.id draft_id,d.content_hash,d.status draft_status,
      bi.batch_id,NULL send_mode,NULL provider_message_id,NULL reply_category
      FROM leads l JOIN organizations o ON o.id=l.organization_id
      LEFT JOIN drafts d ON d.lead_id=l.id
      LEFT JOIN batch_items bi ON bi.draft_id=d.id
      ORDER BY o.name
    """).fetchall()]
    write_csv(args.output_dir / "OUTREACH_TRACKER.csv", tracker_rows, list(tracker_rows[0].keys()))

    drafts_md = ["# DRAFTS", "", "> Internal review only. No batch was approved and no message was sent.", ""]
    for row in store.conn.execute("""
      SELECT d.*,o.name organization,l.contact_value,l.allowed_purpose,l.permission_status,
             l.source_url,l.risk_notes FROM drafts d JOIN leads l ON l.id=d.lead_id
             JOIN organizations o ON o.id=l.organization_id ORDER BY o.name
    """):
        drafts_md += [
            f"## {row['organization']}", "",
            f"- To: `{row['contact_value']}`", f"- Allowed purpose: {row['allowed_purpose']}",
            f"- Permission: `{row['permission_status']}`", f"- Source: {row['source_url']}",
            "- Sender account: `UNCONFIGURED — real sending blocked`",
            f"- Content SHA-256: `{row['content_hash']}`", f"- Risk: {row['risk_notes']}", "",
            "- Duplicate check: no prior contact recorded for this organization; batch-level recheck still required.", "",
            f"Subject: {row['subject']}", "", row["body"], "",
        ]
    (args.output_dir / "DRAFTS.md").write_text("\n".join(drafts_md), encoding="utf-8")

    metrics = store.metrics()
    report = {
        "scout_import": scout_result,
        "curated_candidates": len(data["leads"]),
        "drafts": len(draft_ids),
        "batch_id": batch_id,
        "batch_approval_blockers": {x["draft_id"]: x["checks"] for x in checklist},
        "metrics": metrics,
        "real_messages_sent": 0,
        "simulated_messages_sent": 0,
    }
    (args.output_dir / "first-run-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    store.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
