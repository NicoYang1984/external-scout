#!/usr/bin/env python3
"""Scout -> Contributor -> GitHub -> Outreach. Local state defaults to Scout V2."""
import argparse
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import contributor
from opportunity import gate, outreach_candidate
from pipeline_github import GitHub, track
from pipeline_store import Store
from state import data_dir, utc


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir', type=Path, default=data_dir())
    commands = p.add_subparsers(dest='command', required=True)
    imp = commands.add_parser('import', help='Scout-owned handoff import, no target modifications')
    imp.add_argument('--file', type=Path, required=True)
    revision = commands.add_parser('revise', help='Start a fresh audited attempt; preserve previous worktree/history')
    revision.add_argument('--file', type=Path, required=True)
    revision.add_argument('--reason', required=True)
    commands.add_parser('list')
    for name in ('show', 'history', 'gate', 'export', 'run', 'commit', 'authorize', 'publish', 'track', 'outreach'):
        sub = commands.add_parser(name)
        sub.add_argument('--id', required=True)
        if name in {'export', 'outreach'}:
            sub.add_argument('--output', type=Path, required=True)
        if name == 'run':
            sub.add_argument('--checkout', type=Path, required=True)
            sub.add_argument('--resume', action='store_true')
        if name == 'authorize':
            sub.add_argument('--push-repo', required=True)
            sub.add_argument('--approved-by', required=True)
            sub.add_argument('--evidence', required=True, help='Existing explicit user authorization reference; never infer from Scout')
    return p


def main():
    p, store = parser(), None
    a = p.parse_args()
    try:
        store = Store(a.data_dir)
        api = GitHub(store.db, token=os.environ.get('GITHUB_TOKEN'))
        if a.command == 'import':
            result = store.put(json.loads(a.file.read_text()))
        elif a.command == 'revise':
            result = store.revise(json.loads(a.file.read_text()), a.reason)
        elif a.command == 'list':
            result = [{'opportunity_id': x['opportunity_id'], 'campaign_type': x['campaign_type'],
                       'status': x['status'], 'gate': gate(x), 'progress': store.progress(x['opportunity_id'])} for x in store.list()]
        elif a.command == 'show':
            result = {'spec': store.get(a.id), 'progress': store.progress(a.id)}
        elif a.command == 'history':
            result = store.history(a.id)
        elif a.command == 'gate':
            result = gate(store.get(a.id))
        elif a.command == 'export':
            contributor.write_json(a.output, store.get(a.id))
            result = {'output': str(a.output), 'target_modified': False}
        elif a.command == 'run':
            result = contributor.run(store, api, a.id, a.checkout, a.resume)
        elif a.command == 'commit':
            result = contributor.commit(store, a.id)
        elif a.command == 'authorize':
            result = contributor.authorize(store, a.id, a.push_repo, a.approved_by, a.evidence)
        elif a.command == 'publish':
            result = contributor.publish(store, api, a.id)
        elif a.command == 'track':
            with store.lock(a.id):
                spec, progress = store.get(a.id), store.progress(a.id)
                url = progress.get('pr_url') or spec.get('existing_pr')
                if not url:
                    raise ValueError('No submitted PR; a candidate is not a submission')
                try:
                    result = store.observe(a.id, track(api, spec, url))
                except (ValueError, OSError) as exc:
                    store.save(a.id, 'github_query_failed', last_query_error=str(exc), last_attempt_at=utc())
                    raise
        elif a.command == 'outreach':
            with store.lock(a.id):
                spec, progress = store.get(a.id), store.progress(a.id)
                from datetime import datetime, timezone
                from opportunity import timestamp
                fresh = progress.get('last_checked_at') and not progress.get('last_query_error') and (
                    0 <= (datetime.now(timezone.utc) - timestamp(progress['last_checked_at'])).total_seconds() <= 86400)
                task = outreach_candidate(spec, progress.get('outcome', {})) if fresh else None
                result = {'tasks': [task] if task else [], 'automatic_send': False}
                contributor.write_json(a.output, result)
                store.save(a.id, 'outreach_evaluated', outreach_task=task)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        p.exit(2, str(exc) + '\n')
    finally:
        if store:
            store.close()


if __name__ == '__main__':
    raise SystemExit(main())
