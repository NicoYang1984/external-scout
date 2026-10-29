import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import registry
import state
import policy
import sources
import scan
import migrate


def issue(n=1, updated='2026-01-01T00:00:00Z', pr=False):
    raw = dict(id=n,number=n,title='fixture',html_url=f'https://github.com/o/r/issues/{n}',updated_at=updated,state='open')
    if pr:
        raw['pull_request'] = {'html_url':f'https://github.com/o/r/pull/{n}'}
    return sources.GitHubAdapter('o/r',10,None).normalize(raw)


def candidate():
    return dict(schema_version=2,status='analyzed',support_level='existing',capability_ids=['workflow_observation'],
                capability_evidence=[{'source':'PR873','scope':'read projection'}],runnable_path='Read the authorized session projection',
                technical_fit=dict(capability_match=4,integration_cost=2,validation=1,recovery_fit=1),
                ecosystem_value=dict(user_value=3,collaboration=2,audience_evidence=0),score_evidence=['fixture evidence'])


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.db=registry.connect(self.root)
        with self.db:
            self.claim=state.claim(self.db,'o/r','r1')
        self.token=self.claim['claim_token']

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def expire(self):
        with self.db:
            self.db.execute("UPDATE claims SET expires='2000-01-01'")

    def checkpoint(self, **kw):
        data=dict(repo='o/r',run_id='r1',status='partial',summary='test',coverage={'reviewed_urls':[]},next_action='continue')
        data.update(kw)
        return state.checkpoint(self.db,data,self.token)

    def test_crash_before_first_checkpoint_is_resumable(self):
        self.assertEqual(state.read_repo(self.db,'o/r')['status'],'partial')
        self.expire()
        with self.db:
            c=state.claim(self.db,'o/r','r1')
        self.assertEqual(c['action'],'resume')
        self.assertNotEqual(c['claim_token'],self.token)
        with self.assertRaises(ValueError), self.db:
            self.checkpoint(summary='stale writer')

    def test_cross_run_active_worker_not_stolen(self):
        with self.db:
            self.assertEqual(state.claim(self.db,'o/r','r2')['action'],'busy')

    def test_claim_and_initial_checkpoint_rollback_together(self):
        with self.assertRaises(RuntimeError):
            with self.db:
                state.claim(self.db,'a/b','x')
                raise RuntimeError('crash before commit')
        self.assertIsNone(state.read_repo(self.db,'a/b'))
        self.assertIsNone(self.db.execute("SELECT * FROM claims WHERE repo='a/b'").fetchone())

    def test_concurrent_claim_same_run_only_one_wins(self):
        def worker(_):
            db=registry.connect(self.root)
            with db:
                db.execute('BEGIN IMMEDIATE')
                r=state.claim(db,'a/b','r')
            db.close();return r['action']
        with ThreadPoolExecutor(2) as pool:
            values=list(pool.map(worker,range(2)))
        self.assertEqual(sorted(values),['analyze','skip_this_run'])

    def test_unfinished_page_never_advances_cursor(self):
        with self.db:
            state.begin_scan(self.db,'o/r','r1',self.token,'s')
            state.ingest_page(self.db,'o/r','r1',self.token,'s',1,[issue(100)],True)
        r=state.read_repo(self.db,'o/r')
        self.assertEqual(r['cursor']['last_issue_number'],0)
        self.assertNotIn('updates_checked_through',r['cursor'])
        self.assertEqual(r['cursor']['pending_issue_numbers'],[100])
        with self.assertRaises(ValueError), self.db:
            self.checkpoint(cursor={'last_issue_number':100})

    def test_pages_complete_pending_survives_and_pr_not_issue(self):
        with self.db:
            state.begin_scan(self.db,'o/r','r1',self.token,'s')
            state.ingest_page(self.db,'o/r','r1',self.token,'s',1,[issue(3),issue(4,pr=True)],True)
            state.ingest_page(self.db,'o/r','r1',self.token,'s',2,[issue(10)],False)
            self.checkpoint(cursor={'last_issue_number':10,'pending_issue_numbers':[]})
        r=state.read_repo(self.db,'o/r')
        self.assertEqual(r['cursor']['pending_issue_numbers'],[3,10])
        self.assertEqual(r['cursor']['last_issue_number'],10)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM source_items').fetchone()[0],3)

    def test_out_of_order_page_and_failed_batch_roll_back(self):
        with self.db:
            state.begin_scan(self.db,'o/r','r1',self.token,'s')
        with self.assertRaises(ValueError), self.db:
            state.ingest_page(self.db,'o/r','r1',self.token,'s',2,[issue()],False)
        with self.assertRaises(ValueError), self.db:
            state.ingest_page(self.db,'o/r','r1',self.token,'s',1,[issue(),{}],False)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM source_items').fetchone()[0],0)

    def test_cross_run_old_updated_issue_reopens_pending(self):
        with self.db:
            state.begin_scan(self.db,'o/r','r1',self.token,'s')
            state.ingest_page(self.db,'o/r','r1',self.token,'s',1,[issue()],False)
            state.dispose(self.db,'o/r',1,'2026-01-01T00:00:00Z',{'decision':'reviewed'})
            self.checkpoint(resolved_issue_numbers=[1],status='completed')
            c=state.claim(self.db,'o/r','r2')
            self.assertEqual(c['action'],'incremental')
            state.begin_scan(self.db,'o/r','r2',c['claim_token'],'s2')
            state.ingest_page(self.db,'o/r','r2',c['claim_token'],'s2',1,[issue(1,'2026-02-01T00:00:00Z')],False)
        self.assertEqual(state.read_repo(self.db,'o/r')['cursor']['pending_issue_numbers'],[1])

    def test_supplemental_search_finding_is_pending_without_watermark(self):
        with self.db:
            state.ingest_findings(self.db,'o/r','r1',self.token,[issue(999)])
        cursor=state.read_repo(self.db,'o/r')['cursor']
        self.assertEqual(cursor['pending_issue_numbers'],[999])
        self.assertEqual(cursor['last_issue_number'],0)

    def test_pending_cannot_be_removed_without_disposition(self):
        with self.assertRaises(ValueError), self.db:
            self.checkpoint(resolved_issue_numbers=[1])

    def test_deep_memory_and_coverage_keep_prior_history(self):
        with self.db:
            self.checkpoint(memory={'nested':{'a':1},'decisions':['old']},coverage={'reviewed_urls':['https://github.com/o/r/issues/1']})
            self.checkpoint(memory={'nested':{'b':2},'decisions':['new']},coverage={'reviewed_urls':[]})
            self.checkpoint(memory={'nested':None,'decisions':[]})
        r=state.read_repo(self.db,'o/r')
        self.assertEqual(r['memory']['nested'],{'a':1,'b':2})
        self.assertEqual(r['memory']['decisions'],['old','new'])
        self.assertEqual(len(r['coverage']['reviewed_urls']),1)
        self.assertGreaterEqual(self.db.execute('SELECT COUNT(*) FROM repository_history').fetchone()[0],4)
        with self.assertRaises(ValueError), self.db:
            self.checkpoint(memory={'nested':'replace all'})

    def test_rename_keeps_memory_and_same_run_dedup(self):
        with self.db:
            self.checkpoint(memory={'remember':'yes'},status='completed')
            state.identify(self.db,'o/r',10)
            state.identify(self.db,'new/r',10)
        self.assertEqual(state.resolve(self.db,'o/r'),'new/r')
        self.assertEqual(state.read_repo(self.db,'new/r')['memory']['remember'],'yes')
        with self.db:
            self.assertEqual(state.claim(self.db,'o/r','r1')['action'],'skip_this_run')
            self.assertEqual(state.claim(self.db,'new/r','r2')['action'],'incremental')

    def test_renamed_repo_rejects_disposition_older_than_observation(self):
        with self.db:
            state.observe(self.db,issue(1,'2026-02-01T00:00:00Z'))
            self.checkpoint(status='completed')
            state.identify(self.db,'o/r',10)
            state.identify(self.db,'new/r',10)
        with self.assertRaises(ValueError), self.db:
            state.dispose(self.db,'new/r',1,'2026-01-01T00:00:00Z',{'decision':'stale'})

    def test_different_sources_same_subject_dedup_without_losing_provenance(self):
        a=issue(); b={**a,'source':'public_skill_catalog','source_id':'mirror','repository_id':None}
        with self.db:
            state.observe(self.db,b)
            state.observe(self.db,a)
            state.observe(self.db,a)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM source_items').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM source_observations').fetchone()[0],2)

    def test_migration_readonly_source_preserves_history_and_orphan_claim(self):
        self.db.close()
        # Construct the original V1 schema fixture in an isolated directory.
        # Standalone distribution uses the bundled pristine V1 test fixture instead.
        olddir=self.root/'v1'; olddir.mkdir()
        source=olddir/'opportunities.sqlite3'
        with sqlite3.connect(source) as db:
            db.executescript((Path(__file__).parent/'fixtures/v1-schema.sql').read_text())
            db.execute("INSERT INTO repository_visits VALUES ('lost','a/b','2026-01-01')")
            db.execute("INSERT INTO runs(run_id,recorded_at,payload) VALUES ('r','t','{}')")
            old_op=json.dumps({'url':'https://github.com/x/y','repo':'x/y','status':'ready_for_review','score':9})
            old_repo=json.dumps({'repo':'x/y','run_id':'r','status':'completed','cursor':{'last_issue_number':120,'pending_issue_numbers':[115]},'memory':{'nested':{'keep':'yes'}},'coverage':{'reviewed_urls':['https://github.com/x/y/issues/1']}})
            db.execute('INSERT INTO opportunities VALUES (?,?,?,?)',('https://github.com/x/y','t','t',old_op))
            db.execute('INSERT INTO history(url,recorded_at,payload) VALUES (?,?,?)',('https://github.com/x/y','t',old_op))
            db.execute('INSERT INTO repositories VALUES (?,?,?)',('x/y','t',old_repo))
            db.execute('INSERT INTO repository_history(repo,recorded_at,payload) VALUES (?,?,?)',('x/y','t',old_repo))
        before=hashlib.sha256(source.read_bytes()).hexdigest()
        dest=self.root/'v2'
        migrate.migrate(source,dest)
        self.assertEqual(before,hashlib.sha256(source.read_bytes()).hexdigest())
        db=registry.connect(dest)
        with db:
            self.assertEqual(state.claim(db,'a/b','lost')['action'],'resume')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM runs').fetchone()[0],1)
        self.assertEqual(db.execute('SELECT payload FROM history').fetchone()[0],old_op)
        current=json.loads(db.execute('SELECT payload FROM opportunities').fetchone()[0])
        self.assertEqual(current['status'],'verification_pending')
        copied=state.read_repo(db,'x/y')
        self.assertEqual(copied['legacy_cursor']['last_issue_number'],120)
        self.assertEqual(copied['cursor']['last_issue_number'],0)
        self.assertEqual(copied['cursor']['pending_issue_numbers'],[115])
        self.assertEqual(copied['memory']['nested']['keep'],'yes')
        self.assertEqual(db.execute("SELECT payload FROM repository_history WHERE repo='x/y' ORDER BY id LIMIT 1").fetchone()[0],old_repo)
        db.close()
        with self.assertRaises(ValueError): migrate.migrate(source,dest)
        self.db=registry.connect(self.root)


class PolicyTest(unittest.TestCase):
    def test_known_failures_documented_and_unavailable_are_excluded(self):
        for id_ in ['artifact_edit','generated_mandatory_review','skill_autonomous_delivery','cap09','arbitrary_host_lifecycle']:
            x=candidate();x['capability_ids']=[id_]
            with self.assertRaises(ValueError): policy.validate(x)
            x['status']='rejected';policy.validate(x)
            self.assertFalse(x['eligible'])

    def test_high_stars_low_fit_never_recommended(self):
        x=candidate();x['technical_fit']['capability_match']=1
        x['stars']=100000;x['ecosystem_value']=dict(user_value=4,collaboration=3,audience_evidence=3)
        policy.validate(x)
        self.assertFalse(x['recommended_for_validation'])
        self.assertEqual(x['promotion_priority'],'not_established')

    def test_small_project_keeps_collaboration_potential_not_top_channel(self):
        x=candidate();x['stars']=1
        policy.validate(x)
        self.assertTrue(x['recommended_for_validation'])
        self.assertEqual(x['promotion_priority'],'not_established')

    def test_scores_reject_boolean_and_out_of_range(self):
        for v in (True,5,-1):
            x=candidate();x['technical_fit']['capability_match']=v
            with self.assertRaises(ValueError):policy.validate(x)

    def test_pr_creation_and_comments_do_not_imply_results(self):
        x=candidate();x['public_contribution_url']='https://github.com/o/r/pull/2'
        policy.validate(x)
        self.assertEqual(x['review_status'],'not_requested')
        self.assertEqual(x['trial_status'],'not_started')
        x['review_status']='merged'
        with self.assertRaises(ValueError):policy.validate(x)
        x['review_status']='pending';x['trial_status']='converted'
        with self.assertRaises(ValueError):policy.validate(x)

    def test_ready_requires_actual_validation(self):
        x=candidate();x['status']='ready_for_review'
        with self.assertRaises(ValueError):policy.validate(x)
        x['validation_status']='passed';x['action_evidence']={'validation_status':{'state':'passed','source':'run-log','checked_at':'2026-10-27'}}
        policy.validate(x)

    def test_stale_evidence_requires_refresh(self):
        facts=deepcopy(policy.catalog())
        for f in facts['capabilities']:f['last_verified']='2020-01-01'
        self.assertFalse(policy.assess(candidate(),facts)[0])

    def test_catalog_has_version_sources_date_and_scoped_failures(self):
        facts=policy.catalog()['capabilities']
        self.assertEqual({x['category'] for x in facts},set(range(1,15)))
        self.assertEqual({x['status'] for x in facts},policy.STATUSES)
        for x in facts:
            for field in ['version','sources','last_verified','limitations']:self.assertTrue(x[field])

    def test_legacy_ready_records_are_not_silently_promoted(self):
        x={'status':'ready_for_review'};policy.validate(x)
        self.assertEqual(x['status'],'verification_pending')


class AdapterTest(unittest.TestCase):
    def test_portable_paths(self):
        with patch.dict(os.environ,{'LAZYMIND_SCOUT_DATA_DIR':'/tmp/team-state'}):
            self.assertEqual(str(state.data_dir()),'/tmp/team-state')
        self.assertIsNone(registry.DEFAULT_CONFIG['project_root'])
        self.assertNotIn('/Users/',json.dumps(registry.DEFAULT_CONFIG))

    def test_rate_limit_stops_no_retry(self):
        from urllib.error import HTTPError
        transport=sources.GitHubHTTP(3)
        with patch.object(transport.opener,'open',side_effect=HTTPError('u',429,'limited',{'Retry-After':'60'},None)) as call:
            with self.assertRaises(ValueError):transport.get('https://api.github.com/repos/o/r/issues')
            with self.assertRaises(ValueError):transport.get('https://api.github.com/repos/o/r/issues')
        self.assertEqual(call.call_count,1)

    def test_github_only_get_rejects_other_hosts(self):
        with self.assertRaises(ValueError):sources.GitHubHTTP().get('https://example.com/private')

    def test_catalog_readonly_and_source_schema(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'catalog.json'
            x=issue();x['kind']='skill_directory'
            path.write_text(json.dumps(dict(source_url='https://example.org/skills',version='v1',items=[x])))
            before=path.read_bytes()
            page=sources.CatalogAdapter(path).page()
            self.assertFalse(page.has_next)
            self.assertEqual(page.items[0]['source'],'public_skill_catalog')
            self.assertEqual(before,path.read_bytes())

    def test_feedback_requires_authorization(self):
        x=issue();x['kind']='product_feedback'
        with self.assertRaises(ValueError):sources.validate_item(x)
        x.update(access='authorized',authorization_ref='scope-1')
        sources.validate_item(x)

    def test_snapshot_replay_does_not_advance_live_watermark(self):
        class Transport:
            def get(self,url):return [],{}
        with tempfile.TemporaryDirectory() as d:
            db=registry.connect(Path(d))
            result=scan.scan(db,'o/r',10,'r',Transport(),snapshot=True)
            self.assertFalse(result['cursor_advanced'])
            self.assertTrue(result['pagination_terminal'])
            db.close()

    def test_full_scan_advances_and_budgeted_scan_preserves_pending(self):
        class Transport:
            def get(self,url):
                return [dict(id=1,number=1,title='x',html_url='https://github.com/o/r/issues/1',updated_at='2026-01-01T00:00:00Z',state='open')],{'Link':'<next>; rel="next"'}
        with tempfile.TemporaryDirectory() as d:
            db=registry.connect(Path(d))
            result=scan.scan(db,'o/r',10,'r',Transport(),max_pages=1)
            self.assertFalse(result['cursor_advanced'])
            self.assertEqual(state.read_repo(db,'o/r')['cursor']['pending_issue_numbers'],[1])
            db.close()


if __name__=='__main__': unittest.main()
