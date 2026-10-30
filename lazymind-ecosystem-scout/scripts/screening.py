"""Versioned screening, audit history and reports. No publishing or validation promotion."""
import argparse
import json
import math
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import state
from opportunity import CAMPAIGN_CHECKS, digest, encoded, gate, normalize, timestamp
from registry import canonical_repo
from repository_intelligence import field, fresh, persist, cached_profile, collect_profile

DEFAULT_POLICY = Path(__file__).resolve().parents[1]/'references/screening-policy.json'
DIMENSIONS = ('audience_fit','reach_potential','maintainer_activity','external_pr_friendliness',
              'technical_value','execution_feasibility','direct_exposure_path')
REQUIRED = ('accepts_external_pr','ai_allowed','prerequisites_met','no_duplicate','not_already_fixed','scope_fit')


def load_policy(path=None):
    p = json.loads(Path(path or DEFAULT_POLICY).read_text())
    if not isinstance(p.get('policy_version'),str) or not p['policy_version'].strip():
        raise ValueError('A policy version is required')
    if set(p['weights']) != set(CAMPAIGN_CHECKS):raise ValueError('Exactly three campaigns required')
    for weights in p['weights'].values():
        if set(weights)!=set(DIMENSIONS) or any(type(v) is not int or v<0 for v in weights.values()) or sum(weights.values())!=100:
            raise ValueError('Campaign weights must be nonnegative integers totaling 100')
    for group in ('windows','limits','effort_minutes'):
        for k,v in p[group].items():
            if type(v) is not int or not 1<=v<=10000:raise ValueError('Invalid positive limit: '+k)
    if p['limits']['page_size']>100 or p['limits']['max_pages']>10:raise ValueError('Page limits exceed transport contract')
    for k in ('cache_ttl_hours','evidence_max_age_days','external_min_sample'):
        if type(p[k]) is not int or p[k]<=0:raise ValueError('Invalid '+k)
    for k in ('stars_cap','forks_cap'):
        if type(p['reach'][k]) is not int or p['reach'][k]<=0:raise ValueError('Invalid reach cap')
    for group,keys in [('activity',('commit_fraction','response_fraction','release_fraction')),('friendliness',('merge_fraction','response_fraction','backlog_fraction'))]:
        if any(type(p[group][k]) not in (int,float) or not math.isfinite(p[group][k]) or not 0<=p[group][k]<=1 for k in keys) or abs(sum(p[group][k] for k in keys)-1)>1e-9:
            raise ValueError('Invalid component fractions')
    if not 0<=p['reach']['stars_fraction']<=1:raise ValueError('Invalid stars fraction')
    for k in ('short_commit_target','long_commit_target'):
        if type(p['activity'][k]) is not int or p['activity'][k]<=0:raise ValueError('Invalid activity target')
    for rubric in p['rubrics'].values():
        if any(type(v) is not int or not 0<=v<=5 for v in rubric.values()):raise ValueError('Invalid rubric')
    return p


def evidence_value(item, at, p):
    if not fresh(item,at,p['evidence_max_age_days']):return None
    return item['value']


def admission(candidate, p, at):
    """Screening HOLD is separate from (and cannot weaken) OpportunitySpec NO-GO."""
    profile = candidate['profile']; f=profile['fields']; review=candidate.get('review',{}); facts=review.get('facts',{})
    reject, hold = [], []
    for name in ('archived','disabled'):
        v=evidence_value(f.get(name),at,p)
        if v is True:reject.append(name)
        elif v is not False:hold.append(name+': unknown/stale')
    if not profile.get('repository_id'):hold.append('Repository ID not verified')
    if profile.get('errors'):hold.append('API access/budget incomplete: '+'; '.join(profile['errors']))
    bound = bool(profile.get('revision') and review.get('revision')==profile['revision'])
    if not bound:hold.append('Policy/verification review is not bound to current profile commit')
    def val(k):return evidence_value(facts.get(k),at,p) if bound else None
    if not profile.get('coverage',{}).get('documents') and val('policy_coverage_complete') is not True:
        hold.append('Policy document coverage incomplete; independent complete review required')
    for k in REQUIRED:
        v=val(k)
        if v is False:
            (hold if k=='prerequisites_met' else reject).append(k+': false')
        elif v is not True:hold.append(k+': unknown/stale')
    for k in ('maintainer_claimed','permission_required'):
        v=val(k)
        if v is None:hold.append(k+': unknown/stale')
        elif v is True and val('permission_granted') is not True:hold.append(k+': permission pending')
    auto=val('auto_close_external')
    if auto is True:
        if val('auto_close_exception') is False:reject.append('External PR auto-close; no valid exception')
        elif val('auto_close_exception') is not True:hold.append('External PR auto-close exception not verified')
    elif auto is not False:hold.append('External PR auto-close rules unknown')
    kind=candidate['campaign_type']
    if kind=='native_skill_fix':
        if val('real_defect') is not True:hold.append('Missing reproduction on current commit')
        if val('regression_test') is not True:hold.append('Regression test conditions not verified')
    if kind=='product_integration':
        if val('requires_new_core') is True:reject.append('Requires new LazyMind Core functionality')
        elif val('requires_new_core') is not False:hold.append('Existing capability/scope unknown')
    if val('environment_ready') is not True:hold.append('Execution environment not verified')
    spec = candidate.get('spec')
    execution = None
    if spec:
        spec=normalize(spec)
        if spec['campaign_type']!=kind or (profile.get('repository_id') is not None and spec['source_repo']['repository_id']!=profile['repository_id']):
            raise ValueError('Opportunity identity/campaign does not match profile')
        if spec['source_repo']['commit']!=profile.get('revision'):hold.append('Spec commit differs from profile')
        if kind=='product_integration' and not candidate.get('capability_facts'):
            execution={'decision':'NO-GO','reasons':['Pinned capability facts required for reproducible screening']}
        else:
            execution=gate(spec,timestamp(at),facts=candidate.get('capability_facts'))
        if spec.get('existing_pr') or spec['provenance']['kind']=='historical_import':reject.append('Existing/historical PR: track only')
        elif execution['decision']!='GO':hold.extend(execution['reasons'])
    else:hold.append('Complete verified OpportunitySpec required for handoff')
    if candidate.get('progress',{}).get('pr_url'):reject.append('Already submitted: track existing PR')
    return dict(decision='NO-GO' if reject else 'HOLD' if hold else 'GO',
                reasons=sorted(set(reject+hold)), execution_gate=execution)


def score_dimensions(c,p,at):
    f=c['profile']['fields']; facts=c.get('review',{}).get('facts',{})
    def v(k):return evidence_value(f.get(k),at,p)
    def fact(k):return evidence_value(facts.get(k),at,p)
    def n(k):
        x=v(k)
        window={'substantive_commits_30d':p['windows']['short_days'],'substantive_commits_90d':p['windows']['activity_days']}
        if k in window and f.get(k,{}).get('window_days')!=window[k]:return None
        if x is not None and (type(x) not in (int,float) or not math.isfinite(x) or x<0):raise ValueError('Invalid metric '+k)
        return x
    def part(x,source):return (x,[source])
    values={}
    for k in ('audience_fit','technical_value','direct_exposure_path'):
        name=fact(k)
        if name is not None and name not in p['rubrics'][k]:raise ValueError('Unknown rubric category: '+k)
        values[k]=[part(p['rubrics'][k].get(name),facts.get(k))]
    stars,forks=n('stargazers_count'),n('forks_count');w=p['reach']['stars_fraction']
    values['reach_potential']=[part(None if stars is None else 5*w*min(math.log1p(stars)/math.log1p(p['reach']['stars_cap']),1),f.get('stargazers_count')),
        part(None if forks is None else 5*(1-w)*min(math.log1p(forks)/math.log1p(p['reach']['forks_cap']),1),f.get('forks_count'))]
    # Each component also carries its maximum so unknowns produce honest intervals.
    maxima={'reach_potential':[5*w,5*(1-w)]}
    a=p['activity']; x,y=n('substantive_commits_30d'),n('substantive_commits_90d')
    responses=n('maintainer_responses');release=v('latest_release')
    recent_release=(0 if release==[] else (1 if 0<=(timestamp(at)-timestamp(release['published_at'])).total_seconds()<=p['windows']['activity_days']*86400 else 0)) if release is not None else None
    values['maintainer_activity']=[(None if x is None or y is None else 5*a['commit_fraction']*(min(x/a['short_commit_target'],1)+min(y/a['long_commit_target'],1))/2,[f.get('substantive_commits_30d'),f.get('substantive_commits_90d')]),
        part(None if responses is None else 5*a['response_fraction']*min(responses,1),f.get('maintainer_responses')),
        part(None if recent_release is None else 5*a['release_fraction']*recent_release,f.get('latest_release'))]
    maxima['maintainer_activity']=[5*a[k] for k in ('commit_fraction','response_fraction','release_fraction')]
    s=v('external_pr_sample');ratio=None
    if s and (type(s.get('sample_size')) is not int or s['sample_size']<0 or
              any(type(s.get('counts',{}).get(k)) is not int or s['counts'][k]<0 for k in ('merged','closed','open')) or
              sum(s['counts'].values())!=s['sample_size']):raise ValueError('Invalid PR sample counts')
    if s and s.get('complete') and not s.get('ambiguous_identity_count') and s['sample_size']>=p['external_min_sample'] and s['window_days']==p['windows']['external_pr_days']:
        ratio=s['counts']['merged']/s['sample_size']
    active,backlog=n('active_prs'),n('long_backlog_prs');b=p['friendliness']
    if active is not None and backlog is not None and backlog>active:raise ValueError('Backlog exceeds active PR count')
    external_responses=n('external_pr_responses')
    values['external_pr_friendliness']=[part(None if ratio is None else 5*b['merge_fraction']*ratio,f.get('external_pr_sample')),
        part(None if external_responses is None else 5*b['response_fraction']*min(external_responses,1),f.get('external_pr_responses')),
        (None if active is None or backlog is None else 5*b['backlog_fraction']*(1-backlog/max(active,1)),[f.get('active_prs'),f.get('long_backlog_prs')])]
    maxima['external_pr_friendliness']=[5*b[k] for k in ('merge_fraction','response_fraction','backlog_fraction')]
    minutes=fact('estimated_minutes');env=fact('environment_ready')
    if minutes is not None and (type(minutes) not in (int,float) or not math.isfinite(minutes) or minutes<=0):raise ValueError('Invalid effort estimate')
    values['execution_feasibility']=[(None if minutes is None or env is None else 5*max(0,1-minutes/p['effort_minutes'][c['campaign_type']]) if env is True else 0,[facts.get('estimated_minutes'),facts.get('environment_ready')])]
    result={}
    for k,parts in values.items():
        low=sum(x for x,_ in parts if x is not None)
        high=low+sum(maxima.get(k,[5])[i] for i,(x,_) in enumerate(parts) if x is None)
        result[k]=dict(value=round(low,4) if all(x is not None for x,_ in parts) else None,
                       range=[round(low,4),round(high,4)],weight=p['weights'][c['campaign_type']][k],
                       sources=[e for _,es in parts for e in es if e],
                       uncertainty=None if low==high else 'Missing/partial/stale component; not imputed')
    return result


def evaluate(c,p,at):
    profile=c['profile'];decision=admission(c,p,at)
    result=dict(key=c['key'],repo=profile['repo'],repository_id=profile.get('repository_id'),
                github_url='https://github.com/'+profile['repo'],campaign_type=c['campaign_type'],
                policy_version=p['policy_version'],policy_hash=digest(p),policy_snapshot=p,evaluated_at=at,
                collected_at=profile['collected_at'],profile_hash=digest(profile),
                capability_facts_hash=digest(c.get('capability_facts')),
                gate=decision,score=None,score_range=None,breakdown={},publication_authorized=False,
                fields=profile['fields'],review=c.get('review',{}),
                prescreened=profile['fields'].get('id',{}).get('value') is not None,
                deeply_verified=bool(c.get('spec')),progress={k:v for k,v in c.get('progress',{}).items() if k in {'stage','commit','pr_url','outcome','last_checked_at'}},
                contribution_origin='historical' if c.get('spec',{}).get('provenance',{}).get('kind')=='historical_import' else 'candidate',
                value_tracks={'personal_engineering_contribution':'potential' if c['campaign_type']=='native_skill_fix' else 'not_established',
                              'lazymind_marketing_value':'not_established', 'actual_exposure':'unknown','actual_users':'unknown'},
                next_action='补齐门槛证据；保留当前执行状态')
    if decision['decision']=='GO':
        breakdown=score_dimensions(c,p,at)
        low=sum(d['range'][0]*d['weight']/5 for d in breakdown.values())
        high=sum(d['range'][1]*d['weight']/5 for d in breakdown.values())
        result.update(breakdown=breakdown,score_range=[round(low,2),round(high,2)],
                      score=round(low,2) if all(d['value'] is not None or d['weight']==0 for d in breakdown.values()) else None,
                      next_action='按现有 Pipeline 复核/恢复；发布仍需绑定最终 Commit 的审批')
        if c['campaign_type']!='native_skill_fix':result['value_tracks']['lazymind_marketing_value']='potential_only'
    elif decision['decision']=='NO-GO':result['next_action']='停止实施；已有 PR 仅跟踪，不重复创建'
    result['opportunity_assessment']={k:c.get('review',{}).get('facts',{}).get(k,
        field(None,result['github_url'],at,unknown_reason='No reviewed opportunity evidence'))
        for k in ('target_users','audience_fit','distribution_entry','direct_exposure_path',
                  'technical_value','implementation_difficulty','estimated_minutes','environment_ready','user_feedback')}
    result['data_quality']='partial' if any(x.get('value') is None for x in profile['fields'].values()) else 'observed'
    result['evidence_references']=sorted({e['source_url'] for e in list(profile['fields'].values())+list(c.get('review',{}).get('facts',{}).values()) if e.get('source_url')})
    return result


def attach_existing(db,c):
    """Read current execution state; scoring must not upgrade or erase it."""
    c=deepcopy(c);tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    oid=normalize(c['spec'])['opportunity_id'] if c.get('spec') else c.get('key')
    if 'pipeline_state' in tables:
        row=db.execute('SELECT payload FROM pipeline_state WHERE opportunity_id=?',(oid,)).fetchone()
        if row:c['progress']=json.loads(row[0])
    return c


def queue_key(db,c):
    repo=canonical_repo(c.get('repo') or c['profile']['repo']);record=state.read_repo(db,state.resolve(db,repo)) or {}
    pending=record.get('status')=='partial' or bool(record.get('cursor',{}).get('pending_issue_numbers'))
    progress=attach_existing(db,c).get('progress',{})
    facts=c.get('review',{}).get('facts',{})
    policy_ready=all(facts.get(k,{}).get('value') is True for k in ('accepts_external_pr','ai_allowed','prerequisites_met'))
    return (0 if pending or progress.get('stage') in {'auditing','blocked','validated','committed','committing'} else 1,0 if policy_ready else 1,repo,c['key'])


def report(rows,p,run_id,at,discovered=None):
    def observed(row,key):
        out=row.get('progress',{}).get('outcome',{})
        return out.get('query_source')=='GitHub REST API' and bool(out.get(key))
    existing=[r for r in rows if r.get('progress',{}).get('pr_url') or observed(r,'pr_url')]
    # A replay cannot establish which PR was newly submitted in THIS screening run.
    funnel=dict(discovered=len(rows) if discovered is None else discovered,prescreened=sum(r['prescreened'] for r in rows),
                deeply_verified=sum(r['deeply_verified'] for r in rows),GO=sum(r['gate']['decision']=='GO' for r in rows),
                submitted=0,merged=0,observed_engagement=0,
                HOLD=sum(r['gate']['decision']=='HOLD' for r in rows),NO_GO=sum(r['gate']['decision']=='NO-GO' for r in rows),
                blocked=sum(r.get('progress',{}).get('stage')=='blocked' for r in rows),
                existing_prs=len(existing),historical_contributions=sum(r['contribution_origin']=='historical' for r in rows),
                existing_merged=sum(observed(r,'merged_at') for r in existing))
    top={k:[r['key'] for r in sorted((x for x in rows if x['campaign_type']==k and x['score_range'] is not None),key=lambda x:(-x['score_range'][0],x['key']))[:p['limits']['top_n']]] for k in CAMPAIGN_CHECKS}
    return dict(run_id=run_id,policy_version=p['policy_version'],policy_hash=digest(p),evaluated_at=at,
                external_writes=False,funnel=funnel,shortlist_by_campaign=top,results=rows)


def markdown(doc):
    def cell(x):return str(x).replace('|','\\|').replace('\n',' ') if x is not None else 'unknown'
    out=['# 仓库画像与机会筛选报告','',f"策略 `{doc['policy_version']}`；评估时刻 `{doc['evaluated_at']}`。仅本地筛选，未执行远端发布。",'',
         '分数是审查优先级，不是接受概率；Stars/Forks 不是曝光或用户数。未知分量给出区间，HOLD/NO-GO 不计算总分。','',
         '## Funnel Summary','', '```json',json.dumps(doc['funnel'],ensure_ascii=False,indent=2),'```','',
         'submitted/merged/observed_engagement 仅统计本次筛选新增实绩（均为 0）；已有和历史结果在独立字段中列明。','',
         '| 仓库 | Campaign | Stars/Forks | 最近已确认人工活动 | 外部 PR 样本 | 总分/范围 | 结论 | 下一步 |',
         '|---|---|---|---|---|---|---|---|']
    for r in doc['results']:
        f=r['fields'];val=lambda k:f.get(k,{}).get('value')
        sample=val('external_pr_sample')
        sample_text=(f"n={sample['sample_size']} / {sample['window_days']}天；{sample['counts']}；比例={sample['observed_merge_fraction']}" if sample else 'unknown')
        out.append('| '+' | '.join(cell(x) for x in (r['repo'],r['campaign_type'],f"{val('stargazers_count')}/{val('forks_count')}",val('latest_confirmed_human_activity'),sample_text,r['score'] if r['score'] is not None else r['score_range'],r['gate']['decision'],r['next_action']))+' |')
    for r in doc['results']:
        out+=['',f"### {r['repo']} · {r['campaign_type']}",'', '原因：'+cell('; '.join(r['gate']['reasons']) or '所有硬门槛已通过；排名不授予发布权限'),'',
              '价值分轨：'+cell(r['value_tracks']),'','贡献政策、受众、技术价值、实施条件与预估分钟（均含证据）：','',
              '```json',json.dumps({'review':r['review'],'assessment':r['opportunity_assessment']},ensure_ascii=False,indent=2),'```','',
              '评分明细（0–5；包含权重、范围和来源）：','', '```json',json.dumps(r['breakdown'],ensure_ascii=False,indent=2),'```','',
              '原始证据：'+ '、'.join('['+str(i+1)+']('+u+')' for i,u in enumerate(r['evidence_references'])),'']
    return '\n'.join(out).rstrip()+'\n'


class ReadBudget:
    def __init__(self,api,limit):self.api,self.remaining=api,limit
    def request(self,method,path,**kwargs):
        if method!='GET':raise ValueError('Screening is GET-only')
        if self.remaining<=0:raise ValueError('Repository request budget exhausted')
        self.remaining-=1
        return self.api.request(method,path,**kwargs)
    def get(self,path):return self.request('GET',path)[0]


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['screen','profile'])
    parser.add_argument('--policy',type=Path,default=DEFAULT_POLICY)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--input',type=Path,required=True,help='Candidate list; profile command collects explicit repositories only')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--at',help='Fixed evaluation time for offline replay only')
    parser.add_argument('--handoff-dir',type=Path,help='Export existing verified specs locally; never author missing evidence')
    args=parser.parse_args(argv)
    p=load_policy(args.policy);at=args.at or datetime.now(timezone.utc).isoformat();timestamp(at)
    from pipeline_store import Store
    store=Store(args.data_dir)
    try:
        candidates=json.loads(args.input.read_text())
        deferred=candidates.get('deferred',[]) if isinstance(candidates,dict) else []
        if isinstance(candidates,dict):candidates=candidates['candidates']
        keys=[c['key'] for c in candidates]
        if len(keys)!=len(set(keys)):raise ValueError('Duplicate candidate key')
        identities=[normalize(c['spec'])['opportunity_id'] if c.get('spec') else (c.get('profile',{}).get('repository_id') or canonical_repo(c.get('repo') or c['profile']['repo']),c['campaign_type'],c.get('target_issue') or c.get('subject') or 'repository') for c in candidates]
        if len(identities)!=len(set(identities)):raise ValueError('Duplicate canonical candidate identity')
        if args.command=='profile':
            if args.at:raise ValueError('Live collection cannot be backdated')
            from pipeline_github import GitHub
            api=GitHub(store.db,os.environ.get('GITHUB_TOKEN'),budget=p['limits']['requests_per_batch'])
            ordered=sorted(candidates,key=lambda c:queue_key(store.db,c))
            selected=ordered[:p['limits']['repositories_per_batch']];acquired=[]
            for i,c in enumerate(selected):
                local_api=ReadBudget(api,p['limits']['requests_per_repository'])
                repo=c.get('repo') or c['profile']['repo']
                value=cached_profile(store.db,repo,p,at)
                if value is not None:
                    from urllib.parse import quote
                    try:
                        root='/repos/'+canonical_repo(repo)
                        meta=local_api.get(root)
                        head=local_api.get(root+'/commits/'+quote(meta['default_branch'],safe=''))['sha']
                        if meta['id']!=value['repository_id'] or head!=value['revision'] or any(meta.get(k)!=value['fields'][k]['value'] for k in ('updated_at','pushed_at','archived','disabled')):value=None
                    except (ValueError,OSError,KeyError):value=None
                if value is None or value.get('review_hash')!=digest(c.get('review',{})):
                    value=collect_profile(local_api,repo,p,at,
                        c.get('review'),
                        lambda v:persist(store.db,v,'repository_intelligence',args.run_id,at),deep=i<p['limits']['deep_per_batch'])
                    value['review_hash']=digest(c.get('review',{})) if i<p['limits']['deep_per_batch'] else digest({})
                    persist(store.db,value,'repository_intelligence',args.run_id,at)
                acquired.append({**c,'profile':value})
            output=dict(run_id=args.run_id,candidates=acquired,deferred=[c['key'] for c in ordered[len(selected):]],external_writes=False)
            # screen accepts the candidates list; keep deferred queue explicit beside it.
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
            return
        if isinstance(candidates,dict):candidates=candidates['candidates']
        rows=[]
        for c in sorted(candidates,key=lambda c:queue_key(store.db,c)):
            c=attach_existing(store.db,c)
            r=evaluate(c,p,at);rows.append(r)
            persist(store.db,c['profile'],'repository_intelligence',args.run_id,c['profile']['collected_at'])
            persist(store.db,r,'repository_screening',args.run_id,at)
            if args.handoff_dir and r['gate']['decision']=='GO':
                spec=normalize(c['spec']);args.handoff_dir.mkdir(parents=True,exist_ok=True)
                (args.handoff_dir/(spec['opportunity_id']+'.json')).write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n')
        doc=report(rows,p,args.run_id,at,len(candidates)+len(deferred))
        doc['deferred']=deferred
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
        args.output.with_suffix('.md').write_text(markdown(doc))
        with store.db:
            store.db.execute('INSERT INTO runs(run_id,recorded_at,payload) VALUES (?,?,?)',
                             (args.run_id,at,encoded({'run_id':args.run_id,'status':'completed','screening_report':str(args.output),'funnel':doc['funnel'],'policy_version':p['policy_version']})))
        print(json.dumps(doc['funnel'],ensure_ascii=False))
    finally:store.close()


if __name__=='__main__':main()
