#!/usr/bin/env python3
"""Mail adapter contracts. V1 permits only deterministic simulation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from outreach_core import SendResult


class MailAdapter(ABC):
    @abstractmethod
    def create_draft(self, *, to: str, subject: str, body: str, sender: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def send(self, *, to: str, subject: str, body: str, sender: str, idempotency_key: str) -> SendResult:
        raise NotImplementedError

    @abstractmethod
    def list_sent(self, query: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def read_replies(self, query: str) -> List[Dict[str, Any]]:
        raise NotImplementedError


class MockMailAdapter(MailAdapter):
    def __init__(self, fail_once: bool = False):
        self.fail_once = fail_once
        self._failed = set()

    def create_draft(self, *, to: str, subject: str, body: str, sender: str) -> Dict[str, Any]:
        return {"mode": "simulated", "to": to, "subject": subject, "sender": sender}

    def send(self, *, to: str, subject: str, body: str, sender: str, idempotency_key: str) -> SendResult:
        if self.fail_once and idempotency_key not in self._failed:
            self._failed.add(idempotency_key)
            raise RuntimeError("simulated transient provider failure")
        return SendResult(status="simulated", provider_message_id=f"sim-{idempotency_key[:20]}")

    def list_sent(self, query: str) -> List[Dict[str, Any]]:
        return []

    def read_replies(self, query: str) -> List[Dict[str, Any]]:
        return []


class GmailApiAdapter(MailAdapter):
    """OAuth Gmail interface; intentionally non-operational until a release gate enables it."""

    def __init__(self, oauth_token_provider: Any = None, allow_live: bool = False):
        self.oauth_token_provider = oauth_token_provider
        self.allow_live = allow_live

    def _blocked(self) -> None:
        raise RuntimeError("Gmail live operations are disabled in v1; secrets must come from an approved OAuth provider")

    def create_draft(self, **kwargs: Any) -> Dict[str, Any]:
        self._blocked()

    def send(self, **kwargs: Any) -> SendResult:
        self._blocked()

    def list_sent(self, query: str) -> List[Dict[str, Any]]:
        self._blocked()

    def read_replies(self, query: str) -> List[Dict[str, Any]]:
        self._blocked()


class EnterpriseMailAdapter(MailAdapter):
    """Interface for a company-approved mail provider implementation."""

    pass

