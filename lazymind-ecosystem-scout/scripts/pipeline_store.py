"""Additive tables in the existing V2 SQLite database; old readers stay valid."""
import json
from contextlib import contextmanager
from pathlib import Path

import registry
from opportunity import normalize, encoded, digest, gate
from state import utc

HELD_LOCKS = []

SCHEMA = '''
CREATE TABLE IF NOT EXISTS opportunity_specs (
 opportunity_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline_events (
 id INTEGER PRIMARY KEY, opportunity_id TEXT NOT NULL, kind TEXT NOT NULL,
 recorded_at TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline_state (
 opportunity_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS github_cache (
 url TEXT PRIMARY KEY, etag TEXT, payload TEXT NOT NULL, headers TEXT NOT NULL);
'''


class Store:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.db = registry.connect(self.root)
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    @contextmanager
    def lock(self, oid):
        # Kernel releases this lock on process death. No expiring lease can let a
        # second worker publish while a slow first worker is still running.
        import fcntl
        if not oid.startswith('opp_') or len(oid) != 28 or any(c not in '0123456789abcdef' for c in oid[4:]):
            raise ValueError('Invalid opportunity ID')
        folder = self.root / 'pipeline' / oid
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / '.lock').open('a') as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Opportunity is busy in another process') from None
            try:
                HELD_LOCKS.append(f.fileno())
                yield folder
            finally:
                HELD_LOCKS.remove(f.fileno())
                fcntl.flock(f, fcntl.LOCK_UN)

    def put(self, raw):
        spec = normalize(raw)
        oid = spec['opportunity_id']
        with self.lock(oid), self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.db.execute('SELECT payload FROM opportunity_specs WHERE opportunity_id=?', (oid,)).fetchone()
            duplicate = bool(old)
            if old and json.loads(old[0])['provenance'] != spec['provenance']:
                raise ValueError('Original provenance is immutable; historical work is not new work')
            if not old or old[0] != encoded(spec):
                progress = self.progress(oid)
                if progress.get('stage') and progress.get('stage') != 'imported':
                    raise ValueError('Execution already started; preserve spec and reconcile existing run')
                self.db.execute('INSERT INTO opportunity_specs VALUES (?,?,?) ON CONFLICT(opportunity_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at',
                                (oid, encoded(spec), utc()))
                self.event(oid, 'spec_imported' if not old else 'spec_revised', spec)
        return {'opportunity_id': oid, 'duplicate': duplicate, 'gate': gate(spec)}

    def get(self, oid):
        row = self.db.execute('SELECT payload FROM opportunity_specs WHERE opportunity_id=?', (oid,)).fetchone()
        if not row:
            raise ValueError('Unknown opportunity: ' + oid)
        return json.loads(row[0])

    def revise(self, raw, reason):
        """Explicit fresh attempt; retain prior worktree, evidence and authorization history."""
        spec = normalize(raw)
        oid = spec['opportunity_id']
        if not reason.strip():
            raise ValueError('Revision requires a reason')
        with self.lock(oid), self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old, progress = self.get(oid), self.progress(oid)
            if old['provenance'] != spec['provenance']:
                raise ValueError('Original provenance is immutable')
            if old.get('existing_pr') or progress.get('pr_url') or progress.get('stage') in {'publishing', 'submitted', 'committing'}:
                raise ValueError('Reconcile/track the existing contribution before starting any new attempt')
            self.event(oid, 'attempt_superseded', {'reason': reason, 'spec': old, 'progress': progress})
            self.db.execute('UPDATE opportunity_specs SET payload=?,updated_at=? WHERE opportunity_id=?', (encoded(spec), utc(), oid))
            value = {'stage': 'imported', 'attempt': progress.get('attempt', 1) + 1}
            self.db.execute('INSERT INTO pipeline_state VALUES (?,?) ON CONFLICT(opportunity_id) DO UPDATE SET payload=excluded.payload', (oid, encoded(value)))
            self.event(oid, 'spec_revised', spec)
        return {'opportunity_id': oid, 'attempt': value['attempt'], 'gate': gate(spec)}

    def list(self):
        return [json.loads(x[0]) for x in self.db.execute('SELECT payload FROM opportunity_specs ORDER BY opportunity_id')]

    def progress(self, oid):
        row = self.db.execute('SELECT payload FROM pipeline_state WHERE opportunity_id=?', (oid,)).fetchone()
        return json.loads(row[0]) if row else {}

    def event(self, oid, kind, payload):
        self.db.execute('INSERT INTO pipeline_events(opportunity_id,kind,recorded_at,payload) VALUES (?,?,?,?)',
                        (oid, kind, utc(), encoded(payload)))

    def save(self, oid, kind, **patch):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            value = {**self.progress(oid), **patch}
            self.db.execute('INSERT INTO pipeline_state VALUES (?,?) ON CONFLICT(opportunity_id) DO UPDATE SET payload=excluded.payload', (oid, encoded(value)))
            self.event(oid, kind, patch)
        return value

    def observe(self, oid, snapshot):
        prior = self.progress(oid).get('outcome', {})
        changed = digest(prior) != digest(snapshot)
        if changed:
            self.save(oid, 'github_changed', outcome=snapshot, last_checked_at=utc(), last_query_error=None)
        else:
            with self.db:
                value = {**self.progress(oid), 'last_checked_at': utc(), 'last_query_error': None}
                self.db.execute('UPDATE pipeline_state SET payload=? WHERE opportunity_id=?', (encoded(value), oid))
        return {'changed': changed, **snapshot}

    def history(self, oid):
        return [{'kind': k, 'recorded_at': t, 'payload': json.loads(p)} for k, t, p in self.db.execute(
            'SELECT kind,recorded_at,payload FROM pipeline_events WHERE opportunity_id=? ORDER BY id', (oid,))]
