"""Evidence envelopes and bounded repository profiles on existing source observations."""
import base64
import json
import re
from copy import deepcopy
from datetime import timedelta
from pathlib import PurePosixPath
from urllib.parse import urlencode, quote

import state
from opportunity import digest, timestamp
from registry import canonical_repo

PROFILE_VERSION = 'repository-intelligence/v1'
MAINTAINERS = {'OWNER', 'MEMBER', 'COLLABORATOR'}
EXTERNAL = {'NONE', 'FIRST_TIMER', 'FIRST_TIME_CONTRIBUTOR', 'CONTRIBUTOR'}


def field(value, source, at, confidence='high', unknown_reason=None):
    result = dict(value=value, source_url=source, observed_at=at)
    if value is None:
        result['unknown_reason'] = unknown_reason or 'Not collected or not established'
    else:
        result['confidence'] = confidence
    return result


def fresh(item, at, days):
    return bool(item and item.get('value') is not None and item.get('confidence') in {'high', 'medium'}
                and item.get('source_url') and item.get('observed_at') and
                0 <= (timestamp(at)-timestamp(item['observed_at'])).total_seconds() <= days*86400)


def human(user):
    return (isinstance(user, dict) and user.get('type') == 'User' and
            '[bot]' not in user.get('login', '').lower())


def external(pr):
    """Operational API identity, not an assertion about employment or independence."""
    if pr.get('user', {}).get('type') == 'Bot' or pr.get('author_association') in MAINTAINERS:
        return False
    if human(pr.get('user')) and pr.get('author_association') in EXTERNAL:
        return True
    return None


def substantive(detail):
    """Conservative positive evidence: non-generated source/docs/test edits, not link churn."""
    for f in detail.get('files', []):
        name = f['filename'].lower()
        if any(x in name for x in ('lock', 'changelog', 'generated', 'vendor/', 'dist/')):
            continue
        if PurePosixPath(name).suffix not in {'.py','.js','.ts','.tsx','.jsx','.mjs','.go','.rs','.sh','.md','.yaml','.yml','.json','.toml'}:
            continue
        for line in f.get('patch', '').splitlines():
            if not line.startswith(('+','-')) or line.startswith(('+++','---')):
                continue
            text = line[1:].strip()
            if len(text) >= 8 and not re.search(r'https?://|utm_|badge|shields.io', text, re.I):
                return True
    return False


def pages(api, path, limit, size, cutoff=None, date_key='created_at'):
    items = {}
    for page in range(1, limit+1):
        batch, headers = api.request('GET', path + ('&' if '?' in path else '?') +
                                     urlencode(dict(page=page, per_page=size)))
        if not isinstance(batch, list):
            raise ValueError('Expected paginated list')
        for x in batch:
            items[x.get('id', x.get('sha'))] = x
        link = {k.lower():v for k,v in headers.items()}.get('link')
        terminal = ('rel="next"' not in link) if link is not None else len(batch) < size
        if terminal or (cutoff and any(x.get(date_key) and timestamp(x[date_key]) < cutoff for x in batch)):
            return dict(items=list(items.values()), complete=True)
    return dict(items=list(items.values()), complete=False, unknown_reason='Pagination/sample budget exhausted')


def build_profile(raw, policy):
    """Pure snapshot transform. Incomplete coverage never becomes a zero or exact rate."""
    raw = deepcopy(raw)
    allowed_meta = {'id','full_name','stargazers_count','forks_count','created_at','archived','disabled','default_branch','updated_at','pushed_at','topics','description'}
    raw['repository'] = {k:v for k,v in raw.get('repository',{}).items() if k in allowed_meta}
    at, meta = raw['observed_at'], raw.get('repository', {})
    repo = canonical_repo(meta.get('full_name', raw['repo']))
    root = 'https://api.github.com/repos/' + repo
    out = dict(schema_version=PROFILE_VERSION, repo=repo, repository_id=meta.get('id'),
               collected_at=at, revision=raw.get('revision'), fields={}, coverage=raw.get('coverage', {}),
               errors=raw.get('errors', []), documents=raw.get('documents', []), snapshot_hash=digest(raw), raw_snapshot=deepcopy(raw))
    fields = out['fields']
    out['coverage'].update({k:bool(raw.get(k,{}).get('complete')) for k in ('commits','pull_requests','open_prs','responses','releases')})
    out['coverage']['documents'] = bool(raw.get('documents_complete'))
    for key in ('stargazers_count','forks_count','created_at','archived','disabled','default_branch','updated_at','pushed_at','id','topics','description'):
        fields[key] = field(meta.get(key), root, at)
    for key in ('contribution_policy','ai_policy','pr_template','actions_restrictions','auto_close_external',
                'target_users','distribution_entry','user_feedback','product_mention_path'):
        fields[key] = field(None, 'https://github.com/'+repo, at, unknown_reason='Requires scoped evidence review; text presence is not permission')
    for label, names in {'contributing_documents':('contributing',), 'agent_documents':('agents.',),
                         'ai_documents':('ai_policy','ai-policy','ai_usage'), 'pr_templates':('pull_request_template',),
                         'workflow_documents':('.github/workflows/',)}.items():
        found = [d['source_url'] for d in out['documents'] if any(n in d['path'].lower() for n in names)]
        fields[label] = field(found if raw.get('documents_complete') or found else None, root+'/git/trees/'+str(raw.get('revision')), at)
    now = timestamp(at)
    within = lambda date, days: bool(date) and 0 <= (now-timestamp(date)).total_seconds() <= days*86400
    commits = raw.get('commits', {})
    confirmed, unknown = [], False
    for c in commits.get('items', []):
        if not c.get('commit', {}).get('committer', {}).get('date'):
            unknown = True
            continue
        if not within(c.get('commit', {}).get('committer', {}).get('date'), policy['windows']['activity_days']):
            continue
        if (c.get('author') or {}).get('type') == 'Bot' or (c.get('committer') or {}).get('type') == 'Bot':
            continue
        if not human(c.get('author')) or not human(c.get('committer')):
            unknown = True
            continue
        detail = raw.get('commit_details', {}).get(c['sha'])
        if detail is None or not detail.get('complete'):
            unknown = True
            continue
        if substantive(detail):
            confirmed.append(c)
    complete = commits.get('complete', False) and not unknown
    for key, days in [('substantive_commits_30d', policy['windows']['short_days']), ('substantive_commits_90d', policy['windows']['activity_days'])]:
        count = sum(within(c['commit']['committer']['date'], days) for c in confirmed)
        fields[key] = field(count if complete else None, root+'/commits', at, 'medium', 'Incomplete human identity, file patches or commit pagination')
        fields[key]['observed_lower_bound'] = count
        fields[key]['window_days'] = days
    dates = [c['commit']['committer']['date'] for c in confirmed]
    responses = raw.get('responses', {})
    replies = [x for x in responses.get('items', []) if human(x.get('user')) and x.get('author_association') in MAINTAINERS
               and within(x.get('created_at'), policy['windows']['activity_days'])]
    dates += [x['created_at'] for x in replies]
    fields['latest_confirmed_human_activity'] = field(max(dates, key=timestamp) if dates else None, root, at, 'medium', 'No confirmed human activity in bounded observations')
    fields['maintainer_responses'] = field(len(replies) if responses.get('complete') else None, root+'/issues/comments', at, 'medium', 'Response sample is incomplete')
    fields['maintainer_responses']['observed_lower_bound'] = len(replies)
    fields['maintainer_responses']['evidence_urls'] = [x['html_url'] for x in replies]
    releases = raw.get('releases', {})
    eligible = [r for r in releases.get('items', []) if not r.get('draft') and not r.get('prerelease')]
    fields['latest_release'] = field(eligible[0] if eligible else ([] if releases.get('complete') else None), root+'/releases', at)
    prs = raw.get('pull_requests', {})
    cohort = [p for p in prs.get('items', []) if within(p.get('created_at'), policy['windows']['external_pr_days'])]
    sample = [p for p in cohort if external(p) is True]
    ambiguous = sum(external(p) is None for p in cohort)
    cohort_complete = bool(prs.get('complete')) and all(p.get('created_at') and p.get('state') in {'open','closed'} and 'merged_at' in p for p in prs.get('items',[]))
    counts = {k:sum((bool(p.get('merged_at')) if k=='merged' else
                    p.get('state')=='closed' and not p.get('merged_at') if k=='closed' else p.get('state')=='open') for p in sample) for k in ('merged','closed','open')}
    sufficient = cohort_complete and not ambiguous and len(sample) >= policy['external_min_sample']
    stats = dict(sample_size=len(sample), window_days=policy['windows']['external_pr_days'],
                 window_start=(now-timedelta(days=policy['windows']['external_pr_days'])).isoformat(),
                 window_end=at, cohort='PRs created in window; status observed at collection',
                 counts=counts, ambiguous_identity_count=ambiguous, complete=cohort_complete,
                 observed_merge_fraction=counts['merged']/len(sample) if sufficient else None,
                 unknown_reason=None if sufficient else 'Insufficient sample, uncertain external identity or incomplete pagination',
                 evidence_urls=[p['html_url'] for p in sample], interpretation='Observed cohort distribution, never future acceptance probability')
    fields['external_pr_sample'] = field(stats, root+'/pulls', at, 'medium')
    external_numbers={str(p['number']) if 'number' in p else p['html_url'].rsplit('/',1)[-1] for p in sample}
    external_replies=[x for x in replies if (x.get('issue_url') or x.get('pull_request_url') or '').rsplit('/',1)[-1] in external_numbers]
    fields['external_pr_responses']=field(len(external_replies) if responses.get('complete') and cohort_complete and not ambiguous else None, root+'/issues/comments',at,'medium','Incomplete response/PR identity coverage')
    fields['external_pr_responses']['observed_lower_bound']=len(external_replies)
    backlog = raw.get('open_prs', {})
    backlog_complete=backlog.get('complete') and all(p.get('created_at') for p in backlog.get('items',[]))
    for key, value in [('active_prs',len(backlog.get('items', []))), ('long_backlog_prs',sum(not within(p.get('created_at'),policy['windows']['backlog_days']) for p in backlog.get('items', [])))]:
        fields[key] = field(value if backlog_complete else None, root+'/pulls?state=open', at)
        fields[key]['observed_lower_bound'] = value
    review=raw.get('policy_review',{})
    if review.get('revision')==out['revision']:
        mapping={'contribution_policy':'accepts_external_pr','ai_policy':'ai_allowed','actions_restrictions':'actions_restrictions','auto_close_external':'auto_close_external','target_users':'target_users','distribution_entry':'distribution_entry','user_feedback':'user_feedback','product_mention_path':'direct_exposure_path'}
        for target,source in mapping.items():
            if source in review.get('facts',{}):fields[target]=deepcopy(review['facts'][source])
    return out


def persist(db, value, source, run_id, at):
    """Append immutable source observations; never mutate opportunity/approval tables."""
    repo, rid = value['repo'], value.get('repository_id')
    with db:
        db.execute('BEGIN IMMEDIATE')
        if source=='repository_screening':
            for (payload,) in db.execute('SELECT payload FROM source_observations WHERE source=?',(source,)):
                prior=json.loads(payload)['evidence']
                if prior.get('policy_version')==value['policy_version'] and prior.get('policy_hash')!=value['policy_hash']:
                    raise ValueError('Policy content changed without version bump')
        if rid is not None:
            alias=db.execute('SELECT repo_id FROM repo_aliases WHERE alias=?',(canonical_repo(repo),)).fetchone()
            if alias and alias[0]!=str(rid):
                raise ValueError('Repository alias conflicts with verified ID')
            current=db.execute('SELECT repo FROM repo_ids WHERE repo_id=?',(str(rid),)).fetchone()
            # Replaying an old snapshot must not rename a repository backwards.
            # Real rename reconciliation remains the existing repo-identify command.
            if not current or current[0]==canonical_repo(repo):
                state.identify(db, canonical_repo(repo), rid)
        item = dict(source=source, source_id=digest(value), kind='github_repository',
                    url='https://github.com/'+repo, canonical_url='https://github.com/'+repo,
                    repo=repo, repository_id=rid, title=source, observed_at=at, updated_at=at,
                    access='public', provenance={'source_url':'https://github.com/'+repo,'run_id':run_id}, evidence=value)
        state.observe(db,item)


def cached_profile(db, repo, policy, at):
    repo = state.resolve(db, canonical_repo(repo))
    rid = db.execute('SELECT repo_id FROM repo_ids WHERE repo=?',(repo,)).fetchone()
    if not rid:
        return None
    rows = db.execute('SELECT payload FROM source_observations WHERE source=? AND entity_key=? ORDER BY recorded_at DESC',
                      ('repository_intelligence', 'github:'+rid[0]+':repository'))
    for (payload,) in rows:
        value = json.loads(payload)['evidence']
        age = (timestamp(at)-timestamp(value['collected_at'])).total_seconds()
        if (0 <= age <= policy['cache_ttl_hours']*3600 and not value['errors'] and
            value.get('collection_policy_hash') == digest(policy)):
            return value
    return None


def collect_profile(api, repo, policy, at, review=None, checkpoint=None, deep=True):
    """Metadata first, then documents, then bounded statistics; GET is the only method."""
    repo = canonical_repo(repo)
    root = '/repos/'+repo
    raw = dict(repo=repo, observed_at=at, errors=[])
    def snapshot():
        p = build_profile(raw,policy)
        p['collection_policy_hash'] = digest(policy)
        if checkpoint: checkpoint(p)
        return p
    try:
        raw['repository'] = api.get(root)
        snapshot()
        if raw['repository'].get('archived') or raw['repository'].get('disabled'):
            return snapshot()
        raw['revision'] = api.get(root+'/commits/'+quote(raw['repository']['default_branch'],safe=''))['sha']
        raw['policy_review'] = deepcopy(review or {})
        facts=(review or {}).get('facts',{})
        if (review or {}).get('revision')==raw['revision'] and any(fresh(facts.get(k),at,policy['evidence_max_age_days']) and facts[k]['value'] is False for k in ('accepts_external_pr','ai_allowed','no_duplicate','scope_fit','not_already_fixed')):
            return snapshot()
        tree = api.get(root+'/git/trees/'+raw['revision']+'?recursive=1')
        docs = [d for d in tree['tree'] if d['type']=='blob' and (PurePosixPath(d['path']).name.lower().startswith(
            ('readme','contributing','agents.','ai.','ai_','ai-','pull_request_template')) or d['path'].lower().startswith(('.github/workflows/','.github/pull_request_template/')) or d['path'].lower() in {'.github/config.yml','.github/stale.yml'})]
        raw['documents'] = []
        raw['documents_complete'] = not tree.get('truncated') and len(docs)<=policy['limits']['documents']
        for d in docs[:policy['limits']['documents']]:
            blob = api.get(root+'/git/blobs/'+d['sha'])
            if blob.get('encoding')!='base64':raise ValueError('Unknown document encoding')
            raw['documents'].append(dict(path=d['path'],sha=d['sha'],text=base64.b64decode(blob['content']).decode('utf8'),
                source_url='https://github.com/'+repo+'/blob/'+raw['revision']+'/'+d['path']))
        raw['policy_review'] = deepcopy(review or {})
        snapshot()
        # No unreviewed prose is interpreted as policy approval. Unknown policy stops expensive work.
        facts = (review or {}).get('facts', {})
        if (not deep or (review or {}).get('revision') != raw['revision'] or
            any(not fresh(facts.get(k),at,policy['evidence_max_age_days']) or facts[k]['value'] is not True
                for k in ('accepts_external_pr','ai_allowed','prerequisites_met'))):
            return snapshot()
        now, limits = timestamp(at), policy['limits']
        raw['pull_requests'] = pages(api,root+'/pulls?state=all&sort=created&direction=desc',limits['max_pages'],limits['page_size'],now-timedelta(days=policy['windows']['external_pr_days']))
        raw['open_prs'] = pages(api,root+'/pulls?state=open&sort=created&direction=desc',limits['max_pages'],limits['page_size'])
        raw['commits'] = pages(api,root+'/commits?'+urlencode({'sha':raw['revision'],'since':(now-timedelta(days=policy['windows']['activity_days'])).isoformat(),'until':at}),limits['max_pages'],limits['page_size'])
        raw['commit_details'] = {}
        for c in [c for c in raw['commits']['items'] if human(c.get('author')) and human(c.get('committer'))][:limits['commit_details']]:
            d,h = api.request('GET',root+'/commits/'+c['sha']+'?per_page=100')
            d['complete'] = 'rel="next"' not in h.get('link','') and all('patch' in f for f in d.get('files',[]))
            raw['commit_details'][c['sha']] = d
        raw['responses'] = pages(api,root+'/issues/comments?'+urlencode({'sort':'created','direction':'desc','since':(now-timedelta(days=policy['windows']['activity_days'])).isoformat()}),limits['response_pages'],limits['page_size'])
        review_replies=pages(api,root+'/pulls/comments?'+urlencode({'sort':'created','direction':'desc','since':(now-timedelta(days=policy['windows']['activity_days'])).isoformat()}),limits['response_pages'],limits['page_size'])
        raw['responses']['items']+=review_replies['items']
        raw['responses']['complete'] &= review_replies['complete']
        raw['releases'] = pages(api,root+'/releases',1,limits['page_size'])
    except (ValueError,OSError,KeyError,TypeError) as exc:
        raw['errors'].append(str(exc))
    return snapshot()
