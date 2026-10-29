"""V2 transactional extensions to the original registry (stdlib only)."""
import json
import os
import sqlite3
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path


def utc():
    return datetime.now(timezone.utc).isoformat()


def data_dir():
    if os.environ.get('LAZYMIND_SCOUT_DATA_DIR'):
        return Path(os.environ['LAZYMIND_SCOUT_DATA_DIR']).expanduser()
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'lazymind-ecosystem-scout-v2'


SCHEMA = '''
    CREATE TABLE IF NOT EXISTS claims (
      repo TEXT PRIMARY KEY, run_id TEXT NOT NULL, token TEXT NOT NULL,
      expires TEXT NOT NULL, state TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS repo_aliases (alias TEXT PRIMARY KEY, repo_id TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS repo_ids (repo_id TEXT PRIMARY KEY, repo TEXT NOT NULL UNIQUE);
    CREATE TABLE IF NOT EXISTS source_items (
      entity_key TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS source_observations (
      source TEXT NOT NULL, source_id TEXT NOT NULL, entity_key TEXT NOT NULL,
      payload TEXT NOT NULL, recorded_at TEXT NOT NULL,
      UNIQUE(source, source_id, payload));
    CREATE TABLE IF NOT EXISTS scans (
      scan_id TEXT PRIMARY KEY, repo TEXT NOT NULL, run_id TEXT NOT NULL,
      started_at TEXT NOT NULL, next_page INTEGER NOT NULL,
      complete INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS dispositions (
      repo TEXT NOT NULL, number INTEGER NOT NULL, updated_at TEXT NOT NULL,
      evidence TEXT NOT NULL, PRIMARY KEY(repo,number));
    '''


def merge(old, patch):
    """Absent/null values preserve history; nested objects merge, lists union."""
    if patch is None:
        return deepcopy(old)
    if isinstance(old, dict) and isinstance(patch, dict):
        result = deepcopy(old)
        for key, value in patch.items():
            result[key] = merge(result[key], value) if key in result else deepcopy(value)
        return result
    if isinstance(old, list) and isinstance(patch, list):
        return deepcopy(old) + [deepcopy(x) for x in patch if x not in old]
    if old is not None and type(old) is not type(patch):
        raise ValueError('Memory type change requires explicit migration, not replacement')
    return deepcopy(patch)


def resolve(db, repo):
    row = db.execute('SELECT r.repo FROM repo_aliases a JOIN repo_ids r USING(repo_id) WHERE a.alias=?', (repo,)).fetchone()
    return row[0] if row else repo


def identify(db, repo, repo_id):
    """Use immutable GitHub repository ID; never guess redirects by similar names."""
    repo_id = str(repo_id)
    if not repo_id.isdigit():
        raise ValueError('GitHub repo_id must be numeric')
    conflicting = db.execute('SELECT repo_id FROM repo_aliases WHERE alias=?', (repo,)).fetchone()
    if conflicting and conflicting[0] != repo_id:
        raise ValueError('Alias now belongs to another repository; manual reconciliation required')
    row = db.execute('SELECT repo FROM repo_ids WHERE repo_id=?', (repo_id,)).fetchone()
    old = row[0] if row else repo
    if old != repo:
        for name in (old, repo):
            active = db.execute("SELECT 1 FROM claims WHERE repo=? AND state='active' AND expires>?", (name, utc())).fetchone()
            if active:
                raise ValueError('Finish or expire active claim before repository rename')
        # Preserve immutable histories; rekey only the current opportunity view.
        renames = []
        for url, payload in list(db.execute('SELECT url,payload FROM opportunities')):
            value = json.loads(payload)
            if value.get('repo', '').lower() == old:
                new_url = url.replace('https://github.com/' + old, 'https://github.com/' + repo, 1)
                if new_url != url and db.execute('SELECT 1 FROM opportunities WHERE url=?', (new_url,)).fetchone():
                    raise ValueError('Opportunity URL collision during rename; manual reconciliation required')
                value['repo'], value['url'] = repo, new_url
                renames.append((new_url, json.dumps(value, ensure_ascii=False), url))
        a, b = read_repo(db, old), read_repo(db, repo)
        if a and b:
            raise ValueError('Both names have checkpoints; reconcile on a copy before rename')
        for new_url, payload, old_url in renames:
            db.execute('UPDATE opportunities SET url=?,payload=? WHERE url=?', (new_url, payload, old_url))
        if a:
            a['repo'] = repo
            save_repo(db, a)
            db.execute('DELETE FROM repositories WHERE repo=?', (old,))
        db.execute('INSERT OR IGNORE INTO repository_visits SELECT run_id, ?, started_at FROM repository_visits WHERE repo=?', (repo, old))
        db.execute('DELETE FROM claims WHERE repo=?', (old,))
        db.execute('UPDATE scans SET repo=? WHERE repo=?', (repo, old))
        db.execute('UPDATE dispositions SET repo=? WHERE repo=?', (repo, old))
    db.execute('INSERT INTO repo_ids VALUES (?,?) ON CONFLICT(repo_id) DO UPDATE SET repo=excluded.repo', (repo_id, repo))
    for alias in {old, repo}:
        db.execute('INSERT OR IGNORE INTO repo_aliases VALUES (?,?)', (alias, repo_id))
    return {'repo': repo, 'repo_id': repo_id, 'previous_name': old}


def read_repo(db, repo):
    row = db.execute('SELECT payload FROM repositories WHERE repo=?', (repo,)).fetchone()
    return json.loads(row[0]) if row else None


def save_repo(db, record):
    payload, stamp = json.dumps(record, ensure_ascii=False), utc()
    db.execute('INSERT INTO repository_history(repo,recorded_at,payload) VALUES (?,?,?)', (record['repo'], stamp, payload))
    db.execute('INSERT INTO repositories VALUES (?,?,?) ON CONFLICT(repo) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload', (record['repo'], stamp, payload))


def require_claim(db, repo, run_id, token):
    row = db.execute('SELECT run_id,token,expires,state FROM claims WHERE repo=?', (repo,)).fetchone()
    if not row or row[0] != run_id or row[1] != token or row[2] <= utc() or row[3] != 'active':
        raise ValueError('Missing, expired or stale claim; use repo-start after lease expires')


def claim(db, repo, run_id, seconds=300, preview=False, rescan=None):
    if not 1 <= seconds <= 3600:
        raise ValueError('lease-seconds must be 1..3600')
    repo = resolve(db, repo)
    prior = read_repo(db, repo)
    known = [json.loads(p) for (p,) in db.execute('SELECT payload FROM opportunities')
             if resolve(db, json.loads(p).get('repo', '')) == repo]
    row = db.execute('SELECT run_id,expires,state FROM claims WHERE repo=?', (repo,)).fetchone()
    visited = db.execute('SELECT 1 FROM repository_visits WHERE repo=? AND run_id=?', (repo, run_id)).fetchone()
    active = row and row[2] == 'active' and row[1] > utc()
    if active:
        action = 'skip_this_run' if row[0] == run_id else 'busy'
    elif visited and not (prior and prior['status'] == 'partial'):
        action = 'skip_this_run'
    else:
        action = ('rescan' if rescan else 'resume' if prior and prior['status'] == 'partial'
                  else 'incremental' if prior or known else 'analyze')
    result = dict(repo=repo, action=action, previous=prior, known_opportunities=known, rescan_reason=rescan)
    if row and active:
        result['lease_expires_at'] = row[1]
    if not preview and action not in {'skip_this_run', 'busy'}:
        token = uuid.uuid4().hex
        expires = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
        db.execute('INSERT INTO claims VALUES (?,?,?,?,?) ON CONFLICT(repo) DO UPDATE SET run_id=excluded.run_id,token=excluded.token,expires=excluded.expires,state=excluded.state', (repo, run_id, token, expires, 'active'))
        db.execute('INSERT OR IGNORE INTO repository_visits VALUES (?,?,?)', (run_id, repo, utc()))
        checkpoint = deepcopy(prior) if prior else dict(repo=repo, coverage={'reviewed_urls': []}, memory={}, cursor={'last_issue_number': 0, 'pending_issue_numbers': []})
        checkpoint.update(status='partial', run_id=run_id, summary='Claimed; resume from persisted coverage', next_action='Read checkpoint; enumerate unprocessed items')
        save_repo(db, checkpoint)
        result.update(claim_token=token, lease_expires_at=expires)
    return result


def checkpoint(db, data, token):
    repo = data['repo'] = resolve(db, data['repo'])
    require_claim(db, repo, data['run_id'], token)
    prior = read_repo(db, repo) or {}
    old_cursor = prior.get('cursor', {})
    patch = data.get('cursor', {})
    # Only ingest_page can advance watermarks after durable enumeration.
    for key in ('last_issue_number', 'updates_checked_through'):
        if key in patch and patch[key] != old_cursor.get(key, 0 if key == 'last_issue_number' else None):
            raise ValueError('Cursor advancement is scanner-owned; finish a complete enumeration first')
    for key in ('memory', 'coverage', 'cursor'):
        data[key] = merge(prior.get(key, {}), data.get(key, {}))
    resolved = data.pop('resolved_issue_numbers', [])
    for n in resolved:
        if not db.execute('SELECT 1 FROM dispositions WHERE repo=? AND number=?', (repo, n)).fetchone():
            raise ValueError('Pending removal needs a durable issue disposition')
    data['cursor']['pending_issue_numbers'] = [n for n in data['cursor'].get('pending_issue_numbers', []) if n not in resolved]
    result = {**prior, **data}
    save_repo(db, result)
    if data['status'] != 'partial':
        db.execute("UPDATE claims SET state='done' WHERE repo=?", (repo,))
    return dict(repo=repo, status=data['status'], recorded=True)


def observe(db, item):
    """All source observations survive; dedup only by explicit canonical identity."""
    from sources import validate_item, entity_key, canonical
    validate_item(item)
    key = entity_key(item)
    # A second source may only know the exact canonical URL, not the numeric ID.
    for old_key, old_payload in list(db.execute('SELECT entity_key,payload FROM source_items')):
        old_item = json.loads(old_payload)
        if canonical(old_item['canonical_url']) == canonical(item['canonical_url']) and old_key != key:
            if old_key.startswith('github:'):
                key = old_key
            else:
                db.execute('UPDATE source_observations SET entity_key=? WHERE entity_key=?', (key, old_key))
                db.execute('DELETE FROM source_items WHERE entity_key=?', (old_key,))
    payload = json.dumps(item, sort_keys=True, ensure_ascii=False)
    db.execute('INSERT OR IGNORE INTO source_observations VALUES (?,?,?,?,?)', (item['source'], item['source_id'], key, payload, utc()))
    prior = db.execute('SELECT payload FROM source_items WHERE entity_key=?', (key,)).fetchone()
    if not prior or json.loads(prior[0])['updated_at'] <= item['updated_at']:
        db.execute('INSERT INTO source_items VALUES (?,?,?) ON CONFLICT(entity_key) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at', (key, payload, utc()))
    return key


def begin_scan(db, repo, run_id, token, scan_id):
    require_claim(db, repo, run_id, token)
    previous = read_repo(db, repo)['cursor']
    # Restart page enumeration after crash: mutable offset pages are not snapshots.
    stamp = utc()
    db.execute('INSERT INTO scans VALUES (?,?,?,?,?,?,?)', (scan_id, repo, run_id, stamp, 1, 0, json.dumps({'base': previous, 'max_number': previous.get('last_issue_number', 0)})))
    return stamp


def ingest_page(db, repo, run_id, token, scan_id, page, items, has_next, complete_evidence=True):
    require_claim(db, repo, run_id, token)
    row = db.execute('SELECT repo,run_id,started_at,next_page,complete,payload FROM scans WHERE scan_id=?', (scan_id,)).fetchone()
    if not row or row[0:2] != (repo, run_id) or row[3] != page or row[4]:
        raise ValueError('Wrong scan, page order, or already finalized scan')
    progress, record = json.loads(row[5]), read_repo(db, repo)
    pending = set(record['cursor'].get('pending_issue_numbers', []))
    for item in items:
        if resolve(db, item.get('repo', '').lower()) != repo:
            raise ValueError('Page repository does not match claim')
        observe(db, item)
        number = item.get('number')
        if number:
            progress['max_number'] = max(progress['max_number'], number)
        if item['kind'] == 'github_issue':
            done = db.execute('SELECT updated_at FROM dispositions WHERE repo=? AND number=?', (repo, number)).fetchone()
            if not done or done[0] < item['updated_at']:
                pending.add(number)
    complete = not has_next and complete_evidence
    record['cursor']['pending_issue_numbers'] = sorted(pending)
    if complete:
        record['cursor'].update(last_issue_number=progress['max_number'], updates_checked_through=row[2])
    record['coverage']['enumeration'] = {'scan_id': scan_id, 'next_page': page + 1 if has_next else None, 'complete': complete}
    save_repo(db, record)
    db.execute('UPDATE scans SET next_page=?,complete=?,payload=? WHERE scan_id=?', (page + 1, int(complete), json.dumps(progress), scan_id))
    return complete


def dispose(db, repo, number, updated_at, evidence):
    if type(number) is not int or number < 1 or not evidence:
        raise ValueError('Disposition requires number and conclusion/evidence')
    parsed = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Disposition requires timezone')
    updated_at = parsed.astimezone(timezone.utc).isoformat(timespec='microseconds')
    # Do not acknowledge a newer source revision with an older conclusion.
    candidates = [json.loads(p) for (p,) in db.execute('SELECT payload FROM source_items')]
    if any(resolve(db, x.get('repo', '').lower()) == repo and x.get('number') == number and x['updated_at'] > updated_at for x in candidates):
        raise ValueError('Disposition predates latest observed revision')
    prior = db.execute('SELECT updated_at FROM dispositions WHERE repo=? AND number=?', (repo, number)).fetchone()
    if prior and prior[0] > updated_at:
        raise ValueError('Disposition timestamp cannot regress')
    db.execute('INSERT INTO dispositions VALUES (?,?,?,?) ON CONFLICT(repo,number) DO UPDATE SET updated_at=excluded.updated_at,evidence=excluded.evidence', (repo, number, updated_at, json.dumps(evidence)))


def ingest_findings(db, repo, run_id, token, items):
    """Search/supplemental findings are durable pending work, never cursor receipts."""
    require_claim(db, repo, run_id, token)
    record = read_repo(db, repo)
    pending = set(record['cursor'].get('pending_issue_numbers', []))
    for item in items:
        if resolve(db, item.get('repo', '').lower()) != repo:
            raise ValueError('Finding repository does not match claim')
        observe(db, item)
        if item['kind'] == 'github_issue':
            done = db.execute('SELECT updated_at FROM dispositions WHERE repo=? AND number=?', (repo, item['number'])).fetchone()
            if not done or done[0] < item['updated_at']:
                pending.add(item['number'])
    record['cursor']['pending_issue_numbers'] = sorted(pending)
    save_repo(db, record)
