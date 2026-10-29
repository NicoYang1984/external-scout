"""Regressions reproduced against the owner's NetEase IMAP service."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from netease163 import NetEase163MailAdapter


class IdentityIMAP:
    capabilities = ("IMAP4REV1", "ID", "SPECIAL-USE")

    def __init__(self, sent_name='&XfJT0ZAB-'):
        self.identified = False
        self.events = []
        self.sent_name = sent_name

    def login(self, account, code):
        self.events.append("login")
        return "OK", []

    def xatom(self, command, payload):
        self.events.append(command)
        assert command == "ID"
        assert '"lazymind-outreach-agent"' in payload
        assert "synthetic-secret" not in payload
        self.identified = True
        return "OK", []

    def select(self, name, readonly=True):
        assert readonly
        self.events.append(("select", name))
        if not self.identified:
            return "NO", [b"EXAMINE Unsafe Login"]
        assert name in ('INBOX', '"' + self.sent_name + '"')
        return "OK", [b"0"]

    def list(self):
        return "OK", [f'(\\Sent) "/" "{self.sent_name}"'.encode("ascii")]

    def search(self, *args):
        return "OK", [b""]

    def logout(self):
        return "BYE", []


class IMAPCompatibilityTests(unittest.TestCase):
    def adapter(self, mailbox):
        return NetEase163MailAdapter("owner@163.com", "synthetic-secret", imap_factory=lambda *a, **k: mailbox)

    def test_identity_handshake_precedes_inbox_selection(self):
        mailbox = IdentityIMAP()
        self.assertEqual(self.adapter(mailbox).find_inbox_message("<test@163.com>"), [])
        self.assertEqual(mailbox.events[:3], ["login", "ID", ("select", "INBOX")])

    def test_reply_reader_also_identifies_itself(self):
        mailbox = IdentityIMAP()
        self.assertEqual(self.adapter(mailbox).read_replies("<test@163.com>"), [])
        self.assertEqual(mailbox.events[:3], ["login", "ID", ("select", "INBOX")])

    def test_sent_uses_server_encoded_name_without_guessing_chinese_folder(self):
        mailbox = IdentityIMAP()
        self.assertEqual(self.adapter(mailbox).list_sent("<test@163.com>"), [])
        self.assertEqual(mailbox.events, ["login", "ID", ("select", '"&XfJT0ZAB-"')])

    def test_sent_mailbox_with_spaces_is_quoted(self):
        mailbox = IdentityIMAP("Sent Messages")
        self.assertEqual(self.adapter(mailbox).list_sent("<test@163.com>"), [])
        self.assertIn(("select", '"Sent Messages"'), mailbox.events)

    def test_rejected_inbox_is_reported_instead_of_being_treated_as_empty(self):
        mailbox = IdentityIMAP()
        mailbox.select = lambda *a, **k: ("NO", [b"policy rejection"])
        with self.assertRaisesRegex(RuntimeError, "INBOX"):
            self.adapter(mailbox).find_inbox_message("<test@163.com>")

    def test_rejected_client_identity_stops_before_mailbox_read(self):
        mailbox = IdentityIMAP()
        mailbox.xatom = lambda *a: ("NO", [])
        with self.assertRaisesRegex(RuntimeError, "identification"):
            self.adapter(mailbox).find_inbox_message("<test@163.com>")
        self.assertEqual(mailbox.events, ["login"])


if __name__ == "__main__":
    unittest.main()
