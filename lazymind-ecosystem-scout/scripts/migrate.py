#!/usr/bin/env python3
"""Copy V1 database to a NEW V2 directory. Source is opened read-only, never upgraded."""
import argparse
import json
import sqlite3
from pathlib import Path
import registry
import state


def migrate(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file():
        raise ValueError('Source database does not exist')
    if destination.exists():
        raise ValueError('Destination must not exist; refusing overwrite')
    destination.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as old:
        with sqlite3.connect(destination / 'opportunities.sqlite3') as new:
            old.backup(new)
    db = registry.connect(destination, allow_upgrade=True)
    with db:
        # Legacy cursor was not transactionally proven by page receipts. Preserve it,
        # but start verified enumeration from zero; dispositions/URLs still dedup.
        for (payload,) in list(db.execute('SELECT payload FROM repositories')):
            record = json.loads(payload)
            record['legacy_cursor'] = record.get('cursor', {})
            record['cursor'] = {'last_issue_number': 0, 'pending_issue_numbers': record.get('cursor', {}).get('pending_issue_numbers', [])}
            record.update(status='partial', next_action='Reconcile unproven V1 enumeration; skip already reviewed URLs')
            state.save_repo(db, record)
        for url, payload in list(db.execute('SELECT url,payload FROM opportunities')):
            record = json.loads(payload)
            record['legacy_unverified'] = True
            if record.get('status') in {'validated', 'ready_for_review'}:
                record['legacy_status'] = record['status']
                record['status'] = 'verification_pending'
            db.execute('UPDATE opportunities SET payload=? WHERE url=?', (json.dumps(record, ensure_ascii=False), url))
        # Old visits without checkpoints must remain resumable, not permanently skipped.
        for run_id, repo in list(db.execute('SELECT run_id,repo FROM repository_visits')):
            if not state.read_repo(db, repo):
                state.save_repo(db, dict(repo=repo,run_id=run_id,status='partial',summary='V1 orphan claim recovered',coverage={'reviewed_urls':[]},cursor={'last_issue_number':0,'pending_issue_numbers':[]},memory={},next_action='Resume interrupted initial scan'))
    counts = {t: db.execute('SELECT COUNT(*) FROM ' + t).fetchone()[0] for t in ('opportunities','history','repositories','repository_history','runs')}
    db.close()
    return dict(destination=str(destination), source_modified=False, counts=counts)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path)
    p.add_argument('--destination', required=True, type=Path)
    a = p.parse_args()
    try:
        print(json.dumps(migrate(a.source, a.destination), indent=2))
    except (OSError, ValueError, sqlite3.Error) as exc:
        p.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
