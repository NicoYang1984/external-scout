#!/usr/bin/env python3
"""Read-only Scout V2 adapter with source checksum verification."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from outreach_core import OutreachStore, stable_json, utcnow


def file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_scout(store: OutreachStore, scout_db: Path | str) -> Dict[str, Any]:
    scout_db = Path(scout_db).resolve()
    before = file_sha256(scout_db)
    conn = sqlite3.connect(f"file:{scout_db}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version != 2:
        raise ValueError(f"Scout database must be V2, got user_version={version}")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = {"opportunities", "history", "source_items"}
    if not required.issubset(tables):
        raise ValueError(f"Scout database missing tables: {sorted(required - tables)}")
    imported = 0
    lead_ids: List[str] = []
    for row in conn.execute("SELECT url,payload FROM opportunities ORDER BY url"):
        payload = json.loads(row["payload"])
        history = [json.loads(x[0]) for x in conn.execute(
            "SELECT payload FROM history WHERE url=? ORDER BY id", (row["url"],)
        )]
        source_id = f"scout-opportunity:{row['url']}"
        store.conn.execute("""
          INSERT INTO scout_records(source_id,source_kind,source_url,current_payload,history_json,
          source_db_sha256,imported_at) VALUES(?,?,?,?,?,?,?)
          ON CONFLICT(source_id) DO UPDATE SET current_payload=excluded.current_payload,
          history_json=excluded.history_json,source_db_sha256=excluded.source_db_sha256,
          imported_at=excluded.imported_at
        """, (source_id, "opportunity", row["url"], stable_json(payload), stable_json(history), before, utcnow()))
        technical = payload.get("technical_score", payload.get("score", 0))
        ecosystem = payload.get("ecosystem_score")
        if ecosystem is None:
            e = payload.get("ecosystem_value", {})
            ecosystem = sum(int(e.get(k, 0)) for k in ("user_value", "collaboration", "audience_evidence"))
        sources = payload.get("sources", [])
        lead_payload = {
            "id": hashlib.sha256(source_id.encode()).hexdigest()[:32],
            "organization": payload.get("repo", row["url"].split("/")[2]),
            "project_name": payload.get("repo", payload.get("title", row["url"])),
            "campaign_type": "developer_collaboration",
            "source_kind": "scout_v2",
            "scout_source_id": source_id,
            "source_url": row["url"],
            "pain_point": payload.get("summary", payload.get("title", "Scout opportunity")),
            "evidence": sources or [{"url": row["url"], "finding": "Scout V2 opportunity"}],
            "contact_channel": "unknown",
            "contact_value": "",
            "allowed_purpose": payload.get("outreach_channel") or "not established",
            "permission_status": "not_granted",
            "permission_verified_at": None,
            "language": "language_unknown",
            "technical_fit": int(technical or 0),
            "ecosystem_value": int(ecosystem or 0),
            "recommended_capability": ", ".join(payload.get("capability_ids", [])),
            "case_links": [x.get("source") for x in payload.get("capability_evidence", []) if x.get("source", "").startswith("http")],
            "risk_notes": "Imported read-only from Scout. Permission is never promoted by import.",
            "status": "discovered",
        }
        lead_ids.append(store.upsert_lead(lead_payload))
        imported += 1
    store.conn.commit()
    conn.close()
    after = file_sha256(scout_db)
    if before != after:
        raise RuntimeError("Scout database changed during read-only import")
    return {"scout_user_version": version, "imported_opportunities": imported, "lead_ids": lead_ids, "sha256_before": before, "sha256_after": after, "unchanged": True}


def export_outcomes(store: OutreachStore, output: Path | str) -> None:
    """Explicit one-way handoff file; never writes the Scout database."""
    rows = store.conn.execute("""
      SELECT scout_source_id,status,last_contact_at,updated_at FROM leads
      WHERE scout_source_id IS NOT NULL ORDER BY scout_source_id
    """).fetchall()
    payload = {
        "schema": "lazymind-outreach-scout-outcomes/v1",
        "generated_at": utcnow(),
        "records": [dict(row) for row in rows],
    }
    Path(output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

