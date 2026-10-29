"""Regression tests for the real phase1 -> Keychain -> phase2 credential path."""
import io
import smtplib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import netease_cli
from netease163 import MacOSKeychainCredentialStore, NetEase163MailAdapter
from outreach_core import OutreachStore, SendResult


class CredentialRepairTests(unittest.TestCase):
    def run_session(self, *, storage_fails=False, read_fails=False, charset="utf-8", identity_matches=True):
        account, secret = "test@163.com", "synthetic-value-for-repair"
        observed = []
        class Backend:
            def get(self, *a):
                # repair deliberately ignores a stale existing value.
                return "wrong-old-value" if storage_fails else secret
            def save(self, *a):
                pass

        class Adapter:
            def __init__(self, account, code):
                self.code = code
                observed.append(("construct", code))
            def probe(self):
                observed.append(("probe", self.code))
                return SimpleNamespace(as_dict=lambda: {"smtp_authenticated": True, "imap_authenticated": True})
            def send(self, **kwargs):
                observed.append(("send", self.code))
                self.message_id = kwargs["rfc_message_id"]
                return SendResult(status="smtp_accepted", rfc_message_id=kwargs["rfc_message_id"])
            def find_inbox_message(self, *a):
                if read_fails:
                    raise OSError("synthetic IMAP failure")
                return [{"subject": netease_cli.TEST_SUBJECT, "body_excerpt": netease_cli.TEST_BODY,
                         "from": account, "to": account,
                         "provider_message_id": self.message_id if identity_matches else "<other@163.com>",
                         "mime_charset": charset, "mime_content_type": "text/plain"}]
            list_sent = find_inbox_message

        with tempfile.TemporaryDirectory() as directory:
            store = OutreachStore(Path(directory) / "test.sqlite3")
            store.init()
            output = io.StringIO()
            try:
                with patch("netease163.NativeKeychain", return_value=Backend()), \
                     patch("netease_cli.prompt_authorization_code", return_value=secret) as prompt, \
                     patch("netease_cli.NetEase163MailAdapter", Adapter), \
                     patch("builtins.input", return_value=f"SEND TEST TO {account}"), \
                     patch("sys.stdout", output):
                    session = netease_cli.verified_session(store, account, repair=True)
                    report = netease_cli.phase2(store, account, 0, session=session, owner_target=True)
                    # Second run only reconciles the existing submission.
                    repeat = netease_cli.phase2(store, account, 0, session=session, owner_target=True)
                prompt.assert_called_once()
                self.assertEqual(observed, [("construct", secret), ("probe", secret), ("send", secret)])
                self.assertTrue(repeat["reconciled_without_resend"])
                self.assertNotIn(secret, output.getvalue())
                self.assertNotIn(secret, "\n".join(store.conn.iterdump()))
                self.assertEqual(bool(store.conn.execute("SELECT live_enabled FROM sender_accounts WHERE account=?", (account,)).fetchone()[0]),
                                 not read_fails and charset == "utf-8" and identity_matches)
                return session.report, report
            finally:
                store.close()

    def test_repair_reuses_verified_credential_across_both_phases(self):
        phase1, phase2 = self.run_session()
        self.assertTrue(phase1["keychain_readback_verified"])
        self.assertTrue(phase2["inbox_found"] and phase2["sent_folder_found"])

    def test_wrong_keychain_readback_uses_memory_without_claiming_saved(self):
        phase1, phase2 = self.run_session(storage_fails=True)
        self.assertFalse(phase1["keychain_readback_verified"])
        self.assertEqual(phase1["credential_source"], "memory_only")
        self.assertTrue(phase2["inbox_found"])

    def test_wrong_mime_charset_cannot_pass_self_test(self):
        _, report = self.run_session(charset="gb2312")
        self.assertFalse(report["mime_checks"]["utf8_plain_text"])
        self.assertFalse(report["owner_inbox_receipt_verified"])

    def test_search_result_with_different_message_id_cannot_pass(self):
        _, report = self.run_session(identity_matches=False)
        self.assertFalse(report["mime_checks"]["exact_message_identity"])
        self.assertFalse(report["owner_inbox_receipt_verified"])

    def test_imap_error_after_acceptance_does_not_cause_duplicate_test_send(self):
        _, phase2 = self.run_session(read_fails=True)
        self.assertEqual(phase2["smtp_result"], "smtp_accepted")
        self.assertFalse(phase2["inbox_found"])
        self.assertEqual(phase2["imap_error_type"], "OSError")

    def test_successful_write_must_verify_readback(self):
        # Old security tool may exit zero while storing a different terminal input.
        keychain = MacOSKeychainCredentialStore(
            backend=SimpleNamespace(save=lambda *a: None)
        )
        with patch.object(keychain, "get", return_value="different-synthetic-value"):
            with self.assertRaisesRegex(RuntimeError, "verification"):
                keychain.save("test@163.com", "synthetic-value")

    def test_535_is_explicitly_authentication_failure_before_send(self):
        class SMTP:
            def __init__(self, *a, **k):
                pass

            def login(self, *a):
                raise smtplib.SMTPAuthenticationError(535, b"auth rejected")

            def send_message(self, *a, **k):
                raise AssertionError("must not submit after authentication rejection")

            def quit(self):
                pass

        result = NetEase163MailAdapter(
            "test@163.com", "synthetic-value", smtp_factory=SMTP
        ).send(to="test@163.com", sender="test@163.com", subject="test",
               body="test", idempotency_key="test")
        self.assertEqual(result.details.get("stage"), "authenticate")
        self.assertFalse(result.details["message_submitted"])
        self.assertIn("authentication", result.error)

    def test_noninteractive_secret_input_never_falls_back_to_echo(self):
        from netease163 import load_authorization_code
        with patch("sys.stdin", new=io.StringIO()), \
             patch("netease163.getpass.getpass") as getpass:
            with self.assertRaisesRegex(RuntimeError, "interactive"):
                load_authorization_code("test@163.com", keychain=SimpleNamespace(get=lambda _: None))
            getpass.assert_not_called()


if __name__ == "__main__":
    unittest.main()
