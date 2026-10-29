import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import registry
import state
import scan
from test_v2 import candidate


class CLITest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.script=Path(__file__).with_name('registry.py')

    def tearDown(self):self.temp.cleanup()

    def call(self,command,*args,payload=None,ok=True):
        argv=[sys.executable,str(self.script),command,'--data-dir',str(self.root/'data'),*args]
        if payload is not None:
            path=self.root/'input.json';path.write_text(json.dumps(payload));argv+=['--file',str(path)]
        r=subprocess.run(argv,capture_output=True,text=True)
        self.assertEqual(r.returncode==0,ok,r.stderr)
        return json.loads(r.stdout) if ok else r.stderr

    def test_cli_checkpoint_requires_token_and_heartbeat(self):
        c=self.call('repo-start','--repo','Owner/Repo','--run-id','r')
        p=dict(repo='owner/repo',run_id='r',status='partial',summary='x',coverage={'reviewed_urls':[]},memory={'a':1},next_action='x')
        self.call('repo-put',payload=p,ok=False)
        self.call('repo-heartbeat','--repo','owner/repo','--run-id','r','--claim-token',c['claim_token'])
        self.call('repo-put','--claim-token',c['claim_token'],payload=p)
        self.assertEqual(self.call('repo-memory','--repo','owner/repo')['previous']['memory']['a'],1)

    def test_actual_process_crash_after_claim(self):
        directory=self.root/'data'
        code='import registry,state,os; from pathlib import Path; db=registry.connect(Path(%r)); db.execute("BEGIN IMMEDIATE"); state.claim(db,"o/r","r"); db.commit(); os._exit(19)' % str(directory)
        env={**os.environ,'PYTHONPATH':str(self.script.parent)}
        result=subprocess.run([sys.executable,'-c',code],env=env)
        self.assertEqual(result.returncode,19)
        with sqlite3.connect(directory/'opportunities.sqlite3') as db:
            db.execute("UPDATE claims SET expires='2000-01-01'")
        self.assertEqual(self.call('repo-start','--repo','o/r','--run-id','r')['action'],'resume')

    def test_concurrent_fresh_initialization(self):
        with ThreadPoolExecutor(4) as pool:
            r=list(pool.map(lambda _:self.call('init'),range(4)))
        self.assertEqual(len(r),4)

    def test_old_database_refused_without_writing(self):
        root=self.root/'data';root.mkdir()
        path=root/'opportunities.sqlite3'
        with sqlite3.connect(path) as db:db.execute('CREATE TABLE old_memory(x TEXT)')
        before=path.read_bytes()
        self.call('init',ok=False)
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse((root/'config.json').exists())

    def test_action_history_and_rename(self):
        x={**candidate(), 'url':'https://github.com/o/r/issues/1','repo':'o/r','title':'x','route':'issue_analysis',
           'category':'workflow_gap','evidence_level':'source_reviewed','summary':'fixture','sources':['https://github.com/o/r/issues/1'],'next_action':'review'}
        self.call('put',payload=x)
        x['public_contribution_url']='https://github.com/o/r/pull/2'
        x['review_status']='pending'
        self.call('put',payload=x)
        x.pop('review_status');x.pop('public_contribution_url')
        self.call('put',payload=x)
        rows=self.call('list');self.assertEqual(rows[0]['review_status'],'pending')
        self.assertEqual(len(self.call('history')),3)
        self.call('repo-identify','--repo','o/r','--repo-id','10')
        self.call('repo-identify','--repo','new/r','--repo-id','10')
        self.call('put',payload=x)
        rows=self.call('list')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['url'],'https://github.com/new/r/issues/1')
        x['review_status']='merged'
        self.call('put',payload=x,ok=False)
        self.assertEqual(len(self.call('history')),4)

    def test_full_live_adapter_empty_tail_advances(self):
        class Transport:
            def get(self,url):return [],{}
        db=registry.connect(self.root/'data')
        result=scan.scan(db,'o/r',10,'r',Transport())
        self.assertTrue(result['cursor_advanced'])
        self.assertIn('updates_checked_through',state.read_repo(db,'o/r')['cursor'])
        db.close()


if __name__=='__main__':unittest.main()
