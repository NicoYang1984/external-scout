#!/usr/bin/env python3
"""Interactive, secret-safe provider verification for personal 163 mail."""

from __future__ import annotations

import argparse
import smtplib
import json
import sys
import time
from dataclasses import dataclass, field
from email.utils import make_msgid
from pathlib import Path

from netease163 import (
    MacOSKeychainCredentialStore,
    NetEase163MailAdapter,
    load_authorization_code,
    prompt_authorization_code,
    validate_personal_account,
)
from macos_keychain import KeychainAccessError
from outreach_core import OutreachStore, utcnow
from provider_report import render_provider_reports


PROVIDER = "netease163_personal"
TEST_SUBJECT = "LazyMind 网易邮箱集成自测（仅账户所有者）"
TEST_LINK = "https://github.com/LazyAGI/LazyMind"
TEST_BODY = (
    "这是一封 LazyMind Outreach Agent V1.1 的账户所有者自测邮件。\n\n"
    "它用于验证中文主题、中文正文、链接和 UTF-8 MIME 编码，不是推广邮件，"
    "也不会触发任何第三方外发。\n\n"
    f"项目链接：{TEST_LINK}\n"
)


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def read_account(value: str | None) -> str:
    if value:
        return validate_personal_account(value)
    return validate_personal_account(input("个人 163 邮箱账号: ").strip())


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--db", type=Path, default=Path("data/outreach.sqlite3"))
    root.add_argument("--account", help="personal @163.com account; never an authorization code")
    root.add_argument("--report-dir", type=Path, help="write non-secret provider/readiness reports here")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("probe", help="phase 1: authenticate SMTP and IMAP without sending")
    test = sub.add_parser("self-test", help="phase 2: send one self-addressed integration test")
    test.add_argument("--wait-seconds", type=int, default=20)
    wizard = sub.add_parser("wizard", help="run phase 1, then the explicitly confirmed owner self-test")
    wizard.add_argument("--wait-seconds", type=int, default=20)
    repair = sub.add_parser("repair", help="replace the saved credential after validation, then self-test")
    repair.add_argument("--wait-seconds", type=int, default=20)
    sub.add_parser("check-replies", help="read only replies correlated to recorded real sends")
    sub.add_parser("show-pacing", help="show the sender's persisted cooldown; no mail access")
    pacing = sub.add_parser("configure-pacing", help="set local sending interval; does not authorize or send")
    pacing.add_argument("--interval-seconds", type=int, required=True)
    send = sub.add_parser("send-batch", help="phase 3: send one already approved exact batch")
    send.add_argument("--batch-id", required=True)
    send.add_argument("--wait-for-interval", action="store_true", help="continue this approved batch after each cooldown; Ctrl-C stops")
    return root


@dataclass(repr=False)
class VerifiedSession:
    account: str
    adapter: NetEase163MailAdapter = field(repr=False)
    report: dict


def verified_session(
    store: OutreachStore, account: str, *, save_prompt: bool = True, repair: bool = False,
) -> VerifiedSession:
    # Previous verification cannot authorize live operations after credential failure.
    store.conn.execute("UPDATE sender_accounts SET live_enabled=0 WHERE account=?", (account,))
    store.conn.commit()
    keychain = MacOSKeychainCredentialStore()
    if repair:
        code, source = prompt_authorization_code(), "interactive_prompt"
    else:
        try:
            code, source = load_authorization_code(account, keychain=keychain)
        except KeychainAccessError as exc:
            print(f"Keychain 暂不可访问（状态 {exc.status}），请在隐藏提示中输入授权码。")
            code, source = prompt_authorization_code(), "interactive_prompt"
    adapter = NetEase163MailAdapter(account, code)
    try:
        result = adapter.probe().as_dict()
    except Exception as exc:
        safe = {"error_type": type(exc).__name__, "authorization_code_stored": False}
        if isinstance(exc, smtplib.SMTPAuthenticationError):
            safe.update(stage="authenticate", smtp_code=int(exc.smtp_code), message_submitted=False)
        store.conn.execute(
            "UPDATE sender_accounts SET authorized=0,live_enabled=0,connection_verified_at=NULL WHERE account=?",
            (account,),
        )
        store.record_provider_check(account, PROVIDER, "phase1_connection", "failed", safe)
        raise RuntimeError(
            "SMTP authentication failed; message not submitted. Run repair with the current client authorization code."
            if isinstance(exc, smtplib.SMTPAuthenticationError)
            else f"connection probe failed: {type(exc).__name__}"
        ) from None
    stored = source == "macos_keychain"
    storage_error = None
    if not stored and (save_prompt or repair):
        answer = "y" if repair else input("连接成功。是否将授权码保存到 macOS Keychain？[Y/n] ").strip().casefold()
        if answer in {"", "y", "yes", "是"}:
            try:
                keychain.save(account, code)
                stored = True
                print("Keychain 已保存并读回核验一致。")
            except Exception as exc:
                storage_error = type(exc).__name__
                print("Keychain 保存或读回核验未通过；本次继续使用已验证的内存凭据。")
    result["credential_source"] = "macos_keychain" if stored else "memory_only"
    result["keychain_readback_verified"] = stored
    if storage_error:
        result["keychain_error_type"] = storage_error
    result["authorization_code_stored_in_sqlite"] = False
    result["third_party_message_sent"] = False
    store.configure_sender(
        account, PROVIDER, True, utcnow(), account_type="personal_163",
        connection_verified_at=utcnow(), live_enabled=False,
        details={"credential_storage": result["credential_source"]},
    )
    store.record_provider_check(account, PROVIDER, "phase1_connection", "passed", result)
    return VerifiedSession(account, adapter, result)


def phase1(store: OutreachStore, account: str, save_prompt: bool = True) -> dict:
    return verified_session(store, account, save_prompt=save_prompt).report


def phase2(
    store: OutreachStore, account: str, wait_seconds: int, *, session: VerifiedSession = None,
    owner_target: bool = False,
) -> dict:
    sender = store.conn.execute(
        "SELECT * FROM sender_accounts WHERE account=?", (account,)
    ).fetchone()
    if not sender or not sender["connection_verified_at"]:
        raise RuntimeError("phase 1 must pass before phase 2")
    target = account if owner_target else input("账户所有者指定的自测邮箱（V1.1 必须与发件账号相同）: ").strip().casefold()
    if target != account:
        raise ValueError("phase 2 is restricted to the authenticated account itself; no third party is allowed")
    if session:
        if session.account != account:
            raise ValueError("verified session/account mismatch")
        adapter, source = session.adapter, "verified_session_memory"
    else:
        code, source = load_authorization_code(account)
        adapter = NetEase163MailAdapter(account, code)
    # Reconcile a previous accepted/uncertain attempt; rerunning never blind-resends.
    prior = store.conn.execute(
        "SELECT * FROM provider_checks WHERE account=? AND phase='phase2_owner_self_test' ORDER BY id DESC LIMIT 1",
        (account,),
    ).fetchone()
    resume = prior and prior["status"] in {"queued", "delivery_unknown", "smtp_accepted", "incomplete", "passed"}
    if not resume:
        phrase = f"SEND TEST TO {target}"
        if input(f"输入 {phrase} 以确认只发送一封自测邮件: ").strip() != phrase:
            raise RuntimeError("self-test confirmation did not match; nothing was sent")
    store.conn.execute("UPDATE sender_accounts SET live_enabled=0 WHERE account=?", (account,))
    store.conn.commit()
    report = {
        "recipient": target,
        "credential_source": source,
        "smtp_result": "queued",
        "rfc_message_id": make_msgid(domain="163.com"),
        "smtp_accepted_is_delivery_confirmation": False,
        "inbox_found": False,
        "sent_folder_found": False,
        "mime_checks": {"chinese_subject": False, "chinese_body": False, "link": False},
    }
    # Reserve a queued record atomically so another terminal cannot submit the same test.
    store.conn.execute("BEGIN IMMEDIATE")
    latest = store.conn.execute(
        "SELECT * FROM provider_checks WHERE account=? AND phase='phase2_owner_self_test' ORDER BY id DESC LIMIT 1",
        (account,),
    ).fetchone()
    if latest and latest["status"] in {"queued", "delivery_unknown", "smtp_accepted", "incomplete", "passed"}:
        store.conn.commit()
        report = json.loads(latest["details_json"])
        check_id = latest["id"]
        report["reconciled_without_resend"] = True
        if report.get("smtp_result") == "queued":
            report["smtp_result"] = "delivery_unknown"
        print("发现已有自测提交记录，仅查询收件箱和已发送记录，不重复发送。")
    else:
        cursor = store.conn.execute(
            "INSERT INTO provider_checks(account,provider,phase,status,details_json,checked_at) VALUES(?,?,?,'queued',?,?)",
            (account, PROVIDER, "phase2_owner_self_test", json.dumps(report), utcnow()),
        )
        check_id = cursor.lastrowid
        store.conn.commit()
        try:
            result = adapter.send(
                to=target, subject=TEST_SUBJECT, body=TEST_BODY, sender=account,
                idempotency_key=f"owner-self-test:{account}:{check_id}",
                rfc_message_id=report["rfc_message_id"],
            )
        except Exception as exc:
            report.update(smtp_result="delivery_unknown", error_type=type(exc).__name__)
            _finish_self_test(store, check_id, "delivery_unknown", report)
            return report
        report.update(smtp_result=result.status, error=result.error, smtp_details=result.details or {})
        status = result.status if result.status in {"smtp_accepted", "delivery_unknown"} else "failed"
        _finish_self_test(store, check_id, status, report)
        if result.status == "failed":
            if (result.details or {}).get("stage") == "authenticate":
                store.conn.execute("UPDATE sender_accounts SET authorized=0 WHERE account=?", (account,))
                store.conn.commit()
            return report
    if not report.get("rfc_message_id"):
        raise RuntimeError("prior self-test has no Message-ID; manual reconciliation required before retry")
    deadline = time.monotonic() + max(0, min(wait_seconds, 60))
    inbox = []
    sent = []
    report.pop("imap_error_type", None)
    while True:
        try:
            inbox = adapter.find_inbox_message(report["rfc_message_id"])
            sent = adapter.list_sent(report["rfc_message_id"])
        except Exception as exc:
            report["imap_error_type"] = type(exc).__name__
            break
        if inbox and sent:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(2)
    report["inbox_found"] = bool(inbox)
    report["sent_folder_found"] = bool(sent)
    samples = [group[0] for group in (inbox, sent) if group]
    report["mime_checks"] = {
        "chinese_subject": bool(samples) and all(sample.get("subject") == TEST_SUBJECT for sample in samples),
        "chinese_body": bool(samples) and all("账户所有者自测邮件" in sample.get("body_excerpt", "") for sample in samples),
        "link": bool(samples) and all(TEST_LINK in sample.get("body_excerpt", "") for sample in samples),
        "utf8_plain_text": bool(samples) and all(
            sample.get("mime_charset") == "utf-8" and sample.get("mime_content_type") == "text/plain"
            for sample in samples
        ),
        "exact_message_identity": bool(samples) and all(
            sample.get("provider_message_id") == report["rfc_message_id"]
            and sample.get("from", "").casefold() == account
            and sample.get("to", "").casefold() == target
            for sample in samples
        ),
    }
    report["owner_inbox_receipt_verified"] = bool(inbox and all(report["mime_checks"].values()))
    report["mailbox_evidence"] = [
        {key: sample.get(key) for key in ("folder", "provider_message_id", "from", "to", "mime_charset", "mime_content_type")}
        for sample in samples
    ]
    passed = bool(inbox and sent and all(report["mime_checks"].values()))
    store.configure_sender(
        account, PROVIDER, True, sender["verified_at"], account_type="personal_163",
        connection_verified_at=sender["connection_verified_at"], live_enabled=passed,
        details={"credential_storage": source, "phase2_passed": passed},
    )
    _finish_self_test(store, check_id, "passed" if passed else "incomplete", report)
    return report


def _finish_self_test(store: OutreachStore, check_id: int, status: str, report: dict):
    store.conn.execute(
        "UPDATE provider_checks SET status=?,details_json=?,checked_at=? WHERE id=?",
        (status, json.dumps(report, ensure_ascii=False), utcnow(), check_id),
    )
    store.conn.commit()


def check_replies(store: OutreachStore, account: str) -> dict:
    sender = store.conn.execute(
        "SELECT * FROM sender_accounts WHERE account=?", (account,)
    ).fetchone()
    if not sender or not sender["connection_verified_at"]:
        raise RuntimeError("phase 1 must pass before reply reads")
    code, source = load_authorization_code(account)
    adapter = NetEase163MailAdapter(account, code)
    rows = store.conn.execute("""
      SELECT sr.idempotency_key,sr.rfc_message_id,d.lead_id,l.contact_value
      FROM send_requests sr JOIN drafts d ON d.id=sr.draft_id
      JOIN leads l ON l.id=d.lead_id
      WHERE sr.mode='real' AND sr.rfc_message_id IS NOT NULL
      AND sr.status IN ('delivery_unknown','smtp_accepted','succeeded','replied')
    """).fetchall()
    recorded = []
    for row in rows:
        for reply in adapter.read_replies(
            row["rfc_message_id"], expected_from=row["contact_value"]
        ):
            category = store.record_reply(
                row["lead_id"], reply["body_excerpt"], reply["provider_message_id"]
            )
            store.conn.execute(
                "UPDATE send_requests SET status='replied',updated_at=? WHERE idempotency_key=?",
                (utcnow(), row["idempotency_key"]),
            )
            store.conn.commit()
            recorded.append({
                "lead_id": row["lead_id"], "category": category,
                "provider_message_id": reply["provider_message_id"],
                "follow_up_sent": False,
            })
    return {
        "credential_source": source,
        "threads_checked": len(rows),
        "replies_recorded": recorded,
        "automatic_follow_up": False,
    }


def send_approved_batch(
    store: OutreachStore, account: str, batch_id: str, *, wait_for_interval: bool = False,
) -> dict:
    batch = store.conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
    if not batch:
        raise KeyError(batch_id)
    if batch["sender_account"].casefold() != account:
        raise ValueError("authenticated account does not match the batch sender")
    print(f"发件节奏：每 {store.get_send_pacing(account)['min_interval_seconds']} 秒最多尝试一封；异常停止本轮。")
    phrase = f"SEND APPROVED BATCH {batch_id}"
    if input(f"输入 {phrase} 以执行已审批批次: ").strip() != phrase:
        raise RuntimeError("batch confirmation did not match; nothing was sent")
    code, source = load_authorization_code(account)
    adapter = NetEase163MailAdapter(account, code)
    while True:
        results = store.send_batch(batch_id, adapter, "real")
        deferred = next((x for x in results if x["status"] == "deferred_rate_limit"), None)
        if not deferred or not wait_for_interval:
            break
        print(f"冷却至 {deferred['next_allowed_at']}；等待后重新检查审批和排除状态。按 Ctrl-C 可停止。", flush=True)
        deadline = time.monotonic() + deferred["retry_after_seconds"]
        while time.monotonic() < deadline:
            time.sleep(min(30, max(0, deadline - time.monotonic())))
    return {
        "batch_id": batch_id, "credential_source": source, "results": results,
        "pacing": store.get_send_pacing(account), "pending_cooldown": bool(deferred),
        "smtp_acceptance_is_delivery_confirmation": False,
    }


def main() -> int:
    args = build_parser().parse_args()
    store = OutreachStore(args.db)
    store.init()
    try:
        account = read_account(args.account)
        if args.command == "probe":
            emit(phase1(store, account))
        elif args.command == "self-test":
            result = phase2(store, account, args.wait_seconds)
            emit(result)
            if not (result.get("inbox_found") and result.get("sent_folder_found") and all(result["mime_checks"].values())):
                return 2
        elif args.command in {"wizard", "repair"}:
            session = verified_session(store, account, repair=args.command == "repair")
            emit({"phase1": session.report})
            result = phase2(store, account, args.wait_seconds, session=session, owner_target=args.command == "repair")
            emit({"phase2": result})
            if not (result.get("inbox_found") and result.get("sent_folder_found") and all(result["mime_checks"].values())):
                return 2
        elif args.command == "check-replies":
            emit(check_replies(store, account))
        elif args.command == "show-pacing":
            emit(store.get_send_pacing(account))
        elif args.command == "configure-pacing":
            emit(store.set_send_interval(account, args.interval_seconds))
        elif args.command == "send-batch":
            result = send_approved_batch(store, account, args.batch_id, wait_for_interval=args.wait_for_interval)
            emit(result)
            if result["pending_cooldown"]:
                return 3
            if any(x["status"] in {"failed", "retry_blocked"} or (
                x["status"] == "delivery_unknown" and x.get("last_error")
            ) for x in result["results"]):
                return 2
    except (KeyboardInterrupt, EOFError):
        print("操作已取消；如已提交自测邮件，下次运行只会核验记录。", file=sys.stderr)
        return 130
    except Exception as exc:
        # Provider exception messages may contain echoed input; print controlled local errors only.
        detail = str(exc) if type(exc) in {RuntimeError, ValueError, KeychainAccessError} else type(exc).__name__
        print(f"ERROR: {detail}", file=sys.stderr)
        return 2
    finally:
        if args.report_dir:
            render_provider_reports(store, args.report_dir)
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
