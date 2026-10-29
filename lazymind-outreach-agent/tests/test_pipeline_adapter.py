import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from outreach_core import OutreachStore
from pipeline_adapter import import_pipeline


class PipelineAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'tasks.json'
        self.store = OutreachStore(Path(self.temp.name) / 'outreach.sqlite3')
        self.store.init()
        self.task = {
            'task_id': 'outreach_fixture', 'opportunity_id': 'fixture',
            'source_repo': 'owner/repo', 'source_campaign': 'native_skill_fix',
            'pr_url': 'https://github.com/owner/repo/pull/1', 'observed_status': 'merged',
            'expected_user_value': 'Fix a real bug', 'status': 'candidate_review', 'send_authorized': False,
            'evidence': [{'id': 'channel', 'source': 'https://example.test/collaborate', 'finding': 'Explicit collaboration invitation'}],
            'channel': {'kind': 'email', 'value': 'collaborate@example.test', 'purpose': 'Research collaboration',
                        'evidence_ids': ['channel'], 'suitable': True, 'verified_at': datetime.now(timezone.utc).isoformat()},
        }

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def save(self):
        self.path.write_text(json.dumps({'tasks': [self.task]}))

    def test_no_channel_empty_tasks_produce_no_leads(self):
        self.path.write_text('{"tasks":[]}')
        self.assertEqual(import_pipeline(self.store, self.path)['imported'], [])

    def test_import_preserves_source_campaign_and_cannot_send(self):
        self.save()
        result = import_pipeline(self.store, self.path)
        self.assertEqual(result['messages_sent'], 0)
        lead = self.store.conn.execute('SELECT * FROM leads').fetchone()
        self.assertEqual(lead['permission_status'], 'not_granted')
        self.assertEqual(lead['language'], 'language_unknown')
        self.assertIn('native_skill_fix', lead['risk_notes'])
        self.assertEqual(self.store.conn.execute('SELECT COUNT(*) FROM approvals').fetchone()[0], 0)

    def test_repeat_never_overwrites_suppression_or_creates_duplicate(self):
        self.save()
        result = import_pipeline(self.store, self.path)
        self.store.suppress(result['imported'][0], 'declined')
        self.assertEqual(import_pipeline(self.store, self.path)['imported'], [])
        self.assertEqual(self.store.conn.execute('SELECT status FROM leads').fetchone()[0], 'suppressed')

    def test_stale_unsuitable_missing_evidence_or_permission_transfer_rejected(self):
        from copy import deepcopy
        original = deepcopy(self.task)
        for field, value in [('suitable', False), ('evidence_ids', ['missing']), ('verified_at', '2000-01-01T00:00:00Z')]:
            self.task = deepcopy(original)
            self.task['channel'][field] = value
            self.save()
            with self.assertRaises(ValueError):
                import_pipeline(self.store, self.path)
        self.task = original
        self.task['send_authorized'] = True
        self.save()
        with self.assertRaises(ValueError):
            import_pipeline(self.store, self.path)


if __name__ == '__main__':
    unittest.main()
