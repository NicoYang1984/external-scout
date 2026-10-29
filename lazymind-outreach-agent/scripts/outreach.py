#!/usr/bin/env python3
"""Command line entry point for the LazyMind outreach state machine."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adapters import MockMailAdapter
from outreach_core import OutreachStore
from scout_adapter import export_outcomes, import_scout
from pipeline_adapter import import_pipeline


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    root.add_argument("--db", type=Path, required=True)
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    imp = sub.add_parser("import-scout")
    imp.add_argument("--scout-db", type=Path, required=True)
    pipeline = sub.add_parser("import-pipeline")
    pipeline.add_argument("--file", type=Path, required=True)
    load = sub.add_parser("load-leads")
    load.add_argument("--file", type=Path, required=True)
    batch = sub.add_parser("create-batch")
    batch.add_argument("--name", required=True)
    batch.add_argument("--sender", required=True)
    batch.add_argument("--draft-id", action="append", required=True)
    review = sub.add_parser("review")
    review.add_argument("--batch-id", required=True)
    approve = sub.add_parser("approve")
    approve.add_argument("--batch-id", required=True)
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--review-seconds", type=float, default=0)
    send = sub.add_parser("simulate-send")
    send.add_argument("--batch-id", required=True)
    export = sub.add_parser("export-scout-outcomes")
    export.add_argument("--output", type=Path, required=True)
    sub.add_parser("metrics")
    return root


def main() -> int:
    args = parser().parse_args()
    store = OutreachStore(args.db)
    store.init()
    try:
        if args.command == "init":
            emit({"database": str(args.db), "initialized": True, "dry_run": True})
        elif args.command == "import-scout":
            emit(import_scout(store, args.scout_db))
        elif args.command == "import-pipeline":
            emit(import_pipeline(store, args.file))
        elif args.command == "load-leads":
            payload = json.loads(args.file.read_text(encoding="utf-8"))
            emit({"lead_ids": [store.upsert_lead(item) for item in payload["leads"]]})
        elif args.command == "create-batch":
            emit({"batch_id": store.create_batch(args.name, args.sender, args.draft_id)})
        elif args.command == "review":
            emit(store.review_checklist(args.batch_id))
        elif args.command == "approve":
            store.approve_batch(args.batch_id, args.approved_by, args.review_seconds)
            emit({"batch_id": args.batch_id, "approved": True})
        elif args.command == "simulate-send":
            emit(store.send_batch(args.batch_id, MockMailAdapter(), "simulated"))
        elif args.command == "export-scout-outcomes":
            export_outcomes(store, args.output)
            emit({"output": str(args.output), "scout_database_modified": False})
        elif args.command == "metrics":
            emit(store.metrics())
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
