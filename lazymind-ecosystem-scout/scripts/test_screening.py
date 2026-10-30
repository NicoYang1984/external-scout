"""Repository intelligence regressions use fixed synthetic snapshots, never live results."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import policy as capabilities
import state
from opportunity import digest, encoded, normalize
from pipeline_store import Store
from repository_intelligence import build_profile, collect_profile, field, persist, cached_profile, pages
from screening import load_policy, evaluate, report, markdown, queue_key, attach_existing, ReadBudget
from test_pipeline import candidate as spec_fixture

AT='2026-10-30T12:00:00+00:00'
REV='a'*40
URL='https://github.com/owner/repo'


def snapshot():
    prs=[dict(id=i,html_url=URL+'/pull/'+str(i),created_at='2026-10-01T00:00:00Z',
              state='closed',merged_at='2026-10-10T00:00:00Z',author_association='NONE',user={'type':'User','login':'guest'}) for i in range(1,11)]
    commit=dict(sha='b'*40,author={'type':'User','login':'owner'},committer={'type':'User','login':'owner'},
                commit={'committer':{'date':'2026-10-29T00:00:00Z'}})
    return dict(repo='owner/repo',observed_at=AT,revision=REV,
                repository=dict(id=42,full_name='owner/repo',stargazers_count=2,forks_count=0,archived=False,disabled=False,
                    default_branch='main',created_at='2025-01-01T00:00:00Z',updated_at=AT,pushed_at=AT),
                commits={'complete':True,'items':[commit]},commit_details={commit['sha']:{'complete':True,'files':[{'filename':'main.py','patch':'+return correct_value'}]}},
                pull_requests={'complete':True,'items':prs},open_prs={'complete':True,'items':[]},
                responses={'complete':True,'items':[dict(user={'type':'User','login':'owner'},author_association='OWNER',created_at='2026-10-29T00:00:00Z',html_url=URL+'/issues/7#issuecomment-1')]},
                releases={'complete':True,'items':[]},documents_complete=True,documents=[])


def candidate(kind='native_skill_fix'):
    p=load_policy();s=spec_fixture(kind)
    s['evidence'][0]['checked_at']=AT;s['provenance']['recorded_at']=AT
    if kind=='product_integration':
        from test_v2 import candidate as context
        s['capability_context']=context()
    facts={k:field(True,URL,AT) for k in ('accepts_external_pr','ai_allowed','prerequisites_met','no_duplicate','not_already_fixed','scope_fit','environment_ready','real_defect','regression_test')}
    facts.update({k:field(False,URL,AT) for k in ('maintainer_claimed','permission_required','auto_close_external','requires_new_core')})
    facts.update({k:field(v,URL,AT) for k,v in dict(audience_fit='shared_task',technical_value='reproduced_bug',direct_exposure_path='none',estimated_minutes=15).items()})
    return dict(key=s['opportunity_id'],campaign_type=kind,profile=build_profile(snapshot(),p),
                review={'revision':REV,'facts':facts},spec=s,capability_facts=capabilities.catalog() if kind=='product_integration' else None)


class ScreeningTests(unittest.TestCase):
    def setUp(self):self.p=load_policy()
    def test_small_native_quality_not_excluded_and_weights(self):
        c=candidate();r=evaluate(c,self.p,AT)
        self.assertEqual(r['gate']['decision'],'GO')
        self.assertGreater(r['score'],0)
        self.assertEqual(list(self.p['weights']['native_skill_fix'].values()),[5,10,15,20,30,20,0])
        self.assertFalse(r['publication_authorized'])
        self.assertEqual(r['value_tracks']['lazymind_marketing_value'],'not_established')
    def test_high_stars_policy_prohibition_and_duplicate(self):
        for key in ('accepts_external_pr','ai_allowed','no_duplicate','not_already_fixed','scope_fit'):
            c=candidate();c['profile']['fields']['stargazers_count']['value']=10**8
            c['review']['facts'][key]['value']=False
            r=evaluate(c,self.p,AT)
            self.assertEqual(r['gate']['decision'],'NO-GO',key);self.assertIsNone(r['score'])
    def test_claim_without_permission_is_hold(self):
        c=candidate();c['review']['facts']['maintainer_claimed']['value']=True
        self.assertEqual(evaluate(c,self.p,AT)['gate']['decision'],'HOLD')
    def test_bot_only_recent_updates_not_high_activity(self):
        c=candidate();raw=snapshot();raw['commits']['items'][0]['author']['type']='Bot'
        raw['responses']['items']=[];c['profile']=build_profile(raw,self.p)
        r=evaluate(c,self.p,AT)
        self.assertEqual(r['breakdown']['maintainer_activity']['value'],0)
        self.assertIsNone(c['profile']['fields']['latest_confirmed_human_activity']['value'])
    def test_link_churn_and_unknown_commit_identity(self):
        raw=snapshot();sha=raw['commits']['items'][0]['sha'];raw['commit_details'][sha]['files'][0]['patch']='+https://example.org?utm_source=directory'
        self.assertEqual(build_profile(raw,self.p)['fields']['substantive_commits_30d']['value'],0)
        raw['commits']['items'][0]['author']=None
        self.assertIsNone(build_profile(raw,self.p)['fields']['substantive_commits_30d']['value'])
    def test_insufficient_ambiguous_and_partial_pr_samples_no_fake_rate(self):
        for mode in ('small','ambiguous','partial'):
            raw=snapshot()
            if mode=='small':raw['pull_requests']['items']=raw['pull_requests']['items'][:1]
            if mode=='ambiguous':del raw['pull_requests']['items'][0]['author_association']
            if mode=='partial':raw['pull_requests']['complete']=False
            c=candidate();c['profile']=build_profile(raw,self.p)
            stats=c['profile']['fields']['external_pr_sample']['value'];self.assertIsNone(stats['observed_merge_fraction'])
            r=evaluate(c,self.p,AT);self.assertIsNone(r['score']);self.assertLess(*r['score_range'])
    def test_core_unknown_stale_revision_and_environment_hold(self):
        for mode in ('stale','revision','missing','environment'):
            c=candidate()
            if mode=='stale':c['review']['facts']['no_duplicate']['observed_at']='2025-01-01T00:00:00Z'
            if mode=='revision':c['review']['revision']='c'*40
            if mode=='missing':del c['review']['facts']['no_duplicate']
            if mode=='environment':c['review']['facts']['environment_ready']['value']=False
            r=evaluate(c,self.p,AT);self.assertEqual(r['gate']['decision'],'HOLD');self.assertIsNone(r['score'])

    def test_truncated_policy_tree_cannot_be_overridden_by_popularity(self):
        c=candidate();c['profile']['coverage']['documents']=False
        c['profile']['fields']['stargazers_count']['value']=10**8
        self.assertEqual(evaluate(c,self.p,AT)['gate']['decision'],'HOLD')
    def test_campaign_specific_and_fixed_reproducibility(self):
        a=evaluate(candidate(),self.p,AT);b=evaluate(candidate('resource_listing'),self.p,AT)
        self.assertNotEqual(a['score'],b['score'])
        c=candidate();before=deepcopy(c)
        self.assertEqual(encoded(evaluate(c,self.p,AT)),encoded(evaluate(c,self.p,AT)))
        self.assertEqual(c,before)
    def test_existing_capability_gate_and_core_scope_preserved(self):
        c=candidate('product_integration')
        self.assertEqual(evaluate(c,self.p,AT)['gate']['decision'],'GO')
        c['spec']['capability_context']['technical_fit']['capability_match']=0
        self.assertEqual(evaluate(c,self.p,AT)['gate']['decision'],'HOLD')
        c['review']['facts']['requires_new_core']['value']=True
        self.assertEqual(evaluate(c,self.p,AT)['gate']['decision'],'NO-GO')
    def test_policy_assess_fixed_time_not_wall_clock(self):
        c=candidate('product_integration')['spec']['capability_context']
        from opportunity import timestamp
        self.assertTrue(capabilities.assess(c,now=timestamp(AT))[0])
        self.assertFalse(capabilities.assess(c,now=timestamp('2030-01-01T00:00:00Z'))[0])

    def test_pinned_capability_snapshot_survives_catalog_changes(self):
        c=candidate('product_integration');before=evaluate(c,self.p,AT)
        with patch.object(capabilities,'catalog',side_effect=AssertionError('Must use pinned facts')):
            self.assertEqual(before,evaluate(c,self.p,AT))
        del c['capability_facts']
        self.assertEqual(evaluate(c,self.p,AT)['gate']['decision'],'HOLD')
    def test_reports_separate_history_from_new_results(self):
        c=candidate();c['progress']={'pr_url':URL+'/pull/1','outcome':{'query_source':'GitHub REST API','pr_url':URL+'/pull/1','merged_at':AT}}
        r=evaluate(c,self.p,AT);doc=report([r],self.p,'r1',AT)
        self.assertEqual(doc['funnel']['submitted'],0);self.assertEqual(doc['funnel']['merged'],0)
        self.assertEqual(doc['funnel']['existing_prs'],1);self.assertEqual(doc['funnel']['existing_merged'],1)
        self.assertIn('Stars/Forks 不是曝光',markdown(doc))
    def test_bad_policy_and_numeric_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'p.json';p=deepcopy(self.p);p['weights']['resource_listing']['audience_fit']=99;path.write_text(json.dumps(p))
            with self.assertRaises(ValueError):load_policy(path)
        for bad in (-1,True,float('nan')):
            c=candidate();c['profile']['fields']['stargazers_count']['value']=bad
            with self.assertRaises(ValueError):evaluate(c,self.p,AT)


class StoreAndCollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root);self.p=load_policy()
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def test_policy_upgrade_keeps_approval_evidence_and_old_database(self):
        c=candidate();oid=self.store.put(c['spec'])['opportunity_id']
        self.store.save(oid,'fixture_approval',stage='committed',authorization={'commit':'b'*40,'evidence':'fixture'})
        before={table:list(self.store.db.execute('SELECT * FROM '+table)) for table in ('opportunity_specs','pipeline_state','pipeline_events','opportunities','history')}
        for version in ('v1','v2'):
            p=deepcopy(self.p);p['policy_version']=version
            persist(self.store.db,c['profile'],'repository_intelligence','r',AT)
            persist(self.store.db,evaluate(c,p,AT),'repository_screening','r',AT)
        for table,rows in before.items():self.assertEqual(rows,list(self.store.db.execute('SELECT * FROM '+table)))
        self.assertEqual(self.store.db.execute('PRAGMA user_version').fetchone()[0],2)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM source_observations WHERE source='repository_screening'").fetchone()[0],2)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM repo_ids').fetchone()[0],1)
    def test_cache_freshness_policy_version_and_pending_order(self):
        c=candidate();profile=c['profile'];profile['collection_policy_hash']=digest(self.p)
        persist(self.store.db,profile,'repository_intelligence','r',AT)
        self.assertIsNotNone(cached_profile(self.store.db,'owner/repo',self.p,AT))
        self.assertIsNone(cached_profile(self.store.db,'owner/repo',self.p,'2026-11-01T00:00:00Z'))
        p=deepcopy(self.p);p['policy_version']='v2';self.assertIsNone(cached_profile(self.store.db,'owner/repo',p,AT))
        with self.store.db:state.claim(self.store.db,'owner/repo','r')
        self.assertEqual(queue_key(self.store.db,c)[0],0)
    def test_api_failure_does_not_infer_results_or_continue(self):
        for code in (403,429):
            class API:
                def get(self,path):raise ValueError('GitHub HTTP '+str(code))
            profile=collect_profile(API(),'owner/repo',self.p,AT)
            self.assertIsNone(profile['fields']['stargazers_count']['value'])
            c=candidate();c['profile']=profile;r=evaluate(c,self.p,AT)
            self.assertEqual(r['gate']['decision'],'HOLD');self.assertIsNone(r['score'])
    def test_partial_pagination_and_duplicate_rows(self):
        class API:
            def request(self,*args,**kwargs):return [{'id':1,'created_at':AT}],{'Link':'<next>; rel="next"'}
        result=pages(API(),'/repos/o/r/pulls',2,100)
        self.assertFalse(result['complete']);self.assertEqual(len(result['items']),1)
    def test_archived_stops_after_metadata_and_unknown_policy_stops_before_prs(self):
        class API:
            def __init__(self,archived):self.paths=[];self.archived=archived
            def get(self,path):
                self.paths.append(path)
                if '/commits/' in path:return {'sha':REV}
                if '/git/trees/' in path:return {'tree':[],'truncated':False}
                return {**snapshot()['repository'],'archived':self.archived}
        for archived,count in ((True,1),(False,3)):
            api=API(archived);profile=collect_profile(api,'owner/repo',self.p,AT)
            self.assertEqual(len(api.paths),count);self.assertFalse(profile['errors'])
    def test_get_only_and_repo_budget(self):
        class API:
            def request(self,*args,**kwargs):return [],{}
        api=ReadBudget(API(),1)
        with self.assertRaises(ValueError):api.request('POST','/repos/o/r/pulls')
        api.request('GET','/repos/o/r')
        with self.assertRaises(ValueError):api.request('GET','/repos/o/r')

    def test_complete_collection_is_read_only_and_retains_raw_evidence(self):
        raw=snapshot()
        class API:
            def get(self,path):
                if '/git/trees/' in path:return {'tree':[],'truncated':False}
                if '/commits/' in path:return {'sha':REV}
                return {**raw['repository'],'temp_clone_token':'DO_NOT_PERSIST'}
            def request(self,method,path,**kwargs):
                if method!='GET':raise AssertionError('Remote write')
                if '/pulls?state=all' in path:return raw['pull_requests']['items'],{}
                if '/pulls?state=open' in path:return [],{}
                if '/commits?' in path:return raw['commits']['items'],{}
                if '/commits/' in path:return raw['commit_details']['b'*40],{}
                if '/issues/comments?' in path:return raw['responses']['items'],{}
                return [],{}
        profile=collect_profile(API(),'owner/repo',self.p,AT,candidate()['review'])
        self.assertFalse(profile['errors'])
        self.assertEqual(profile['fields']['substantive_commits_90d']['value'],1)
        self.assertEqual(profile['fields']['external_pr_sample']['value']['sample_size'],10)
        self.assertNotIn('DO_NOT_PERSIST',encoded(profile))
        self.assertIn('raw_snapshot',profile)

    def test_screening_cannot_authorize_publish(self):
        import contributor
        c=candidate();self.store.put(c['spec'])
        self.store.save(c['key'],'fixture',stage='committed',commit='b'*40,title='fixture',pr_body='fixture',branch='fixture')
        persist(self.store.db,evaluate(c,self.p,AT),'repository_screening','r',AT)
        with self.assertRaisesRegex(ValueError,'Missing authorization'):
            contributor.publish(self.store,None,c['key'])

    def test_policy_content_change_requires_version_bump(self):
        c=candidate();persist(self.store.db,evaluate(c,self.p,AT),'repository_screening','r',AT)
        p=deepcopy(self.p);p['external_min_sample']=11
        with self.assertRaisesRegex(ValueError,'version bump'):
            persist(self.store.db,evaluate(c,p,AT),'repository_screening','r',AT)

    def test_historical_profile_cannot_reverse_verified_rename(self):
        c=candidate()
        with self.store.db:
            state.identify(self.store.db,'owner/repo',42)
            state.identify(self.store.db,'owner/renamed',42)
        persist(self.store.db,c['profile'],'repository_intelligence','r',AT)
        self.assertEqual(state.resolve(self.store.db,'owner/repo'),'owner/renamed')
    def test_cli_replay_exports_same_spec_and_preserves_unauthorized_progress(self):
        c=candidate();self.store.put(c['spec']);self.store.save(c['key'],'fixture',stage='committed',commit='b'*40)
        inp=self.root/'input.json';out=self.root/'report.json';inp.write_text(json.dumps([c]))
        script=Path(__file__).with_name('ranking.py')
        cmd=[sys.executable,str(script),'screen','--input',str(inp),'--output',str(out),'--run-id','fixture','--at',AT,'--data-dir',str(self.root),'--handoff-dir',str(self.root/'handoffs')]
        completed=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(completed.returncode,0,completed.stderr)
        self.assertEqual(json.loads(out.read_text())['funnel']['GO'],1)
        self.assertEqual(normalize(json.loads(next((self.root/'handoffs').glob('*.json')).read_text())),normalize(c['spec']))
        self.assertNotIn('authorization',self.store.progress(c['key']))
        self.assertTrue(out.with_suffix('.md').exists())


if __name__=='__main__':unittest.main()
