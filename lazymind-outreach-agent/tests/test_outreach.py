from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adapters import MockMailAdapter  # noqa: E402
from outreach_core import OutreachStore  # noqa: E402
from scout_adapter import file_sha256, import_scout  # noqa: E402


class OutreachTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = OutreachStore(self.root / "outreach.sqlite3")
        self.store.init()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def lead(self, **changes):
        source = changes.pop("source_url", "https://example.test/collaborate")
        payload = {
            "organization": "Example Org",
            "project_name": "Example Project",
            "campaign_type": "developer_collaboration",
            "source_kind": "official_web",
            "source_url": source,
            "pain_point": "The project requests bounded compatibility tests for governed agent workflows.",
            "evidence": [{"url": source, "finding": "Official collaboration invitation"}],
            "contact_channel": "email",
            "contact_value": "partners@example.test",
            "allowed_purpose": "research collaboration",
            "permission_status": "official_collaboration_channel",
            "permission_verified_at": "2026-10-28",
            "language": "en",
            "technical_fit": 8,
            "ecosystem_value": 6,
            "recommended_capability": "workflow observation",
            "case_links": ["https://github.com/LazyAGI/LazyMind/pull/873"],
            "risk_notes": "Do not claim production validation.",
            "status": "qualified",
        }
        payload.update(changes)
        return payload

    def draft_body(self, marker="specific"):
        return (
            f"Your official collaboration page describes {marker} governed execution as an open area. "
            "A bounded workflow could compare step visibility and failure recovery without claiming an upstream endorsement. "
            "LazyMind can provide its existing observation surface, with the known limits documented in the case. "
            "Evidence: https://example.test/collaborate and case: https://github.com/LazyAGI/LazyMind/pull/873. "
            "We are the LazyMind team; this is a compatibility-test proposal, not a claim of successful deployment. "
            "Would a short written test plan be appropriate for your collaboration channel?"
        )

    def make_approved(self, **lead_changes):
        self.store.configure_sender("authorized@example.test", "mock", True, "2026-10-28")
        lead_id = self.store.upsert_lead(self.lead(**lead_changes))
        draft_id = self.store.add_draft(lead_id, "Bounded compatibility test", self.draft_body(), "en")
        batch_id = self.store.create_batch("test", "authorized@example.test", [draft_id])
        self.store.approve_batch(batch_id, "reviewer")
        return lead_id, draft_id, batch_id

    def test_duplicate_email_and_project_are_deduplicated(self):
        self.store.upsert_lead(self.lead())
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.upsert_lead(self.lead(
                id="different", organization="Other Org", contact_value="PARTNERS@example.test"
            ))

    def test_same_organization_multiple_channels_blocked_in_batch(self):
        first = self.store.upsert_lead(self.lead(id="one"))
        second = self.store.upsert_lead(self.lead(
            id="two", contact_channel="form", contact_value="https://example.test/form",
            campaign_type="editorial_pitch", permission_status="official_submission_channel",
        ))
        d1 = self.store.add_draft(first, "One", self.draft_body("one"), "en")
        d2 = self.store.add_draft(second, "Two", self.draft_body("two"), "en")
        with self.assertRaisesRegex(ValueError, "same organization"):
            self.store.create_batch("dup", "authorized@example.test", [d1, d2])

    def test_nationality_is_never_inferred_or_stored(self):
        with self.assertRaisesRegex(ValueError, "forbidden inferred"):
            self.store.upsert_lead(self.lead(nationality="guessed"))
        columns = {row[1] for row in self.store.conn.execute("PRAGMA table_info(leads)")}
        self.assertFalse({"nationality", "ethnicity", "race"}.intersection(columns))

    def test_missing_permission_cannot_be_approved(self):
        lead_id = self.store.upsert_lead(self.lead(permission_status="not_granted"))
        draft_id = self.store.add_draft(lead_id, "Test", self.draft_body(), "en")
        batch_id = self.store.create_batch("blocked", "authorized@example.test", [draft_id])
        with self.assertRaisesRegex(ValueError, "not sendable"):
            self.store.approve_batch(batch_id, "reviewer")

    def test_content_change_invalidates_old_approval(self):
        _, draft_id, batch_id = self.make_approved()
        old_hash = self.store.conn.execute("SELECT content_hash FROM drafts WHERE id=?", (draft_id,)).fetchone()[0]
        new_hash = self.store.update_draft(draft_id, "Changed", self.draft_body("changed") + " More detail.")
        self.assertNotEqual(old_hash, new_hash)
        active = self.store.conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE draft_id=? AND revoked_at IS NULL", (draft_id,)
        ).fetchone()[0]
        self.assertEqual(active, 0)
        with self.assertRaisesRegex(ValueError, "lacks matching"):
            self.store.send_batch(batch_id, MockMailAdapter(), "simulated")

    def test_failed_send_recovers_and_is_idempotent(self):
        _, _, batch_id = self.make_approved()
        adapter = MockMailAdapter(fail_once=True)
        first = self.store.send_batch(batch_id, adapter, "simulated")[0]
        self.assertEqual(first["status"], "failed")
        second = self.store.send_batch(batch_id, adapter, "simulated")[0]
        self.assertEqual(second["status"], "succeeded")
        third = self.store.send_batch(batch_id, adapter, "simulated")[0]
        self.assertEqual(third["provider_message_id"], second["provider_message_id"])
        attempts = self.store.conn.execute("SELECT COUNT(*) FROM send_attempts").fetchone()[0]
        self.assertEqual(attempts, 2)

    def test_decline_immediately_suppresses_organization(self):
        lead_id = self.store.upsert_lead(self.lead())
        category = self.store.record_reply(lead_id, "No thanks, we are not interested.")
        self.assertEqual(category, "declined")
        status = self.store.conn.execute("SELECT status FROM leads WHERE id=?", (lead_id,)).fetchone()[0]
        self.assertEqual(status, "suppressed")
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM suppressions").fetchone()[0], 1)

    def test_simulated_and_real_results_are_strictly_distinct(self):
        lead_id, _, batch_id = self.make_approved()
        result = self.store.send_batch(batch_id, MockMailAdapter(), "simulated")[0]
        self.assertEqual(result["mode"], "simulated")
        status = self.store.conn.execute("SELECT status,last_contact_at FROM leads WHERE id=?", (lead_id,)).fetchone()
        self.assertEqual(status[0], "approved")
        self.assertIsNone(status[1])
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            self.store.send_batch(batch_id, MockMailAdapter(), "real")
        self.assertEqual(self.store.metrics()["real_send_successes"], 0)

    def test_scout_database_remains_byte_identical(self):
        path = self.root / "scout.sqlite3"
        conn = sqlite3.connect(path)
        conn.executescript("""
          PRAGMA user_version=2;
          CREATE TABLE opportunities(url TEXT PRIMARY KEY,updated_at TEXT,next_review_at TEXT,payload TEXT);
          CREATE TABLE history(id INTEGER PRIMARY KEY,url TEXT,recorded_at TEXT,payload TEXT);
          CREATE TABLE source_items(entity_key TEXT PRIMARY KEY,payload TEXT,updated_at TEXT);
        """)
        payload = {
            "url": "https://github.com/example/project", "repo": "example/project",
            "title": "Compatibility", "summary": "A bounded test", "score": 8,
            "ecosystem_value": {"user_value": 2, "collaboration": 1, "audience_evidence": 1},
            "sources": [{"url": "https://github.com/example/project", "finding": "public"}],
            "outreach_permission": "not_granted", "capability_ids": ["workflow_observation"],
        }
        conn.execute(
            "INSERT INTO opportunities VALUES(?,?,?,?)",
            (payload["url"], "2026-10-28", "2026-11-04", json.dumps(payload)),
        )
        conn.commit()
        conn.close()
        before = file_sha256(path)
        result = import_scout(self.store, path)
        after = file_sha256(path)
        self.assertTrue(result["unchanged"])
        self.assertEqual(before, after)
        permission = self.store.conn.execute(
            "SELECT permission_status FROM leads WHERE scout_source_id IS NOT NULL"
        ).fetchone()[0]
        self.assertEqual(permission, "not_granted")


if __name__ == "__main__":
    unittest.main()
