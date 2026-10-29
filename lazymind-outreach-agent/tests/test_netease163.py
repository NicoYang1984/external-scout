from __future__ import annotations

import email
import sqlite3
import sys
import tempfile
import unittest
from email import policy
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adapters import MockMailAdapter  # noqa: E402
from netease163 import (  # noqa: E402
    EnterpriseAccountRequiresSeparateConfiguration,
    MacOSKeychainCredentialStore,
    NetEase163MailAdapter,
    validate_personal_account,
)
from outreach_core import OutreachStore, SendResult, sha256_text, utcnow  # noqa: E402


class FakeSMTP:
    sent = 0
    logins = 0

    def __init__(self, *args, **kwargs):
        self.__class__.last_args = args
        self.args = args
        self.kwargs = kwargs

    def login(self, account, code):
        self.__class__.logins += 1
        return 235, b"ok"

    def send_message(self, message, **kwargs):
        self.__class__.sent += 1
        self.message = message
        return {}

    def quit(self):
        return 221, b"bye"


class FakeProbeIMAP:
    logins = 0

    def __init__(self, *args, **kwargs):
        self.__class__.last_args = args
        self.args = args
        self.kwargs = kwargs

    def login(self, account, code):
        self.__class__.logins += 1
        return "OK", [b"authenticated"]

    def logout(self):
        return "BYE", []

    def select(self, mailbox, readonly=True):
        assert mailbox == "INBOX" and readonly
        return "OK", [b"0"]


class FakeReplyIMAP(FakeProbeIMAP):
    def __init__(self, raw, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.raw = raw

    def select(self, mailbox, readonly=True):
        return "OK", [b"1"]

    def search(self, charset, *criteria):
        field = criteria[1]
        return ("OK", [b"7"]) if field == "In-Reply-To" else ("OK", [b""])

    def fetch(self, message_id, query):
        return "OK", [(b"7 (RFC822)", self.raw), b")"]


class UnknownOnceAdapter:
    provider_name = "netease163_personal"

    def __init__(self):
        self.calls = 0

    def send(self, **kwargs):
        self.calls += 1
        return SendResult(
            status="delivery_unknown", rfc_message_id="<unknown@163.com>",
            error="connection ended during SMTP submission", safe_to_retry=False,
        )


class NetEase163Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = OutreachStore(Path(self.tmp.name) / "outreach.sqlite3")
        self.store.init()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def lead(self, contact="partner@example.test"):
        return {
            "id": "lead-1", "organization": "Partner", "project_name": "Partner project",
            "campaign_type": "developer_collaboration", "source_kind": "official_web",
            "source_url": "https://example.test/partner", "pain_point": "A bounded compatibility study.",
            "evidence": [{"url": "https://example.test/partner", "finding": "Official channel"}],
            "contact_channel": "email", "contact_value": contact,
            "allowed_purpose": "research collaboration",
            "permission_status": "official_collaboration_channel",
            "permission_verified_at": "2026-10-28", "language": "en",
            "technical_fit": 8, "ecosystem_value": 7,
            "recommended_capability": "governed workflow observation",
            "case_links": ["https://github.com/LazyAGI/LazyMind/pull/873"],
            "risk_notes": "No endorsement claim.", "status": "qualified",
        }

    def body(self):
        return (
            "Your official page asks for bounded research collaboration on governed workflows. "
            "A small compatibility study could inspect step visibility and failure recovery. "
            "LazyMind can provide its existing observation surface without claiming production validation. "
            "Evidence: https://example.test/partner and case: https://github.com/LazyAGI/LazyMind/pull/873. "
            "We are the LazyMind project team, and the next step would only be a written test plan."
        )

    def approved(self):
        self.store.configure_sender(
            "owner@163.com", "netease163_personal", True, utcnow(),
            account_type="personal_163", connection_verified_at=utcnow(), live_enabled=True,
        )
        lead_id = self.store.upsert_lead(self.lead())
        draft_id = self.store.add_draft(lead_id, "Compatibility study", self.body(), "en")
        batch_id = self.store.create_batch("v1.1", "owner@163.com", [draft_id])
        self.store.approve_batch(batch_id, "owner")
        return lead_id, draft_id, batch_id

    def test_enterprise_account_is_rejected_before_personal_configuration(self):
        with self.assertRaises(EnterpriseAccountRequiresSeparateConfiguration):
            validate_personal_account("owner@company.com")
        with self.assertRaises(EnterpriseAccountRequiresSeparateConfiguration):
            validate_personal_account("owner@qiye.163.com")

    def test_probe_authenticates_both_servers_without_sending(self):
        FakeSMTP.sent = FakeSMTP.logins = FakeProbeIMAP.logins = 0
        adapter = NetEase163MailAdapter(
            "owner@163.com", "memory-only-code",
            smtp_factory=FakeSMTP, imap_factory=FakeProbeIMAP,
        )
        result = adapter.probe()
        self.assertTrue(result.smtp_authenticated and result.imap_authenticated)
        self.assertEqual(FakeSMTP.logins, 1)
        self.assertEqual(FakeProbeIMAP.logins, 1)
        self.assertEqual(FakeSMTP.sent, 0)
        self.assertEqual(FakeSMTP.last_args[:2], ("smtp.163.com", 465))
        self.assertEqual(FakeProbeIMAP.last_args[:2], ("imap.163.com", 993))

    def test_utf8_mime_preserves_chinese_subject_body_and_link(self):
        message = NetEase163MailAdapter.build_message(
            to="owner@163.com", sender="owner@163.com", subject="中文主题",
            body="中文正文 https://github.com/LazyAGI/LazyMind",
        )
        parsed = email.message_from_bytes(message.as_bytes(), policy=policy.default)
        self.assertEqual(parsed["Subject"], "中文主题")
        self.assertIn("中文正文", parsed.get_content())
        self.assertIn("https://github.com/LazyAGI/LazyMind", parsed.get_content())
        self.assertEqual(parsed.get_content_charset(), "utf-8")

    def test_reply_reader_correlates_message_id_and_sender(self):
        reply = EmailMessage()
        reply["From"] = "Partner <partner@example.test>"
        reply["To"] = "owner@163.com"
        reply["Subject"] = "Re: Compatibility"
        reply["Message-ID"] = "<reply@example.test>"
        reply["In-Reply-To"] = "<original@163.com>"
        reply.set_content("Interested — can you share the test plan?")
        factory = lambda *args, **kwargs: FakeReplyIMAP(reply.as_bytes(), *args, **kwargs)
        adapter = NetEase163MailAdapter(
            "owner@163.com", "memory-only-code", imap_factory=factory,
        )
        found = adapter.read_replies("<original@163.com>", expected_from="partner@example.test")
        self.assertEqual(len(found), 1)
        self.assertIn("test plan", found[0]["body_excerpt"])
        self.assertEqual(
            adapter.read_replies("<original@163.com>", expected_from="other@example.test"), []
        )

    def test_recipient_change_invalidates_approval(self):
        _, _, batch_id = self.approved()
        self.store.upsert_lead(self.lead(contact="changed@example.test"))
        with self.assertRaisesRegex(ValueError, "lacks matching active approval"):
            self.store.send_batch(batch_id, MockMailAdapter(), "simulated")

    def test_delivery_unknown_is_not_blindly_retried(self):
        lead_id, _, batch_id = self.approved()
        adapter = UnknownOnceAdapter()
        first = self.store.send_batch(batch_id, adapter, "real")[0]
        second = self.store.send_batch(batch_id, adapter, "real")[0]
        self.assertEqual(first["status"], "delivery_unknown")
        self.assertEqual(second["status"], "delivery_unknown")
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(
            self.store.conn.execute("SELECT status FROM leads WHERE id=?", (lead_id,)).fetchone()[0],
            "delivery_unknown",
        )

    def test_abandoned_queued_request_requires_reconciliation_not_retry(self):
        _, draft_id, batch_id = self.approved()
        item = self.store.review_checklist(batch_id)[0]
        idem = sha256_text(f"{batch_id}:{draft_id}:{item['approval_fingerprint']}:real")
        now = utcnow()
        self.store.conn.execute("""
          INSERT INTO send_requests(idempotency_key,batch_id,draft_id,mode,content_hash,status,
          recipient_snapshot,subject_snapshot,created_at,updated_at)
          VALUES(?,?,?,?,?,'queued',?,?,?,?)
        """, (
            idem, batch_id, draft_id, "real", item["content_hash"],
            item["contact_value"], item["subject"], now, now,
        ))
        self.store.conn.commit()
        adapter = UnknownOnceAdapter()
        result = self.store.send_batch(batch_id, adapter, "real")[0]
        self.assertEqual(result["status"], "delivery_unknown")
        self.assertEqual(result["safe_to_retry"], 0)
        self.assertEqual(adapter.calls, 0)

    def test_keychain_save_never_places_secret_in_process_arguments(self):
        calls = []
        values = {}
        def save(service, account, value):
            calls.append("native_write")
            values[(service, account)] = value
        backend = SimpleNamespace(save=save, get=lambda service, account: values.get((service, account)))
        store = MacOSKeychainCredentialStore(backend=backend)
        with patch("subprocess.run") as subprocess_run:
            store.save("owner@163.com", "synthetic-code")
            subprocess_run.assert_not_called()
        self.assertEqual(calls, ["native_write"])
        self.assertEqual(store.get("owner@163.com"), "synthetic-code")

    def test_authorization_code_is_not_persisted_to_sqlite(self):
        self.store.configure_sender(
            "owner@163.com", "netease163_personal", True, utcnow(),
            account_type="personal_163", connection_verified_at=utcnow(),
            details={"credential_storage": "macos_keychain"},
        )
        secret = "a-unique-authorization-code"
        self.store.close()
        raw = (Path(self.tmp.name) / "outreach.sqlite3").read_bytes()
        self.assertNotIn(secret.encode(), raw)
        self.store = OutreachStore(Path(self.tmp.name) / "outreach.sqlite3")


if __name__ == "__main__":
    unittest.main()
