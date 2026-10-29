"""Reproduce original V1 gaps using a temporary database only."""
import json, subprocess, sys, tempfile
from pathlib import Path
script=Path(__file__).resolve().parents[1]/'original/lazymind-ecosystem-scout/scripts/registry.py'
with tempfile.TemporaryDirectory() as d:
 def call(command,payload=None,*extra):
  argv=[sys.executable,str(script),command,'--data-dir',d,*extra]
  if payload is not None:
   p=Path(d)/'input.json';p.write_text(json.dumps(payload));argv+=['--file',str(p)]
  r=subprocess.run(argv,capture_output=True,text=True,check=True)
  return json.loads(r.stdout)
 first=call('repo-start',None,'--repo','o/r','--run-id','r1')
 after_crash=call('repo-start',None,'--repo','o/r','--run-id','r1')
 record=dict(repo='o/r',status='partial',run_id='r1',summary='test',coverage={'reviewed_urls':['first'],'page_cursor':'page2'},next_action='next',cursor={'last_issue_number':100,'pending_issue_numbers':[3]},memory={'nested':{'a':1},'decisions':['first']})
 call('repo-put',record)
 record.update(cursor={'last_issue_number':200,'pending_issue_numbers':[]},memory={'nested':{'b':2},'decisions':['second']},coverage={'reviewed_urls':[],'page_cursor':'still-unfinished'})
 call('repo-put',record)
 final=call('repo-memory',None,'--repo','o/r')['previous']
 result=dict(crash_without_checkpoint=dict(action=after_crash['action'],previous=after_crash['previous']),unfinished_pagination_cursor=final['cursor'],latest_memory=final['memory'],latest_coverage=final['coverage'],history_count=len(call('repo-history')),personal_project_root=json.loads((Path(d)/'config.json').read_text())['project_root'])
 print(json.dumps(result,ensure_ascii=False,indent=2))
