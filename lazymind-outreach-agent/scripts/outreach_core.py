#!/usr/bin/env python3
"""SQLite-backed policy engine for controlled LazyMind outreach."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


CAMPAIGNS = {"editorial_pitch", "developer_collaboration", "business_trial"}
STATUSES = {
    "discovered", "qualified", "drafted", "review_pending", "approved",
    "queued", "smtp_accepted", "delivery_unknown", "failed", "sent", "replied",
    "interested", "trial_started", "declined", "suppressed", "stale_channel",
}
SENDABLE_PERMISSIONS = {
    "explicit_opt_in", "official_submission_channel",
    "official_collaboration_channel", "prior_correspondence",
}
FORBIDDEN_PROFILE_KEYS = {
    "nationality", "citizenship", "ethnicity", "race", "族裔", "民族", "国籍",
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEFAULT_SEND_INTERVAL_SECONDS = 300


def pacing_now() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_org(value: str) -> str:
    return re.sub(r"[^\w]+", "-", value.casefold(), flags=re.UNICODE).strip("-_")


def normalize_contact(channel: str, value: str) -> str:
    value = value.strip()
    if channel == "email":
        return value.casefold()
    return value.rstrip("/").casefold()


def ensure_no_sensitive_inference(payload: Dict[str, Any]) -> None:
    bad = FORBIDDEN_PROFILE_KEYS.intersection(payload)
    if bad:
        raise ValueError(f"forbidden inferred profile fields: {sorted(bad)}")


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS organizations (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, organization_key TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY, organization_id INTEGER NOT NULL REFERENCES organizations(id),
  project_name TEXT NOT NULL, campaign_type TEXT NOT NULL,
  source_kind TEXT NOT NULL, scout_source_id TEXT, source_url TEXT NOT NULL,
  pain_point TEXT NOT NULL, evidence_json TEXT NOT NULL,
  contact_channel TEXT NOT NULL, contact_value TEXT NOT NULL,
  normalized_contact TEXT NOT NULL, allowed_purpose TEXT NOT NULL,
  permission_status TEXT NOT NULL, permission_verified_at TEXT,
  language TEXT NOT NULL, technical_fit INTEGER NOT NULL,
  ecosystem_value INTEGER NOT NULL, recommended_capability TEXT NOT NULL,
  case_links_json TEXT NOT NULL, risk_notes TEXT NOT NULL,
  status TEXT NOT NULL, last_contact_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS lead_contact_campaign
  ON leads(normalized_contact, campaign_type) WHERE normalized_contact <> '';
CREATE TABLE IF NOT EXISTS lead_versions (
  id INTEGER PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id),
  recorded_at TEXT NOT NULL, payload_hash TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scout_records (
  source_id TEXT PRIMARY KEY, source_kind TEXT NOT NULL, source_url TEXT NOT NULL,
  current_payload TEXT NOT NULL, history_json TEXT NOT NULL,
  source_db_sha256 TEXT NOT NULL, imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
  id TEXT PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id),
  subject TEXT NOT NULL, body TEXT NOT NULL, language TEXT NOT NULL,
  content_hash TEXT NOT NULL, version INTEGER NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS draft_versions (
  id INTEGER PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES drafts(id),
  version INTEGER NOT NULL, content_hash TEXT NOT NULL,
  subject TEXT NOT NULL, body TEXT NOT NULL, recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sender_accounts (
  account TEXT PRIMARY KEY, provider TEXT NOT NULL, authorized INTEGER NOT NULL,
  verified_at TEXT, created_at TEXT NOT NULL,
  account_type TEXT NOT NULL DEFAULT 'unspecified',
  connection_verified_at TEXT, live_enabled INTEGER NOT NULL DEFAULT 0,
  details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS batches (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, sender_account TEXT NOT NULL,
  status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS send_pacing (
  account TEXT PRIMARY KEY REFERENCES sender_accounts(account),
  min_interval_seconds INTEGER NOT NULL DEFAULT 300 CHECK(min_interval_seconds BETWEEN 60 AND 86400),
  last_reserved_at TEXT, next_allowed_at TEXT
);
CREATE TABLE IF NOT EXISTS batch_items (
  batch_id TEXT NOT NULL REFERENCES batches(id),
  draft_id TEXT NOT NULL REFERENCES drafts(id),
  PRIMARY KEY(batch_id, draft_id)
);
CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id),
  draft_id TEXT NOT NULL REFERENCES drafts(id), content_hash TEXT NOT NULL,
  approval_fingerprint TEXT,
  approved_by TEXT NOT NULL, approved_at TEXT NOT NULL,
  revoked_at TEXT, UNIQUE(batch_id, draft_id, content_hash)
);
CREATE TABLE IF NOT EXISTS suppressions (
  id INTEGER PRIMARY KEY, organization_id INTEGER REFERENCES organizations(id),
  normalized_contact TEXT, reason TEXT NOT NULL, source TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS send_requests (
  idempotency_key TEXT PRIMARY KEY, batch_id TEXT NOT NULL,
  draft_id TEXT NOT NULL, mode TEXT NOT NULL, content_hash TEXT NOT NULL,
  status TEXT NOT NULL, provider_message_id TEXT, last_error TEXT,
  rfc_message_id TEXT, recipient_snapshot TEXT, subject_snapshot TEXT,
  safe_to_retry INTEGER NOT NULL DEFAULT 1, details_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS send_attempts (
  id INTEGER PRIMARY KEY, idempotency_key TEXT NOT NULL,
  mode TEXT NOT NULL, outcome TEXT NOT NULL, provider_message_id TEXT,
  error TEXT, attempted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_checks (
  id INTEGER PRIMARY KEY, account TEXT NOT NULL, provider TEXT NOT NULL,
  phase TEXT NOT NULL, status TEXT NOT NULL, details_json TEXT NOT NULL,
  checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS replies (
  id TEXT PRIMARY KEY, lead_id TEXT NOT NULL REFERENCES leads(id),
  provider_message_id TEXT, received_at TEXT NOT NULL,
  category TEXT NOT NULL, body_excerpt TEXT NOT NULL,
  follow_up_draft_required INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS replies_provider_message
  ON replies(provider_message_id) WHERE provider_message_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, lead_id TEXT, event_type TEXT NOT NULL,
  payload TEXT NOT NULL, occurred_at TEXT NOT NULL,
  human_seconds REAL NOT NULL DEFAULT 0
);
"""


@dataclass
class SendResult:
    status: str
    provider_message_id: Optional[str] = None
    error: Optional[str] = None
    rfc_message_id: Optional[str] = None
    safe_to_retry: bool = True
    details: Optional[Dict[str, Any]] = None


class OutreachStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        self.conn.close()

    def init(self) -> None:
        self.conn.executescript(SCHEMA)
        self._ensure_column("sender_accounts", "account_type", "TEXT NOT NULL DEFAULT 'unspecified'")
        self._ensure_column("sender_accounts", "connection_verified_at", "TEXT")
        self._ensure_column("sender_accounts", "live_enabled", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("sender_accounts", "details_json", "TEXT NOT NULL DEFAULT '{}'")
        self._ensure_column("approvals", "approval_fingerprint", "TEXT")
        self._ensure_column("send_requests", "rfc_message_id", "TEXT")
        self._ensure_column("send_requests", "recipient_snapshot", "TEXT")
        self._ensure_column("send_requests", "subject_snapshot", "TEXT")
        self._ensure_column("send_requests", "safe_to_retry", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("send_requests", "details_json", "TEXT NOT NULL DEFAULT '{}'")
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES('schema_version','1.1') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )
        self.conn.commit()

    def _ensure_column(self, table: str, name: str, declaration: str) -> None:
        columns = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    def _org_id(self, name: str) -> int:
        key = normalize_org(name)
        if not key:
            raise ValueError("organization name cannot be empty")
        now = utcnow()
        self.conn.execute(
            "INSERT OR IGNORE INTO organizations(name,organization_key,created_at) VALUES(?,?,?)",
            (name.strip(), key, now),
        )
        return int(self.conn.execute(
            "SELECT id FROM organizations WHERE organization_key=?", (key,)
        ).fetchone()[0])

    def upsert_lead(self, payload: Dict[str, Any]) -> str:
        ensure_no_sensitive_inference(payload)
        campaign = payload["campaign_type"]
        if campaign not in CAMPAIGNS:
            raise ValueError(f"unsupported campaign: {campaign}")
        status = payload.get("status", "discovered")
        if status not in STATUSES:
            raise ValueError(f"unsupported status: {status}")
        language = payload.get("language", "language_unknown")
        if language not in {"zh-CN", "en", "language_unknown"}:
            raise ValueError("language must be zh-CN, en, or language_unknown")
        channel = payload.get("contact_channel", "unknown")
        contact = payload.get("contact_value", "")
        normalized = normalize_contact(channel, contact)
        if channel == "email" and contact and not EMAIL_RE.match(contact):
            raise ValueError("invalid email address")
        org_id = self._org_id(payload["organization"])
        lead_id = payload.get("id") or str(uuid.uuid4())
        now = utcnow()
        evidence = payload.get("evidence", [])
        case_links = payload.get("case_links", [])
        values = (
            lead_id, org_id, payload.get("project_name", payload["organization"]), campaign,
            payload.get("source_kind", "official_web"), payload.get("scout_source_id"),
            payload["source_url"], payload["pain_point"], stable_json(evidence), channel,
            contact, normalized, payload.get("allowed_purpose", ""),
            payload.get("permission_status", "unknown"), payload.get("permission_verified_at"),
            language, int(payload.get("technical_fit", 0)), int(payload.get("ecosystem_value", 0)),
            payload.get("recommended_capability", ""), stable_json(case_links),
            payload.get("risk_notes", ""), status, payload.get("last_contact_at"), now, now,
        )
        existing = self.conn.execute("SELECT id,created_at FROM leads WHERE id=?", (lead_id,)).fetchone()
        if existing:
            values = values[:-2] + (existing["created_at"], now)
            self.conn.execute("""
              UPDATE leads SET organization_id=?,project_name=?,campaign_type=?,source_kind=?,
              scout_source_id=?,source_url=?,pain_point=?,evidence_json=?,contact_channel=?,
              contact_value=?,normalized_contact=?,allowed_purpose=?,permission_status=?,
              permission_verified_at=?,language=?,technical_fit=?,ecosystem_value=?,
              recommended_capability=?,case_links_json=?,risk_notes=?,status=?,last_contact_at=?,
              created_at=?,updated_at=? WHERE id=?
            """, values[1:] + (lead_id,))
        else:
            self.conn.execute("""
              INSERT INTO leads(id,organization_id,project_name,campaign_type,source_kind,
              scout_source_id,source_url,pain_point,evidence_json,contact_channel,contact_value,
              normalized_contact,allowed_purpose,permission_status,permission_verified_at,
              language,technical_fit,ecosystem_value,recommended_capability,case_links_json,
              risk_notes,status,last_contact_at,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, values)
        snapshot = dict(payload)
        snapshot["id"] = lead_id
        encoded = stable_json(snapshot)
        self.conn.execute(
            "INSERT INTO lead_versions(lead_id,recorded_at,payload_hash,payload) VALUES(?,?,?,?)",
            (lead_id, now, sha256_text(encoded), encoded),
        )
        self.conn.execute(
            "INSERT INTO events(lead_id,event_type,payload,occurred_at) VALUES(?,?,?,?)",
            (lead_id, "lead_upserted", stable_json({"status": status}), now),
        )
        self.conn.commit()
        return lead_id

    def add_draft(self, lead_id: str, subject: str, body: str, language: str) -> str:
        lead = self.conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not lead:
            raise KeyError(lead_id)
        if language == "language_unknown" or lead["language"] == "language_unknown":
            raise ValueError("cannot draft when language is unknown")
        if lead["language"] != language:
            raise ValueError("draft language conflicts with evidence-backed lead language")
        if len(body.strip()) < 240:
            raise ValueError("draft is too short to contain evidence-backed personalization")
        evidence_urls = [x.get("url") for x in json.loads(lead["evidence_json"]) if x.get("url")]
        case_urls = [x for x in json.loads(lead["case_links_json"]) if isinstance(x, str)]
        if not any(url in body for url in evidence_urls + case_urls):
            raise ValueError("draft must include at least one recorded evidence or case URL")
        now = utcnow()
        content_hash = sha256_text(subject + "\n" + body)
        existing = self.conn.execute(
            "SELECT id FROM drafts WHERE lead_id=? AND content_hash=? ORDER BY created_at LIMIT 1",
            (lead_id, content_hash),
        ).fetchone()
        if existing:
            self.conn.execute(
                "UPDATE leads SET status='review_pending',updated_at=? WHERE id=? AND status IN ('discovered','qualified','drafted','review_pending')",
                (now, lead_id),
            )
            self.conn.commit()
            return str(existing["id"])
        draft_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO drafts VALUES(?,?,?,?,?,?,?,?,?,?)",
            (draft_id, lead_id, subject, body, language, content_hash, 1, "review_pending", now, now),
        )
        self.conn.execute(
            "INSERT INTO draft_versions(draft_id,version,content_hash,subject,body,recorded_at) VALUES(?,?,?,?,?,?)",
            (draft_id, 1, content_hash, subject, body, now),
        )
        self.conn.execute("UPDATE leads SET status='review_pending',updated_at=? WHERE id=?", (now, lead_id))
        self.conn.commit()
        return draft_id

    def update_draft(self, draft_id: str, subject: str, body: str) -> str:
        row = self.conn.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
        if not row:
            raise KeyError(draft_id)
        now = utcnow()
        version = int(row["version"]) + 1
        content_hash = sha256_text(subject + "\n" + body)
        self.conn.execute(
            "UPDATE drafts SET subject=?,body=?,content_hash=?,version=?,status='review_pending',updated_at=? WHERE id=?",
            (subject, body, content_hash, version, now, draft_id),
        )
        self.conn.execute(
            "INSERT INTO draft_versions(draft_id,version,content_hash,subject,body,recorded_at) VALUES(?,?,?,?,?,?)",
            (draft_id, version, content_hash, subject, body, now),
        )
        self.conn.execute(
            "UPDATE approvals SET revoked_at=? WHERE draft_id=? AND revoked_at IS NULL AND content_hash<>?",
            (now, draft_id, content_hash),
        )
        self.conn.execute(
            "UPDATE leads SET status='review_pending',updated_at=? WHERE id=?", (now, row["lead_id"])
        )
        self.conn.commit()
        return content_hash

    def create_batch(self, name: str, sender_account: str, draft_ids: Iterable[str]) -> str:
        draft_ids = list(draft_ids)
        if not draft_ids:
            raise ValueError("batch cannot be empty")
        if len(draft_ids) > 10:
            raise ValueError("small-batch limit is 10")
        rows = [self.conn.execute("""
            SELECT d.*,l.organization_id,l.normalized_contact,l.permission_status,l.status lead_status
            FROM drafts d JOIN leads l ON l.id=d.lead_id WHERE d.id=?
        """, (draft_id,)).fetchone() for draft_id in draft_ids]
        if any(row is None for row in rows):
            raise KeyError("unknown draft")
        orgs = [row["organization_id"] for row in rows]
        contacts = [row["normalized_contact"] for row in rows if row["normalized_contact"]]
        if len(orgs) != len(set(orgs)):
            raise ValueError("same organization cannot appear twice in one batch")
        if len(contacts) != len(set(contacts)):
            raise ValueError("duplicate contact in batch")
        if len({row["content_hash"] for row in rows}) != len(rows):
            raise ValueError("identical draft content is not personalized")
        for candidate in self.conn.execute(
            "SELECT id FROM batches WHERE name=? AND sender_account=? ORDER BY created_at",
            (name, sender_account),
        ):
            existing_ids = {x[0] for x in self.conn.execute(
                "SELECT draft_id FROM batch_items WHERE batch_id=?", (candidate["id"],)
            )}
            if existing_ids == set(draft_ids):
                return str(candidate["id"])
        batch_id = str(uuid.uuid4())
        now = utcnow()
        self.conn.execute("INSERT INTO batches VALUES(?,?,?,?,?)", (batch_id, name, sender_account, "review_pending", now))
        self.conn.executemany(
            "INSERT INTO batch_items(batch_id,draft_id) VALUES(?,?)",
            [(batch_id, draft_id) for draft_id in draft_ids],
        )
        self.conn.commit()
        return batch_id

    def configure_sender(
        self,
        account: str,
        provider: str,
        authorized: bool,
        verified_at: Optional[str] = None,
        *,
        account_type: str = "unspecified",
        connection_verified_at: Optional[str] = None,
        live_enabled: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.conn.execute("""
          INSERT INTO sender_accounts(account,provider,authorized,verified_at,created_at,
          account_type,connection_verified_at,live_enabled,details_json)
          VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(account) DO UPDATE SET
          provider=excluded.provider,authorized=excluded.authorized,
          verified_at=excluded.verified_at,account_type=excluded.account_type,
          connection_verified_at=excluded.connection_verified_at,
          live_enabled=excluded.live_enabled,details_json=excluded.details_json
        """, (
            account, provider, int(authorized), verified_at, utcnow(), account_type,
            connection_verified_at, int(live_enabled), stable_json(details or {}),
        ))
        self.conn.commit()

    def record_provider_check(
        self, account: str, provider: str, phase: str, status: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO provider_checks(account,provider,phase,status,details_json,checked_at) "
            "VALUES(?,?,?,?,?,?)",
            (account, provider, phase, status, stable_json(details or {}), utcnow()),
        )
        self.conn.commit()

    def get_send_pacing(self, account: str) -> Dict[str, Any]:
        row = self.conn.execute("SELECT * FROM send_pacing WHERE account=?", (account,)).fetchone()
        return dict(row) if row else {
            "account": account, "min_interval_seconds": DEFAULT_SEND_INTERVAL_SECONDS,
            "last_reserved_at": None, "next_allowed_at": None,
        }

    def set_send_interval(self, account: str, seconds: int) -> Dict[str, Any]:
        # Local guardrail, not a claim about any provider's sending allowance.
        if type(seconds) is not int or not 60 <= seconds <= 86400:
            raise ValueError("send interval must be an integer from 60 to 86400 seconds")
        if not self.conn.execute("SELECT 1 FROM sender_accounts WHERE account=?", (account,)).fetchone():
            raise ValueError("configure the sender account before setting its send interval")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            current = self.get_send_pacing(account)
            next_allowed = current["next_allowed_at"]
            if current["last_reserved_at"]:
                extended = datetime.fromisoformat(current["last_reserved_at"]) + timedelta(seconds=seconds)
                if not next_allowed or extended > datetime.fromisoformat(next_allowed):
                    next_allowed = extended.isoformat()
            self.conn.execute("""
              INSERT INTO send_pacing(account,min_interval_seconds,last_reserved_at,next_allowed_at)
              VALUES(?,?,?,?) ON CONFLICT(account) DO UPDATE SET
              min_interval_seconds=excluded.min_interval_seconds,next_allowed_at=excluded.next_allowed_at
            """, (account, seconds, current["last_reserved_at"], next_allowed))
            self.conn.execute(
                "INSERT INTO events(event_type,payload,occurred_at) VALUES(?,?,?)",
                ("send_interval_configured", stable_json({"account": account, "seconds": seconds}), utcnow()),
            )
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise
        return self.get_send_pacing(account)

    def _reserve_send_slot(self, account: str) -> Optional[Dict[str, Any]]:
        """Must run in the same write transaction as queued-request reservation."""
        if not self.conn.in_transaction:
            raise RuntimeError("send pacing reservation requires a transaction")
        now = pacing_now()
        current = self.get_send_pacing(account)
        if current["next_allowed_at"]:
            remaining = (datetime.fromisoformat(current["next_allowed_at"]) - now).total_seconds()
            if remaining > 0:
                return {"status": "deferred_rate_limit", "account": account,
                        "retry_after_seconds": math.ceil(remaining),
                        "next_allowed_at": current["next_allowed_at"],
                        "min_interval_seconds": current["min_interval_seconds"], "mode": "real"}
        self.conn.execute("""
          INSERT INTO send_pacing(account,min_interval_seconds,last_reserved_at,next_allowed_at)
          VALUES(?,?,?,?) ON CONFLICT(account) DO UPDATE SET
          last_reserved_at=excluded.last_reserved_at,next_allowed_at=excluded.next_allowed_at
        """, (account, current["min_interval_seconds"], now.isoformat(),
              (now + timedelta(seconds=current["min_interval_seconds"])).isoformat()))
        return None

    def _check_live_sender(self, item: Dict[str, Any]) -> None:
        if (item["sender_provider"] != "netease163_personal"
                or item["sender_account_type"] != "personal_163"
                or not item["sender_authorized"] or not item["connection_verified_at"]
                or not item["sender_live_enabled"]):
            raise RuntimeError("real sending is disabled until phased provider verification is complete")

    @staticmethod
    def approval_fingerprint(
        sender_account: str, recipient: str, subject: str, body: str
    ) -> str:
        return sha256_text("\n".join((
            sender_account.strip().casefold(), recipient.strip().casefold(), subject, body,
        )))

    def _check_sendable(self, row: sqlite3.Row) -> List[str]:
        errors: List[str] = []
        if "lead_status" in row.keys() and row["lead_status"] in {"stale_channel", "suppressed", "declined"}:
            errors.append(f"lead status is {row['lead_status']}")
        if "draft_status" in row.keys() and row["draft_status"] in {"identity_hold", "stale_channel", "invalidated"}:
            errors.append(f"draft status is {row['draft_status']}")
        if row["permission_status"] not in SENDABLE_PERMISSIONS:
            errors.append("missing purpose-specific permission")
        if row["language"] == "language_unknown":
            errors.append("language unknown")
        if row["contact_channel"] != "email" or not EMAIL_RE.match(row["contact_value"]):
            errors.append("first-version sender requires a valid official email")
        if not row["sender_authorized"]:
            errors.append("sender account is not authorized")
        suppressed = self.conn.execute(
            "SELECT 1 FROM suppressions WHERE organization_id=? OR normalized_contact=? LIMIT 1",
            (row["organization_id"], row["normalized_contact"]),
        ).fetchone()
        if suppressed:
            errors.append("suppressed")
        prior = self.conn.execute("""
          SELECT 1 FROM leads WHERE organization_id=? AND id<>? AND last_contact_at IS NOT NULL LIMIT 1
        """, (row["organization_id"], row["lead_id"])).fetchone()
        if prior or row["last_contact_at"]:
            errors.append("organization already contacted")
        return errors

    def review_checklist(self, batch_id: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute("""
          SELECT d.id draft_id,d.subject,d.body,d.content_hash,d.language,d.status draft_status,
                 l.id lead_id,l.project_name,l.contact_channel,l.contact_value,
                 l.allowed_purpose,l.permission_status,l.permission_verified_at,
                 l.evidence_json,l.risk_notes,l.organization_id,l.normalized_contact,
                 l.last_contact_at,l.status lead_status,b.sender_account,COALESCE(sa.authorized,0) sender_authorized,
                 COALESCE(sa.provider,'') sender_provider,
                 COALESCE(sa.account_type,'unspecified') sender_account_type,
                 sa.connection_verified_at,COALESCE(sa.live_enabled,0) sender_live_enabled
          FROM batch_items bi JOIN drafts d ON d.id=bi.draft_id
          JOIN leads l ON l.id=d.lead_id JOIN batches b ON b.id=bi.batch_id
          LEFT JOIN sender_accounts sa ON sa.account=b.sender_account
          WHERE bi.batch_id=? ORDER BY l.project_name
        """, (batch_id,)).fetchall()
        return [dict(row) | {
            "evidence": json.loads(row["evidence_json"]),
            "approval_fingerprint": self.approval_fingerprint(
                row["sender_account"], row["contact_value"], row["subject"], row["body"]
            ),
            "checks": self._check_sendable(row),
        } for row in rows]

    def approve_batch(self, batch_id: str, approved_by: str, human_seconds: float = 0) -> None:
        checklist = self.review_checklist(batch_id)
        if not checklist:
            raise KeyError(batch_id)
        failures = {x["draft_id"]: x["checks"] for x in checklist if x["checks"]}
        if failures:
            raise ValueError(f"batch is not sendable: {failures}")
        now = utcnow()
        for item in checklist:
            self.conn.execute(
                "INSERT OR REPLACE INTO approvals(batch_id,draft_id,content_hash,approval_fingerprint,approved_by,approved_at,revoked_at) VALUES(?,?,?,?,?,?,NULL)",
                (batch_id, item["draft_id"], item["content_hash"], item["approval_fingerprint"], approved_by, now),
            )
            self.conn.execute("UPDATE drafts SET status='approved',updated_at=? WHERE id=?", (now, item["draft_id"]))
            self.conn.execute("UPDATE leads SET status='approved',updated_at=? WHERE id=?", (now, item["lead_id"]))
        self.conn.execute("UPDATE batches SET status='approved' WHERE id=?", (batch_id,))
        self.conn.execute(
            "INSERT INTO events(lead_id,event_type,payload,occurred_at,human_seconds) VALUES(NULL,?,?,?,?)",
            ("batch_approved", stable_json({"batch_id": batch_id, "approved_by": approved_by}), now, max(0.0, float(human_seconds))),
        )
        self.conn.commit()

    def send_batch(self, batch_id: str, adapter: Any, mode: str = "simulated") -> List[Dict[str, Any]]:
        if mode not in {"simulated", "real"}:
            raise ValueError("mode must be simulated or real")
        if mode == "real":
            batch = self.conn.execute(
                "SELECT b.*,sa.provider,sa.authorized,sa.account_type,sa.connection_verified_at,sa.live_enabled "
                "FROM batches b LEFT JOIN sender_accounts sa ON sa.account=b.sender_account WHERE b.id=?",
                (batch_id,),
            ).fetchone()
            if not batch:
                raise KeyError(batch_id)
            if getattr(adapter, "provider_name", None) != "netease163_personal":
                raise RuntimeError("real sending is disabled for this adapter")
            if (
                batch["provider"] != "netease163_personal"
                or batch["account_type"] != "personal_163"
                or not batch["authorized"]
                or not batch["connection_verified_at"]
                or not batch["live_enabled"]
            ):
                raise RuntimeError("real sending is disabled until phased provider verification is complete")
        checklist = self.review_checklist(batch_id)
        results = []
        for snapshot in checklist:
            # Refresh gates and atomically reserve both the account slot and request.
            # Never hold a database transaction while waiting or using the network.
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                fresh = self.review_checklist(batch_id)
                item = next((x for x in fresh if x["draft_id"] == snapshot["draft_id"]), None)
                if item is None:
                    raise ValueError("batch changed before sending")
                approval = self.conn.execute("""
                  SELECT 1 FROM approvals WHERE batch_id=? AND draft_id=? AND content_hash=?
                  AND approval_fingerprint=? AND revoked_at IS NULL
                """, (
                    batch_id, item["draft_id"], item["content_hash"], item["approval_fingerprint"],
                )).fetchone()
                if not approval:
                    raise ValueError(f"draft {item['draft_id']} lacks matching active approval")
                state = self.conn.execute("SELECT status FROM batches WHERE id=?", (batch_id,)).fetchone()
                if not state or state["status"] != "approved":
                    raise ValueError("batch is not approved")
                idem = sha256_text(
                    f"{batch_id}:{item['draft_id']}:{item['approval_fingerprint']}:{mode}"
                )
                existing = self.conn.execute("SELECT * FROM send_requests WHERE idempotency_key=?", (idem,)).fetchone()
                if existing and existing["status"] == "queued":
                    # Uncertain prior submission must never become a new SMTP attempt.
                    self.conn.execute(
                        "UPDATE send_requests SET status='delivery_unknown',safe_to_retry=0,"
                        "last_error=?,updated_at=? WHERE idempotency_key=?",
                        ("previous queued attempt ended without a recorded provider result", utcnow(), idem),
                    )
                    existing = self.conn.execute(
                        "SELECT * FROM send_requests WHERE idempotency_key=?", (idem,)
                    ).fetchone()
                if existing and existing["status"] in {
                    "succeeded", "smtp_accepted", "delivery_unknown", "retry_blocked", "replied"
                }:
                    self.conn.commit()
                    results.append(dict(existing))
                    continue
                if item["checks"]:
                    raise ValueError(f"draft {item['draft_id']} failed pre-send checks: {item['checks']}")
                if mode == "real":
                    self._check_live_sender(item)
                    deferred = self._reserve_send_slot(item["sender_account"])
                    if deferred:
                        self.conn.rollback()
                        results.append(deferred | {"batch_id": batch_id, "draft_id": item["draft_id"]})
                        break
                now = utcnow()
                self.conn.execute("""
                  INSERT INTO send_requests(idempotency_key,batch_id,draft_id,mode,content_hash,status,
                  provider_message_id,last_error,rfc_message_id,recipient_snapshot,subject_snapshot,
                  safe_to_retry,details_json,created_at,updated_at)
                  VALUES(?,?,?,?,?,'queued',NULL,NULL,NULL,?,?,1,'{}',?,?)
                  ON CONFLICT(idempotency_key) DO UPDATE SET status='queued',updated_at=excluded.updated_at
                """, (
                    idem, batch_id, item["draft_id"], mode, item["content_hash"],
                    item["contact_value"], item["subject"], now, now,
                ))
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise
            try:
                result: SendResult = adapter.send(
                    to=item["contact_value"], subject=item["subject"], body=item["body"],
                    sender=item["sender_account"], idempotency_key=idem,
                )
            except Exception as exc:  # unknown real outcomes must not be retried blindly
                result = SendResult(
                    status="delivery_unknown" if mode == "real" else "failed",
                    error=f"adapter exception: {type(exc).__name__}", safe_to_retry=mode != "real",
                )
            if result.status in {"simulated", "sent"}:
                request_status = "succeeded"
            elif result.status == "smtp_accepted":
                request_status = "delivery_unknown"
            elif result.status == "delivery_unknown":
                request_status = "delivery_unknown"
            elif result.status == "failed" and not result.safe_to_retry:
                request_status = "retry_blocked"
            else:
                request_status = "failed"
            self.conn.execute("""
              UPDATE send_requests SET status=?,provider_message_id=?,last_error=?,rfc_message_id=?,
              safe_to_retry=?,details_json=?,updated_at=?
              WHERE idempotency_key=?
            """, (
                request_status, result.provider_message_id, result.error, result.rfc_message_id,
                int(result.safe_to_retry), stable_json(result.details or {}), utcnow(), idem,
            ))
            self.conn.execute("""
              INSERT INTO send_attempts(idempotency_key,mode,outcome,provider_message_id,error,attempted_at)
              VALUES(?,?,?,?,?,?)
            """, (idem, mode, result.status, result.provider_message_id, result.error, utcnow()))
            # Simulations deliberately do not set last_contact_at or status=sent.
            if mode == "real" and result.status in {"smtp_accepted", "delivery_unknown"}:
                self.conn.execute(
                    "UPDATE leads SET status='delivery_unknown',last_contact_at=?,updated_at=? WHERE id=?",
                    (utcnow(), utcnow(), item["lead_id"]),
                )
            elif mode == "real" and result.status == "sent":
                self.conn.execute(
                    "UPDATE leads SET status='sent',last_contact_at=?,updated_at=? WHERE id=?",
                    (utcnow(), utcnow(), item["lead_id"]),
                )
            elif mode == "real" and result.status == "failed":
                self.conn.execute(
                    "UPDATE leads SET status='failed',updated_at=? WHERE id=?",
                    (utcnow(), item["lead_id"]),
                )
            self.conn.commit()
            results.append(dict(self.conn.execute(
                "SELECT * FROM send_requests WHERE idempotency_key=?", (idem,)
            ).fetchone()))
            if mode == "real" and result.status not in {"smtp_accepted", "sent"}:
                # Authentication, throttling, and ambiguous outcomes stop this run.
                break
        return results

    def suppress(self, lead_id: str, reason: str, source: str = "reply") -> None:
        lead = self.conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not lead:
            raise KeyError(lead_id)
        now = utcnow()
        self.conn.execute(
            "INSERT INTO suppressions(organization_id,normalized_contact,reason,source,created_at) VALUES(?,?,?,?,?)",
            (lead["organization_id"], lead["normalized_contact"], reason, source, now),
        )
        self.conn.execute("UPDATE leads SET status='suppressed',updated_at=? WHERE id=?", (now, lead_id))
        self.conn.commit()

    def record_reply(self, lead_id: str, body: str, provider_message_id: Optional[str] = None) -> str:
        if provider_message_id:
            existing = self.conn.execute(
                "SELECT category FROM replies WHERE provider_message_id=?", (provider_message_id,)
            ).fetchone()
            if existing:
                return str(existing["category"])
        lowered = body.casefold()
        if any(x in lowered for x in ("unsubscribe", "remove me", "退订", "不要再联系")):
            category = "unsubscribe"
        elif any(x in lowered for x in ("not interested", "no thanks", "不感兴趣", "拒绝")):
            category = "declined"
        elif any(x in lowered for x in ("interested", "let's talk", "愿意", "可以聊")):
            category = "interested"
        elif "?" in body or "？" in body:
            category = "question"
        else:
            category = "other"
        reply_id = str(uuid.uuid4())
        now = utcnow()
        follow_up = int(category in {"interested", "question"})
        self.conn.execute(
            "INSERT INTO replies VALUES(?,?,?,?,?,?,?)",
            (reply_id, lead_id, provider_message_id, now, category, body[:500], follow_up),
        )
        if category in {"unsubscribe", "declined"}:
            self.suppress(lead_id, category, "authorized_mailbox_reply")
        else:
            status = "interested" if category == "interested" else "replied"
            self.conn.execute("UPDATE leads SET status=?,updated_at=? WHERE id=?", (status, now, lead_id))
            self.conn.commit()
        return category

    def prepare_follow_up_draft(self, reply_id: str, subject: str, body: str, language: str) -> str:
        reply = self.conn.execute(
            "SELECT * FROM replies WHERE id=?", (reply_id,)
        ).fetchone()
        if not reply:
            raise KeyError(reply_id)
        if not reply["follow_up_draft_required"]:
            raise ValueError("reply does not justify a follow-up draft")
        # add_draft always returns review_pending; it never sends the reply.
        return self.add_draft(reply["lead_id"], subject, body, language)

    def metrics(self) -> Dict[str, Any]:
        counts = {row["status"]: row["n"] for row in self.conn.execute(
            "SELECT status,COUNT(*) n FROM leads GROUP BY status"
        )}
        discovered = self.conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        qualified = self.conn.execute(
            "SELECT COUNT(*) FROM leads WHERE permission_status IN (%s)" % ",".join("?" * len(SENDABLE_PERMISSIONS)),
            tuple(sorted(SENDABLE_PERMISSIONS)),
        ).fetchone()[0]
        approved = self.conn.execute("SELECT COUNT(DISTINCT draft_id) FROM approvals WHERE revoked_at IS NULL").fetchone()[0]
        real_sent = self.conn.execute("SELECT COUNT(*) FROM send_attempts WHERE mode='real' AND outcome='sent'").fetchone()[0]
        smtp_accepted = self.conn.execute(
            "SELECT COUNT(*) FROM send_attempts WHERE mode='real' AND outcome='smtp_accepted'"
        ).fetchone()[0]
        delivery_unknown = self.conn.execute(
            "SELECT COUNT(*) FROM send_requests WHERE mode='real' AND status='delivery_unknown'"
        ).fetchone()[0]
        replies = self.conn.execute("SELECT COUNT(*) FROM replies WHERE category<>'other'").fetchone()[0]
        interested = self.conn.execute("SELECT COUNT(*) FROM leads WHERE status IN ('interested','trial_started')").fetchone()[0]
        trial = self.conn.execute("SELECT COUNT(*) FROM leads WHERE status='trial_started'").fetchone()[0]
        human_seconds = self.conn.execute("SELECT COALESCE(SUM(human_seconds),0) FROM events").fetchone()[0]
        return {
            "discovered_candidates": discovered,
            "qualified_contact_channels": qualified,
            "approved_drafts": approved,
            "real_send_successes": real_sent,
            "smtp_accepted_not_delivery_confirmed": smtp_accepted,
            "delivery_unknown": delivery_unknown,
            "effective_replies": replies,
            "interested_or_trial": interested,
            "trials_started": trial,
            "average_human_review_seconds": 0 if approved == 0 else human_seconds / approved,
            "human_seconds_per_effective_lead": None if interested == 0 else human_seconds / interested,
            "status_counts": counts,
        }
