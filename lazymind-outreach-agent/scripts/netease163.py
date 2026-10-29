#!/usr/bin/env python3
"""Controlled SMTP/IMAP adapter for personal ``@163.com`` mailboxes.

The authorization code is accepted only in memory.  It is never returned in a
result object and this module never writes it to SQLite or a log.
"""

from __future__ import annotations

import email
import getpass
import hmac
import imaplib
import re
import smtplib
import ssl
import sys
import warnings
from dataclasses import dataclass
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.utils import make_msgid, parseaddr
from typing import Any, Callable, Dict, List, Optional, Sequence

from adapters import MailAdapter
from outreach_core import SendResult
from macos_keychain import KeychainAccessError, NativeKeychain


SMTP_HOST = "smtp.163.com"
SMTP_PORT = 465
IMAP_HOST = "imap.163.com"
IMAP_PORT = 993
KEYCHAIN_SERVICE = "lazymind-outreach-agent:netease163"


class EnterpriseAccountRequiresSeparateConfiguration(ValueError):
    """Raised when personal 163 settings would be unsafe for the account."""


def validate_personal_account(account: str) -> str:
    normalized = account.strip().casefold()
    if normalized.count("@") != 1 or not normalized.endswith("@163.com"):
        raise EnterpriseAccountRequiresSeparateConfiguration(
            "personal NetEase settings apply only to exact @163.com accounts; "
            "enterprise mail hosts must be validated separately"
        )
    return normalized


class MacOSKeychainCredentialStore:
    """Use native SecItem calls and verify every write by reading it back."""

    def __init__(self, service: str = KEYCHAIN_SERVICE, backend: Any = None):
        self.service = service
        self.backend = backend

    def _native(self):
        if self.backend is None:
            self.backend = NativeKeychain()
        return self.backend

    def get(self, account: str) -> Optional[str]:
        return self._native().get(self.service, account)

    def save(self, account: str, authorization_code: str) -> None:
        self._native().save(self.service, account, authorization_code)
        readback = self.get(account)
        if readback is None or not hmac.compare_digest(
            readback.encode("utf-8"), authorization_code.encode("utf-8")
        ):
            raise RuntimeError("Keychain verification failed: saved value does not match")

    def delete(self, account: str) -> None:
        self._native().delete(self.service, account)


def prompt_authorization_code() -> str:
    if not sys.stdin.isatty():
        raise RuntimeError("authorization code requires an interactive terminal with hidden input")
    with warnings.catch_warnings():
        # Never let getpass's fallback echo a credential to logs or a terminal.
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            value = getpass.getpass("163 客户端授权码（输入不会显示）: ")
        except getpass.GetPassWarning:
            raise RuntimeError("interactive terminal cannot provide hidden input") from None
    if not value or any(ch.isspace() for ch in value):
        raise ValueError("authorization code is empty or contains whitespace; re-enter without spaces")
    return value


def load_authorization_code(
    account: str,
    *,
    keychain: Optional[MacOSKeychainCredentialStore] = None,
    allow_prompt: bool = True,
) -> tuple[str, str]:
    """Return an in-memory authorization code and its non-secret source label."""
    store = keychain or MacOSKeychainCredentialStore()
    value = store.get(account)
    if value:
        return value, "macos_keychain"
    if not allow_prompt:
        raise RuntimeError("authorization code is not present in macOS Keychain")
    return prompt_authorization_code(), "interactive_prompt"


def _decoded_header(value: Optional[str]) -> str:
    return str(make_header(decode_header(value or "")))


def _plain_text(message: Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                try:
                    return part.get_content()
                except Exception:
                    payload = part.get_payload(decode=True) or b""
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    try:
        return message.get_content()
    except Exception:
        payload = message.get_payload(decode=True) or b""
        return payload.decode(message.get_content_charset() or "utf-8", errors="replace")


@dataclass(frozen=True)
class ConnectionProbe:
    account: str
    smtp_host: str
    smtp_port: int
    imap_host: str
    imap_port: int
    smtp_authenticated: bool
    imap_authenticated: bool
    imap_mailbox_readable: bool

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


class NetEase163MailAdapter(MailAdapter):
    """Personal 163 adapter with explicit uncertainty and reply correlation."""

    provider_name = "netease163_personal"
    supports_live_send = True

    def __init__(
        self,
        account: str,
        authorization_code: str,
        *,
        smtp_factory: Callable[..., Any] = smtplib.SMTP_SSL,
        imap_factory: Callable[..., Any] = imaplib.IMAP4_SSL,
        ssl_context: Optional[ssl.SSLContext] = None,
        timeout: int = 30,
    ):
        self.account = validate_personal_account(account)
        if not authorization_code:
            raise ValueError("authorization code is required in memory")
        self._authorization_code = authorization_code
        self._smtp_factory = smtp_factory
        self._imap_factory = imap_factory
        self._ssl_context = ssl_context or ssl.create_default_context()
        self.timeout = timeout

    def _smtp(self) -> Any:
        return self._smtp_factory(
            SMTP_HOST, SMTP_PORT, context=self._ssl_context, timeout=self.timeout
        )

    def _imap(self) -> Any:
        return self._imap_factory(
            IMAP_HOST, IMAP_PORT, ssl_context=self._ssl_context, timeout=self.timeout
        )

    def _login_imap(self, mailbox: Any) -> None:
        status, _ = mailbox.login(self.account, self._authorization_code)
        if str(status).upper() != "OK":
            raise RuntimeError("IMAP authentication did not return OK")
        capabilities = {
            (item.decode("ascii") if isinstance(item, bytes) else item).upper()
            for item in getattr(mailbox, "capabilities", ())
        }
        if "ID" in capabilities:
            # RFC 2971: truthful implementation identity only, no user data or secrets.
            status, _ = mailbox.xatom(
                "ID", '("name" "lazymind-outreach-agent" "version" "1.1")'
            )
            if str(status).upper() != "OK":
                raise RuntimeError("IMAP client identification failed")

    @staticmethod
    def build_message(*, to: str, subject: str, body: str, sender: str, rfc_message_id: Optional[str] = None) -> EmailMessage:
        message = EmailMessage()
        message["From"] = sender
        message["To"] = to
        message["Subject"] = subject
        message["Message-ID"] = rfc_message_id or make_msgid(domain="163.com")
        message["X-LazyMind-Outreach"] = "controlled-v1.1"
        message.set_content(body, subtype="plain", charset="utf-8")
        return message

    def probe(self) -> ConnectionProbe:
        """Authenticate to both servers without submitting a message."""
        smtp = self._smtp()
        try:
            smtp.login(self.account, self._authorization_code)
        finally:
            try:
                smtp.quit()
            except Exception:
                pass
        imap = self._imap()
        try:
            self._login_imap(imap)
            status, _ = imap.select("INBOX", readonly=True)
            if str(status).upper() != "OK":
                raise RuntimeError("cannot select INBOX after IMAP authentication")
        finally:
            try:
                imap.logout()
            except Exception:
                pass
        return ConnectionProbe(
            self.account, SMTP_HOST, SMTP_PORT, IMAP_HOST, IMAP_PORT, True, True, True
        )

    def create_draft(self, *, to: str, subject: str, body: str, sender: str) -> Dict[str, Any]:
        if validate_personal_account(sender) != self.account:
            raise ValueError("sender must equal the authenticated personal 163 account")
        message = self.build_message(to=to, subject=subject, body=body, sender=sender)
        return {
            "mode": "local_mime_preview",
            "to": to,
            "subject": subject,
            "sender": sender,
            "rfc_message_id": message["Message-ID"],
        }

    def send(self, *, to: str, subject: str, body: str, sender: str, idempotency_key: str, rfc_message_id: Optional[str] = None) -> SendResult:
        del idempotency_key  # provider does not offer an idempotency API
        if validate_personal_account(sender) != self.account:
            return SendResult(status="failed", error="sender/account mismatch", safe_to_retry=True)
        message = self.build_message(to=to, subject=subject, body=body, sender=sender, rfc_message_id=rfc_message_id)
        rfc_message_id = str(message["Message-ID"])
        smtp = None
        stage = "connect"
        try:
            smtp = self._smtp()
            stage = "authenticate"
            smtp.login(self.account, self._authorization_code)
            stage = "submit"
            refused = smtp.send_message(message, from_addr=self.account, to_addrs=[to])
            if refused:
                return SendResult(
                    status="failed", error="SMTP rejected one or more recipients",
                    rfc_message_id=rfc_message_id, safe_to_retry=True,
                    details={"refused_recipient_count": len(refused)},
                )
            return SendResult(
                status="smtp_accepted", provider_message_id=rfc_message_id,
                rfc_message_id=rfc_message_id, safe_to_retry=False,
                details={"delivery_confirmed": False},
            )
        except smtplib.SMTPAuthenticationError as exc:
            return SendResult(
                status="failed", error=f"SMTP authentication failed ({exc.smtp_code}); message not submitted",
                rfc_message_id=rfc_message_id, safe_to_retry=True,
                details={"smtp_code": int(exc.smtp_code), "stage": "authenticate", "message_submitted": False},
            )
        except smtplib.SMTPRecipientsRefused:
            return SendResult(
                status="failed", error="SMTP rejected all recipients",
                rfc_message_id=rfc_message_id, safe_to_retry=True,
            )
        except smtplib.SMTPResponseException as exc:
            return SendResult(
                status="failed", error=f"SMTP rejected request ({exc.smtp_code})",
                rfc_message_id=rfc_message_id, safe_to_retry=True,
                details={"smtp_code": int(exc.smtp_code), "stage": stage},
            )
        except Exception as exc:
            if stage == "submit":
                return SendResult(
                    status="delivery_unknown",
                    error=f"connection ended during SMTP submission: {type(exc).__name__}",
                    rfc_message_id=rfc_message_id, safe_to_retry=False,
                )
            return SendResult(
                status="failed", error=f"SMTP {stage} failed: {type(exc).__name__}",
                rfc_message_id=rfc_message_id, safe_to_retry=True,
            )
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    pass

    def _search_ids(self, mailbox: Any, field: str, value: str) -> List[bytes]:
        status, data = mailbox.search(None, "HEADER", field, f'"{value}"')
        if str(status).upper() != "OK" or not data:
            return []
        return data[0].split()

    def _fetch_messages(self, mailbox: Any, ids: Sequence[bytes]) -> List[Message]:
        messages: List[Message] = []
        for message_id in ids:
            status, data = mailbox.fetch(message_id, "(BODY.PEEK[])")
            if str(status).upper() != "OK" or not data:
                continue
            raw = next((item[1] for item in data if isinstance(item, tuple)), None)
            if raw:
                messages.append(email.message_from_bytes(raw, policy=policy.default))
        return messages

    def read_replies(
        self,
        query: str,
        *,
        expected_from: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Read only replies correlated by In-Reply-To or References."""
        mailbox = self._imap()
        try:
            self._login_imap(mailbox)
            status, _ = mailbox.select("INBOX", readonly=True)
            if str(status).upper() != "OK":
                raise RuntimeError("cannot select INBOX")
            ids = set(self._search_ids(mailbox, "In-Reply-To", query))
            ids.update(self._search_ids(mailbox, "References", query))
            replies = []
            for message in self._fetch_messages(mailbox, sorted(ids)):
                from_name, from_address = parseaddr(message.get("From", ""))
                if expected_from and from_address.casefold() != expected_from.casefold():
                    continue
                replies.append({
                    "provider_message_id": message.get("Message-ID"),
                    "in_reply_to": message.get("In-Reply-To"),
                    "from": from_address,
                    "from_name": _decoded_header(from_name),
                    "subject": _decoded_header(message.get("Subject")),
                    "received_at": message.get("Date"),
                    "body_excerpt": _plain_text(message).strip()[:500],
                })
            return replies
        finally:
            try:
                mailbox.logout()
            except Exception:
                pass

    def list_sent(self, query: str) -> List[Dict[str, Any]]:
        """Locate the exact RFC Message-ID in a server-declared Sent mailbox."""
        mailbox = self._imap()
        found: List[Dict[str, Any]] = []
        try:
            self._login_imap(mailbox)
            status, rows = mailbox.list()
            names: List[str] = []
            if str(status).upper() == "OK":
                for row in rows or []:
                    text = row.decode("ascii") if isinstance(row, bytes) else str(row)
                    match = re.fullmatch(r'\(([^)]*)\)\s+(?:NIL|"(?:[^"\\]|\\.)*")\s+("(?:[^"\\]|\\.)*"|[^\s]+)', text)
                    if not match:
                        continue
                    flags, name = match.groups()
                    # Keep the server's quoted modified-UTF-7 wire name verbatim.
                    # Never guess a raw Unicode mailbox or an undeclared folder.
                    if "\\sent" in flags.casefold().split() or name.strip('"') in {"Sent", "Sent Messages"}:
                        names.append(name)
            else:
                raise RuntimeError("cannot list IMAP mailboxes")
            for name in names:
                selected, _ = mailbox.select(name, readonly=True)
                if str(selected).upper() != "OK":
                    continue
                ids = self._search_ids(mailbox, "Message-ID", query)
                for message in self._fetch_messages(mailbox, ids):
                    found.append({
                        "folder": name,
                        "provider_message_id": message.get("Message-ID"),
                        "from": parseaddr(message.get("From", ""))[1],
                        "to": parseaddr(message.get("To", ""))[1],
                        "subject": _decoded_header(message.get("Subject")),
                        "body_excerpt": _plain_text(message).strip()[:500],
                        "mime_charset": message.get_content_charset(),
                        "mime_content_type": message.get_content_type(),
                    })
                if found:
                    break
            return found
        finally:
            try:
                mailbox.logout()
            except Exception:
                pass

    def find_inbox_message(self, query: str) -> List[Dict[str, Any]]:
        """Find an exact Message-ID in INBOX for a self-addressed integration test."""
        mailbox = self._imap()
        try:
            self._login_imap(mailbox)
            status, _ = mailbox.select("INBOX", readonly=True)
            if str(status).upper() != "OK":
                raise RuntimeError("cannot select INBOX after IMAP authentication")
            messages = self._fetch_messages(
                mailbox, self._search_ids(mailbox, "Message-ID", query)
            )
            return [{
                "folder": "INBOX",
                "provider_message_id": message.get("Message-ID"),
                "from": parseaddr(message.get("From", ""))[1],
                "to": parseaddr(message.get("To", ""))[1],
                "subject": _decoded_header(message.get("Subject")),
                "body_excerpt": _plain_text(message).strip()[:500],
                "mime_charset": message.get_content_charset(),
                "mime_content_type": message.get_content_type(),
            } for message in messages]
        finally:
            try:
                mailbox.logout()
            except Exception:
                pass
