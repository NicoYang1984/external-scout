"""Pipeline regressions: real Git, temporary SQLite and fake network/agent boundaries."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import contributor
import opportunity
import pipeline_github as gh
from pipeline_store import Store
from opportunity import normalize, gate, digest, ROOT


def candidate(campaign='native_skill_fix'):
    stamp = datetime.now(timezone.utc).isoformat()
    return normalize({
        'schema_version': 'opportunity/v1',
        'source_repo': {'full_name': 'owner/repo', 'repository_id': 42, 'base_branch': 'main', 'commit': 'a' * 40},
        'target_issue': 'https://github.com/owner/repo/issues/7' if campaign == 'native_skill_fix' else None,
        'subject': 'https://github.com/product/runtime', 'campaign_type': campaign,
        'evidence': [{'id': 'proof', 'source': 'https://github.com/owner/repo/issues/7', 'finding': 'Reviewed fixture', 'checked_at': stamp}],
        'contribution_policy': {'verdict': 'allowed', 'sources': ['CONTRIBUTING.md'], 'requirements': [], 'prerequisites_met': True},
        'proposed_change': {'title': 'Fix native behavior', 'summary': 'Repair the fixture defect.', 'files': ['value.txt'], 'max_changed_lines': 20},
        'environment_requirements': {'executables': ['git'], 'required_env': [], 'notes': 'No external dependencies'},
        'validation_plan': [{'argv': [sys.executable, '-c', 'from pathlib import Path; assert Path("value.txt").read_text() == "fixed\\n"'], 'purpose': 'Check observable behavior', 'timeout_seconds': 30}],
        'expected_user_value': 'Correct native behavior', 'next_action': 'Implement minimal fix', 'status': 'ready',
        'checks': {x: {'result': 'pass', 'evidence_ids': ['proof']} for x in opportunity.CAMPAIGN_CHECKS[campaign]},
        'provenance': {'kind': 'new_candidate', 'recorded_at': stamp, 'source': 'fixture'},
        'existing_pr': None, 'outreach_channel': None,
    })


def pr():
    return {'number': 8, 'html_url': 'https://github.com/owner/repo/pull/8', 'state': 'open',
            'head': {'sha': 'b' * 40}, 'base': {'repo': {'id': 42}}, 'merged_at': None,
            'updated_at': '2026-10-29T00:00:00Z'}


def evidence(spec):
    return {'repository': {'id': 42}, 'commit': spec['source_repo']['commit'], 'policies': [],
            'issue': {'number': 7, 'state': 'open'}, 'timeline': [], 'comments': [],
            'pull_requests': [], 'coverage_complete': True}


class ContractTests(unittest.TestCase):
    def test_native_and_listing_are_independent_of_capabilities(self):
        for campaign in ('native_skill_fix', 'resource_listing'):
            self.assertEqual(gate(candidate(campaign))['decision'], 'GO')
        self.assertEqual(gate(candidate('product_integration'))['decision'], 'NO-GO')

    def test_integration_preserves_existing_capability_and_score_gate(self):
        from test_v2 import candidate as capability
        s = candidate('product_integration')
        s['capability_context'] = capability()
        self.assertEqual(gate(s)['decision'], 'GO')
        s['capability_context']['technical_fit']['capability_match'] = 1
        self.assertEqual(gate(s)['decision'], 'NO-GO')
        s['capability_context'] = capability()
        s['capability_context']['capability_ids'] = ['artifact_edit']
        self.assertEqual(gate(s)['decision'], 'NO-GO')

    def test_all_campaign_checks_are_required_with_real_references(self):
        for campaign in opportunity.CAMPAIGN_CHECKS:
            s = candidate(campaign)
            for check in opportunity.CAMPAIGN_CHECKS[campaign]:
                x = deepcopy(s)
                x['checks'][check]['result'] = 'unknown'
                self.assertEqual(gate(x)['decision'], 'NO-GO')
        x = candidate()
        x['checks']['real_defect']['evidence_ids'] = ['missing']
        with self.assertRaises(ValueError):
            normalize(x)

    def test_bad_contract_and_boolean_integer_are_rejected(self):
        for key in ('evidence', 'validation_plan', 'proposed_change'):
            x = candidate()
            del x[key]
            with self.assertRaises(ValueError):
                normalize(x)
        x = candidate()
        x['source_repo']['repository_id'] = True
        with self.assertRaises(ValueError):
            normalize(x)
        x = candidate()
        x['proposed_change']['files'] = ['../escape']
        with self.assertRaises(ValueError):
            normalize(x)

    def test_id_dedup_title_url_case_rename_and_campaign_separation(self):
        s = candidate()
        other = deepcopy(s)
        other['source_repo']['full_name'] = 'OWNER/REPO.git/'
        other['target_issue'] += '?noise=1'
        other['proposed_change']['title'] = 'A different title'
        self.assertEqual(normalize(other)['opportunity_id'], s['opportunity_id'])
        other['source_repo']['full_name'] = 'new/name'
        other['target_issue'] = 'https://github.com/new/name/issues/7'
        self.assertEqual(normalize(other)['opportunity_id'], s['opportunity_id'])
        self.assertNotEqual(candidate('resource_listing')['opportunity_id'], candidate('product_integration')['opportunity_id'])

    def test_pr_is_not_issue_and_no_cross_repository_binding(self):
        for target in ('https://github.com/owner/repo/pull/7', 'https://github.com/other/repo/issues/7'):
            x = candidate()
            x['target_issue'] = target
            with self.assertRaises(ValueError):
                normalize(x)

    def test_stale_future_and_blocked_policies_never_go(self):
        for date in ('2000-01-01T00:00:00Z', '2099-01-01T00:00:00Z'):
            x = candidate()
            x['evidence'][0]['checked_at'] = date
            self.assertEqual(gate(x)['decision'], 'NO-GO')
        x = candidate()
        x['contribution_policy']['prerequisites_met'] = False
        self.assertEqual(gate(x)['decision'], 'NO-GO')

    def test_historical_work_cannot_be_relabelled_or_executed(self):
        x = candidate()
        x['provenance']['kind'] = 'historical_import'
        with self.assertRaises(ValueError):
            normalize(x)
        x['status'] = 'historical'
        self.assertEqual(gate(normalize(x))['decision'], 'NO-GO')

    def test_merge_alone_never_creates_contact_task(self):
        x = candidate()
        outcome = {'status': 'merged', 'pr_url': pr()['html_url']}
        self.assertIsNone(opportunity.outreach_candidate(x, outcome))
        x['outreach_channel'] = {'kind': 'form', 'value': 'https://example.test/collaborate',
            'purpose': 'Explicit collaboration', 'evidence_ids': ['proof'], 'suitable': True,
            'verified_at': datetime.now(timezone.utc).isoformat()}
        task = opportunity.outreach_candidate(x, outcome)
        self.assertFalse(task['send_authorized'])
        x['outreach_channel']['suitable'] = False
        self.assertIsNone(opportunity.outreach_candidate(x, outcome))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_additive_database_keeps_old_payload_and_version(self):
        db = self.store.db
        old = '{"status":"rejected","support_level":"upstream_only"}'
        with db:
            db.execute('INSERT INTO opportunities VALUES (?,?,?,?)', ('u', 't', 't', old))
        self.store.put(candidate())
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
        self.assertEqual(db.execute('SELECT payload FROM opportunities').fetchone()[0], old)

    def test_duplicate_import_preserves_history_and_execution(self):
        x = candidate()
        self.assertFalse(self.store.put(x)['duplicate'])
        self.assertTrue(self.store.put(x)['duplicate'])
        oid = x['opportunity_id']
        self.assertEqual(len(self.store.history(oid)), 1)
        self.store.save(oid, 'test', stage='validated', commit='fixture')
        self.store.put(x)
        self.assertEqual(self.store.progress(oid)['commit'], 'fixture')
        x['next_action'] = 'change'
        with self.assertRaises(ValueError):
            self.store.put(x)

    def test_incremental_observation_only_records_changes(self):
        s = candidate()
        oid = self.store.put(s)['opportunity_id']
        out = gh.summarize(pr(), [], [], [], [])
        self.assertTrue(self.store.observe(oid, out)['changed'])
        self.assertFalse(self.store.observe(oid, out)['changed'])
        self.assertEqual(len(self.store.history(oid)), 2)
        self.store.close()
        self.store = Store(Path(self.temp.name))
        self.assertEqual(self.store.progress(oid)['outcome']['status'], 'review_pending')

    def test_cross_process_lock_and_crash_recovery(self):
        oid = self.store.put(candidate())['opportunity_id']
        script = 'from pipeline_store import Store; import sys; s=Store(sys.argv[1]);\nwith s.lock(sys.argv[2]): print("acquired")'
        env = {**os.environ, 'PYTHONPATH': str(Path(__file__).parent)}
        with self.store.lock(oid):
            p = subprocess.run([sys.executable, '-c', script, self.temp.name, oid], env=env, capture_output=True)
            self.assertNotEqual(p.returncode, 0)
        p = subprocess.run([sys.executable, '-c', script, self.temp.name, oid], env=env, capture_output=True)
        self.assertEqual(p.returncode, 0)

    def test_explicit_revision_preserves_old_attempt_but_invalidates_approval(self):
        s = candidate()
        oid = self.store.put(s)['opportunity_id']
        self.store.save(oid, 'old', stage='validated', worktree='/old/tree', authorization={'binding': 'old'})
        s['next_action'] = 'Revalidated source'
        revised = self.store.revise(s, 'Upstream advanced')
        self.assertEqual(revised['attempt'], 2)
        self.assertNotIn('authorization', self.store.progress(oid))
        self.assertEqual(self.store.history(oid)[-2]['payload']['progress']['worktree'], '/old/tree')

    def test_legacy_cli_and_new_handoff_share_database(self):
        path = Path(self.temp.name) / 'spec.json'
        path.write_text(json.dumps(candidate()))
        script = Path(__file__).with_name('registry.py')
        for command, args in [('handoff', ['--file', str(path)]), ('handoffs', []), ('list', [])]:
            p = subprocess.run([sys.executable, str(script), command, '--data-dir', self.temp.name, *args], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)


class GitHubTests(unittest.TestCase):
    def test_every_external_status_and_no_checks_not_success(self):
        p = pr()
        self.assertEqual(gh.summarize(p, [], [], [], [])['ci'], 'unknown')
        for conclusion, status in [('action_required', 'ci_action_required'), ('failure', 'ci_failed'), ('success', 'ci_passed')]:
            run = {'id': 1, 'workflow_id': 1, 'status': 'completed', 'conclusion': conclusion}
            self.assertEqual(gh.summarize(p, [], [run], [], [])['status'], status)
        review = {'id': 1, 'user': {'login': 'maintainer'}, 'state': 'CHANGES_REQUESTED', 'commit_id': p['head']['sha']}
        self.assertEqual(gh.summarize(p, [], [], [], [review])['status'], 'changes_requested')
        p['state'] = 'closed'
        self.assertEqual(gh.summarize(p, [], [], [], [])['status'], 'closed')
        p['merged_at'] = '2026-10-28T00:00:00Z'
        self.assertEqual(gh.summarize(p, [], [], [], [])['status'], 'merged')

    def test_latest_rerun_and_reviewer_decision_replace_old_results(self):
        runs = [{'id': 1, 'workflow_id': 1, 'status': 'completed', 'conclusion': 'failure'},
                {'id': 2, 'workflow_id': 1, 'status': 'completed', 'conclusion': 'success'}]
        reviews = [{'id': 1, 'user': {'login': 'a'}, 'state': 'CHANGES_REQUESTED'},
                   {'id': 2, 'user': {'login': 'a'}, 'state': 'APPROVED', 'commit_id': pr()['head']['sha']}]
        out = gh.summarize(pr(), [], runs, [], reviews)
        self.assertEqual((out['ci'], out['review']), ('passed', 'approved'))
        reviews.append({'id': 3, 'user': {'login': 'a'}, 'state': 'COMMENTED'})
        self.assertEqual(gh.summarize(pr(), [], [], [], reviews)['review'], 'approved')

    def test_pagination_incomplete_fails_and_no_mutating_endpoint(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(d)
            api = gh.GitHub(s.db)
            with patch.object(api, 'request', return_value=([{}] * 100, {'link': '<next>; rel="next"'})):
                with self.assertRaisesRegex(ValueError, 'Pagination'):
                    api.pages('/repos/o/r/pulls', max_pages=2)
            for method, path in [('POST', '/repos/o/r/issues'), ('GET', '//evil.test/repos/o/r'), ('GET', '/user')]:
                with self.assertRaises(ValueError):
                    api.request(method, path)
            s.close()

    def test_etag_304_retains_payload_and_pagination_headers(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(d)
            url = 'https://api.github.com/repos/o/r/pulls'
            with s.db:
                s.db.execute('INSERT INTO github_cache VALUES (?,?,?,?)', (url, 'etag-1', '[{"id":1}]', '{"link":"next"}'))
            api = gh.GitHub(s.db)
            with patch.object(api.opener, 'open', side_effect=HTTPError(url, 304, '', {}, None)) as call:
                data, headers = api.request('GET', '/repos/o/r/pulls')
                self.assertEqual(data, [{'id': 1}])
                self.assertEqual(headers['link'], 'next')
                self.assertEqual(call.call_args.args[0].get_header('If-none-match'), 'etag-1')
            s.close()

    def test_rate_limit_stops_and_does_not_assume_merge(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(d)
            api = gh.GitHub(s.db)
            with patch.object(api.opener, 'open', side_effect=HTTPError('u', 403, '', {}, None)) as call:
                with self.assertRaises(ValueError):
                    api.get('/repos/o/r')
                with self.assertRaises(ValueError):
                    api.get('/repos/o/r')
                self.assertEqual(call.call_count, 1)
            s.close()

    def test_head_change_during_query_preserves_previous_result(self):
        class API:
            def get(self, path, fresh=False):
                p = pr()
                if fresh:
                    p['head']['sha'] = 'c' * 40
                return p
            def pages(self, *args):
                return []
        with self.assertRaisesRegex(ValueError, 'changed during'):
            gh.track(API(), candidate(), pr()['html_url'])

    def test_existing_issue_fix_and_timeline_pr_block_execution(self):
        s = candidate()
        d = evidence(s)
        d['pull_requests'] = [{'head': 'someone:fix', 'title': 'fixes #7', 'body': '', 'url': 'pr'}]
        self.assertEqual(gh.duplicate_blockers(s, d), ['pr'])

    def test_real_historical_cases_are_classified_without_new_results(self):
        data = json.loads((ROOT / 'regression/github-cases.json').read_text())['cases']
        for name, status in [('awesome', 'merged'), ('marketing', 'ci_action_required')]:
            x = data[name]
            actual = gh.summarize(x['pr'], x['checks'], x['runs'], x['statuses'], x['reviews'])
            self.assertEqual(actual['status'], status)
            self.assertEqual(actual['review'], 'pending')
        specs = [normalize(json.loads(p.read_text())) for p in sorted((ROOT / 'examples').glob('*.json'))]
        self.assertEqual({s['campaign_type'] for s in specs}, set(opportunity.CAMPAIGN_CHECKS))
        self.assertTrue(all(gate(s)['decision'] == 'NO-GO' for s in specs))
        native = next(s for s in specs if s['campaign_type'] == 'native_skill_fix')
        self.assertEqual(native['checks']['real_defect']['result'], 'pass')
        self.assertEqual(native['checks']['no_duplicate']['result'], 'fail')


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = Store(root / 'data')
        self.checkout = root / 'checkout'
        self.checkout.mkdir()
        contributor.git(self.checkout, 'init', '-b', 'main')
        contributor.git(self.checkout, 'config', 'user.email', 'fixture@example.test')
        contributor.git(self.checkout, 'config', 'user.name', 'Fixture')
        (self.checkout / 'value.txt').write_text('broken\n')
        contributor.git(self.checkout, 'add', '.')
        contributor.git(self.checkout, 'commit', '-m', 'fixture')
        self.spec = candidate()
        self.spec['source_repo']['commit'] = contributor.git(self.checkout, 'rev-parse', 'HEAD')
        self.oid = self.store.put(self.spec)['opportunity_id']

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def execute(self, failing=False):
        calls = []
        real_git = contributor.git
        def local_git(cwd, *args):
            if args[0] == 'fetch':
                return ''
            return real_git(cwd, *args)
        def agent(spec, worktree, folder, task, prompt, read_only=False):
            calls.append(task)
            if not read_only:
                (worktree / 'value.txt').write_text('bad\n' if failing else 'fixed\n')
            return {'decision': 'ready', 'reason': 'Synthetic agent boundary; tests run for real.',
                    'pr_body': '## Upstream fixture template\n\nRepair the native behavior.'}
        with patch.object(contributor, 'preflight', return_value=self.checkout), \
             patch.object(contributor, 'dossier', return_value=evidence(self.spec)), \
             patch.object(contributor, 'git', side_effect=local_git):
            result = contributor.run(self.store, None, self.oid, self.checkout, resume=True, agent=agent)
        return result, calls

    def test_real_worktree_target_tests_commit_and_repeat(self):
        result, calls = self.execute()
        self.assertEqual(result['stage'], 'validated')
        self.assertEqual(calls, ['audit', 'implementation'])
        self.assertIn('## Upstream fixture template', result['pr_body'])
        self.assertEqual((self.checkout / 'value.txt').read_text(), 'broken\n')
        committed = contributor.commit(self.store, self.oid)
        self.assertEqual(committed['stage'], 'committed')
        self.assertEqual(contributor.commit(self.store, self.oid)['commit'], committed['commit'])
        self.assertEqual(contributor.run(self.store, None, self.oid, self.checkout)['commit'], committed['commit'])

    def test_failed_test_has_durable_checkpoint_and_resume_reuses_worktree(self):
        with self.assertRaisesRegex(ValueError, 'validation failed'):
            self.execute(failing=True)
        before = self.store.progress(self.oid)
        self.assertEqual(before['stage'], 'blocked')
        result, _ = self.execute()
        self.assertEqual(before['worktree'], result['worktree'])
        self.assertEqual(result['stage'], 'validated')

    def test_edit_after_validation_cannot_commit(self):
        result, _ = self.execute()
        (Path(result['worktree']) / 'value.txt').write_text('unvalidated\n')
        with self.assertRaisesRegex(ValueError, 'changed since validation'):
            contributor.commit(self.store, self.oid)

    def test_crash_after_commit_recovers_same_commit_without_duplicate(self):
        self.execute()
        save = self.store.save
        def crash(oid, kind, **kw):
            if kind == 'committed':
                raise OSError('crash after git commit before SQLite receipt')
            return save(oid, kind, **kw)
        with patch.object(self.store, 'save', side_effect=crash):
            with self.assertRaises(OSError):
                contributor.commit(self.store, self.oid)
        p = self.store.progress(self.oid)
        self.assertEqual(p['stage'], 'committing')
        sha = contributor.git(Path(p['worktree']), 'rev-parse', 'HEAD')
        self.assertEqual(contributor.commit(self.store, self.oid)['commit'], sha)

    def test_tests_that_modify_source_cannot_certify_the_result(self):
        result, _ = self.execute()
        s = deepcopy(self.spec)
        s['validation_plan'][0]['argv'] = [sys.executable, '-c', 'from pathlib import Path; Path("value.txt").write_text("mutated")']
        with self.assertRaisesRegex(ValueError, 'Tests changed source'):
            contributor.run_tests(s, Path(result['worktree']), Path(result['worktree']).parent)

    def test_publish_without_explicit_authorization_stops_before_network(self):
        self.execute()
        contributor.commit(self.store, self.oid)
        with self.assertRaisesRegex(ValueError, 'authorization'):
            contributor.publish(self.store, None, self.oid)

    def test_out_of_scope_file_is_blocked(self):
        result, _ = self.execute()
        w = Path(result['worktree'])
        (w / 'unrelated.txt').write_text('bad')
        with self.assertRaisesRegex(ValueError, 'scope'):
            contributor.inspect_diff(self.spec, w)

    def test_authorization_binds_commit_body_and_destination(self):
        self.execute()
        contributor.commit(self.store, self.oid)
        p = contributor.authorize(self.store, self.oid, 'me/repo', 'owner', 'Explicit fixture approval')
        self.assertEqual(p['authorization']['binding'], contributor.publication_binding(self.spec, p, 'me/repo'))
        self.store.save(self.oid, 'changed_body', pr_body='changed')
        with self.assertRaisesRegex(ValueError, 'authorization'):
            contributor.publish(self.store, None, self.oid)

    def test_ambiguous_publish_never_reposts(self):
        self.execute()
        contributor.commit(self.store, self.oid)
        contributor.authorize(self.store, self.oid, 'me/repo', 'owner', 'Explicit fixture approval')
        self.store.save(self.oid, 'crash', stage='publishing')
        class API:
            def pages(self, *a):
                return []
            def create_pr(self, *a):
                raise AssertionError('Must not repeat an uncertain POST')
        with self.assertRaisesRegex(ValueError, 'uncertain'):
            contributor.publish(self.store, API(), self.oid)

    def test_publish_uses_verified_commit_and_reconciles_response_loss(self):
        self.execute()
        contributor.commit(self.store, self.oid)
        p = contributor.authorize(self.store, self.oid, 'me/repo', 'owner', 'Explicit fixture approval')
        class API:
            posted = 0
            def pages(self, *a):
                return []
            def get(self, *a, **kw):
                return {'id': 99, 'parent': {'id': 42}, 'permissions': {'push': True}}
            def create_pr(self, repo, body):
                self.posted += 1
                raise OSError('simulated response loss')
        api = API()
        real_git = contributor.git
        def fake_push(cwd, *args):
            return '' if args[0] == 'push' else real_git(cwd, *args)
        with patch.object(contributor, 'dossier', return_value=evidence(self.spec)), patch.object(contributor, 'git', side_effect=fake_push):
            with self.assertRaises(OSError):
                contributor.publish(self.store, api, self.oid)
        self.assertEqual(self.store.progress(self.oid)['stage'], 'publishing')
        self.assertEqual(api.posted, 1)
        api.pages = lambda *a: [{'html_url': pr()['html_url'], 'head': {'label': 'me:' + p['branch'], 'sha': p['commit'], 'repo': {'full_name': 'me/repo'}}}]
        self.assertEqual(contributor.publish(self.store, api, self.oid)['pr_url'], pr()['html_url'])
        self.assertEqual(api.posted, 1)

    def test_tests_do_not_inherit_github_or_mail_credentials(self):
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'secret', 'MAIL_PASSWORD': 'secret'}):
            env = contributor.environment(self.spec)
            self.assertNotIn('GITHUB_TOKEN', env)
            self.assertNotIn('MAIL_PASSWORD', env)


if __name__ == '__main__':
    unittest.main()
