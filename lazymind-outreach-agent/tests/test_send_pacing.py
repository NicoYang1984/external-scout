"""Offline dispatch tests: no socket, Keychain access, or real mail."""
import io
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from adapters import MockMailAdapter
from netease_cli import build_parser, send_approved_batch
from outreach_core import OutreachStore, SendResult


class AcceptedAdapter:
    provider_name = "netease163_personal"

    def __init__(self):
        self.calls = []

    def send(self, **kwargs):
        self.calls.append(kwargs)
        return SendResult(status="smtp_accepted", rfc_message_id=f"<{len(self.calls)}@example.test>", safe_to_retry=False)


class SendPacingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "outreach.sqlite3"
        self.store = OutreachStore(self.path)
        self.store.init()
        self.account = "owner@163.com"
        self.store.configure_sender(self.account, "netease163_personal", True, "2026-10-28",
                                    account_type="personal_163", connection_verified_at="2026-10-28", live_enabled=True)
        self.now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
        self.clock = patch("outreach_core.pacing_now", side_effect=lambda: self.now)
        self.clock.start()
        self.adapter = AcceptedAdapter()
        self.next_id = 0

    def tearDown(self):
        self.clock.stop()
        self.store.close()
        self.tmp.cleanup()

    def batch(self, count=2, approve=True, language="en"):
        leads, drafts = [], []
        for _ in range(count):
            i = self.next_id
            self.next_id += 1
            lead = self.store.upsert_lead({
                "organization": f"Partner {i}", "project_name": f"Project {i}",
                "campaign_type": "developer_collaboration", "source_kind": "official_web",
                "source_url": "https://example.test/collaborate", "pain_point": "A bounded compatibility study",
                "evidence": [{"url": "https://example.test/collaborate", "finding": "Official collaboration invitation"}],
                "contact_channel": "email", "contact_value": f"partner{i}@example.test",
                "allowed_purpose": "research collaboration", "permission_status": "official_collaboration_channel",
                "permission_verified_at": "2026-10-28", "language": language,
                "technical_fit": 8, "ecosystem_value": 7, "recommended_capability": "workflow observation",
                "case_links": [], "risk_notes": "No endorsement claim", "status": "qualified",
            })
            body = (f"Project {i} has an evidenced need for a bounded compatibility study. "
                    "We propose using public inputs to test observable recovery and report failures. "
                    "LazyMind can provide an open-source workflow observation surface; we have not tested compatibility. "
                    "Evidence: https://example.test/collaborate. We represent the project; would a written plan be appropriate?")
            draft = self.store.add_draft(lead, f"Study {i}", body, "en")
            leads.append(lead)
            drafts.append(draft)
        batch = self.store.create_batch(f"pacing-{self.next_id}", self.account, drafts)
        if approve:
            self.store.approve_batch(batch, "synthetic-reviewer")
        return batch, leads, drafts

    def test_default_interval_defers_then_resumes_without_resending(self):
        batch, _, _ = self.batch()
        first = self.store.send_batch(batch, self.adapter, "real")
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(first[-1]["status"], "deferred_rate_limit")
        self.assertEqual(first[-1]["retry_after_seconds"], 300)
        self.store.send_batch(batch, self.adapter, "real")
        self.assertEqual(len(self.adapter.calls), 1)
        self.now += timedelta(seconds=300)
        self.store.send_batch(batch, self.adapter, "real")
        reserved = self.store.get_send_pacing(self.account)
        self.store.send_batch(batch, self.adapter, "real")
        self.assertEqual(len(self.adapter.calls), 2)
        self.assertEqual(reserved, self.store.get_send_pacing(self.account))
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM send_attempts").fetchone()[0], 2)

    def test_cooldown_survives_restart_and_applies_across_batches(self):
        first, _, _ = self.batch(1)
        second, _, _ = self.batch(1)
        self.store.send_batch(first, self.adapter, "real")
        self.store.close()
        self.store = OutreachStore(self.path)
        self.store.init()
        result = self.store.send_batch(second, self.adapter, "real")
        self.assertEqual(result[0]["status"], "deferred_rate_limit")
        self.assertEqual(len(self.adapter.calls), 1)

    def test_other_connection_cannot_take_a_reserved_slot(self):
        first, _, _ = self.batch(1)
        second, _, _ = self.batch(1)
        other = OutreachStore(self.path)
        observed = []
        original = self.adapter.send
        def during_send(**kwargs):
            observed.extend(other.send_batch(second, AcceptedAdapter(), "real"))
            return original(**kwargs)
        try:
            with patch.object(self.adapter, "send", side_effect=during_send):
                self.store.send_batch(first, self.adapter, "real")
            self.assertEqual(observed[0]["status"], "deferred_rate_limit")
        finally:
            other.close()

    def test_missing_approval_does_not_consume_slot(self):
        batch, _, _ = self.batch(approve=False)
        with self.assertRaisesRegex(ValueError, "approval"):
            self.store.send_batch(batch, self.adapter, "real")
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM send_pacing").fetchone()[0], 0)
        self.assertEqual(self.adapter.calls, [])

    def test_simulation_does_not_consume_real_cooldown(self):
        batch, _, _ = self.batch()
        results = self.store.send_batch(batch, MockMailAdapter(), "simulated")
        self.assertEqual(len(results), 2)
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM send_pacing").fetchone()[0], 0)

    def test_changed_content_during_cooldown_is_blocked(self):
        batch, _, drafts = self.batch()
        self.store.send_batch(batch, self.adapter, "real")
        self.store.update_draft(drafts[1], "Changed", "This text was not approved.")
        self.now += timedelta(seconds=300)
        with self.assertRaisesRegex(ValueError, "approval"):
            self.store.send_batch(batch, self.adapter, "real")
        self.assertEqual(len(self.adapter.calls), 1)

    def test_suppression_during_cooldown_is_blocked(self):
        batch, leads, _ = self.batch()
        self.store.send_batch(batch, self.adapter, "real")
        self.store.suppress(leads[1], "declined")
        self.now += timedelta(seconds=300)
        with self.assertRaisesRegex(ValueError, "suppressed"):
            self.store.send_batch(batch, self.adapter, "real")
        self.assertEqual(len(self.adapter.calls), 1)

    def test_account_revocation_during_cooldown_is_blocked(self):
        batch, _, _ = self.batch()
        self.store.send_batch(batch, self.adapter, "real")
        self.store.conn.execute("UPDATE sender_accounts SET authorized=0")
        self.store.conn.commit()
        self.now += timedelta(seconds=300)
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            self.store.send_batch(batch, self.adapter, "real")
        self.assertEqual(len(self.adapter.calls), 1)

    def test_config_validates_and_cannot_shorten_existing_cooldown(self):
        for invalid in (0, -1, 30, 86401, 1.5, True):
            with self.assertRaises(ValueError):
                self.store.set_send_interval(self.account, invalid)
        self.store.set_send_interval(self.account, 900)
        batch, _, _ = self.batch(1)
        self.store.send_batch(batch, self.adapter, "real")
        original = self.store.get_send_pacing(self.account)["next_allowed_at"]
        self.assertEqual(self.store.set_send_interval(self.account, 60)["next_allowed_at"], original)
        extended = self.store.set_send_interval(self.account, 1200)["next_allowed_at"]
        self.assertEqual(datetime.fromisoformat(extended), self.now + timedelta(seconds=1200))

    def test_provider_error_stops_batch_and_preserves_cooldown(self):
        batch, _, _ = self.batch()
        with patch.object(self.adapter, "send", return_value=SendResult(status="failed", safe_to_retry=True)) as send:
            first = self.store.send_batch(batch, self.adapter, "real")
            self.assertEqual(first[0]["status"], "failed")
            self.assertEqual(send.call_count, 1)
            second = self.store.send_batch(batch, self.adapter, "real")
            self.assertEqual(second[0]["status"], "deferred_rate_limit")
            self.assertEqual(send.call_count, 1)

    def test_unhandled_provider_error_is_uncertain_not_auto_retryable(self):
        batch, _, _ = self.batch()
        with patch.object(self.adapter, "send", side_effect=OSError("synthetic-private-detail")) as send:
            results = self.store.send_batch(batch, self.adapter, "real")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(results[0]["status"], "delivery_unknown")
        self.assertEqual(results[0]["safe_to_retry"], 0)
        self.assertNotIn("synthetic-private-detail", str(results))

    def test_cli_waits_in_short_chunks_and_confirms_only_once(self):
        batch, _, _ = self.batch()
        pauses = []
        def sleep(seconds):
            pauses.append(seconds)
            self.now += timedelta(seconds=seconds)
        with patch("netease_cli.load_authorization_code", return_value=("synthetic-code", "test")), \
             patch("netease_cli.NetEase163MailAdapter", return_value=self.adapter), \
             patch("netease_cli.time.monotonic", side_effect=lambda: self.now.timestamp()), \
             patch("netease_cli.time.sleep", side_effect=sleep), \
             patch("builtins.input", return_value=f"SEND APPROVED BATCH {batch}") as confirm, \
             patch("sys.stdout", new=io.StringIO()):
            result = send_approved_batch(self.store, self.account, batch, wait_for_interval=True)
        confirm.assert_called_once()
        self.assertFalse(result["pending_cooldown"])
        self.assertEqual(len(self.adapter.calls), 2)
        self.assertEqual(sum(pauses), 300)
        self.assertLessEqual(max(pauses), 30)
        self.assertTrue(build_parser().parse_args(["send-batch", "--batch-id", batch, "--wait-for-interval"]).wait_for_interval)

    def test_unknown_language_cannot_be_overridden_when_drafting(self):
        with self.assertRaisesRegex(ValueError, "language is unknown"):
            self.batch(language="language_unknown")


if __name__ == "__main__":
    unittest.main()
