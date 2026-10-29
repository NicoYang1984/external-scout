#!/usr/bin/env python3
"""Bounded read-only GitHub and public Skill catalog discovery."""
import argparse
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
import registry
import state
from sources import GitHubAdapter, GitHubHTTP, CatalogAdapter, SnapshotTransport


def scan(db, repo, repo_id, run_id, transport, max_pages=2, snapshot=False):
    if not 1 <= max_pages <= 10:
        raise ValueError('max-pages must be 1..10')
    with db:
        db.execute('BEGIN IMMEDIATE')
        repo = registry.canonical_repo(repo)
        state.identify(db, repo, repo_id)
        c = state.claim(db, repo, run_id)
    if c['action'] in {'skip_this_run', 'busy'}:
        return c
    token, scan_id = c['claim_token'], uuid.uuid4().hex
    with db:
        db.execute('BEGIN IMMEDIATE')
        state.begin_scan(db, repo, run_id, token, scan_id)
    previous = (c['previous'] or {}).get('cursor', {})
    since = previous.get('updates_checked_through')
    if since and not snapshot:
        since = (datetime.fromisoformat(since.replace('Z', '+00:00')) - timedelta(minutes=5)).isoformat()
    else:
        since = None
    adapter = GitHubAdapter(repo, repo_id, transport, since=since)
    processed, complete = 0, False
    try:
        for page_no in range(1, max_pages + 1):
            page = adapter.page(page_no)
            with db:
                db.execute('BEGIN IMMEDIATE')
                complete = state.ingest_page(db, repo, run_id, token, scan_id, page_no,
                                            page.items, page.has_next,
                                            # Historical snapshots never certify a current watermark.
                                            complete_evidence=page.complete_evidence and not snapshot)
            processed += len(page.items)
            if not page.has_next:
                break
        with db:
            db.execute('BEGIN IMMEDIATE')
            record = state.read_repo(db, repo)
            record.update(status='completed' if complete else 'partial', run_id=run_id,
                          summary='Read-only enumeration; items await triage', next_action='Triage pending issues; continue bounded enumeration')
            state.checkpoint(db, record, token)
        return dict(repo=repo, count=processed, pagination_terminal=not page.has_next,
                    cursor_advanced=complete, snapshot_replay=snapshot, scan_id=scan_id,
                    claim_token=token, status=record['status'])
    except (ValueError, OSError) as exc:
        return dict(repo=repo, count=processed, cursor_advanced=False, status='blocked',
                    error=str(exc), scan_id=scan_id, claim_token=token)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir', type=Path, default=state.data_dir())
    sub = p.add_subparsers(dest='source', required=True)
    gh = sub.add_parser('github')
    gh.add_argument('--repo', required=True)
    gh.add_argument('--repo-id', required=True, help='Verified numeric GitHub repository ID')
    gh.add_argument('--run-id', required=True)
    gh.add_argument('--max-pages', type=int, default=2)
    gh.add_argument('--snapshot', type=Path, action='append', help='Raw connector acquisition JSON; never advances current cursor')
    catalog = sub.add_parser('catalog')
    catalog.add_argument('--file', required=True, type=Path)
    args = p.parse_args()
    try:
        db = registry.connect(args.data_dir)
        if args.source == 'github':
            transport = SnapshotTransport(args.snapshot) if args.snapshot else GitHubHTTP(args.max_pages, os.environ.get('GITHUB_TOKEN'))
            result = scan(db, args.repo, args.repo_id, args.run_id, transport, args.max_pages, bool(args.snapshot))
        else:
            page = CatalogAdapter(args.file).page()
            with db:
                db.execute('BEGIN IMMEDIATE')
                keys = [state.observe(db, x) for x in page.items]
            result = dict(count=len(keys), entity_keys=keys, external_writes=False)
        db.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get('status') == 'blocked':
            raise SystemExit(2)
    except (ValueError, KeyError, OSError) as exc:
        p.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
