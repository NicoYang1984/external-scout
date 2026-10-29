"""Bounded GitHub REST transport, conditional reads and independent PR outcomes."""
import base64
import json
import re
from urllib.error import HTTPError
from urllib.parse import urlencode, quote
from urllib.request import Request, build_opener

from opportunity import encoded
from sources import NoRedirect


class GitHub:
    def __init__(self, db, token=None, budget=100):
        self.db, self.token, self.remaining = db, token, budget
        self.opener = build_opener(NoRedirect)

    def request(self, method, path, body=None, fresh=False):
        if not path.startswith('/repos/') or '..' in path or '#' in path:
            raise ValueError('Only GitHub repository endpoints allowed')
        if method not in {'GET', 'POST'} or (method == 'POST' and not re.fullmatch(r'/repos/[\w.-]+/[\w.-]+/pulls', path)):
            raise ValueError('Only PR creation is writable')
        if self.remaining <= 0:
            raise ValueError('GitHub request budget exhausted; incomplete coverage')
        if method != 'GET' and not self.token:
            raise ValueError('GITHUB_TOKEN with pull-request write permission required')
        self.remaining -= 1
        url = 'https://api.github.com' + path
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'external-scout-pipeline',
                   'X-GitHub-Api-Version': '2022-11-28'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        cached = self.db.execute('SELECT etag,payload,headers FROM github_cache WHERE url=?', (url,)).fetchone()
        if method == 'GET' and cached and cached[0] and not fresh:
            headers['If-None-Match'] = cached[0]
        data = encoded(body).encode() if body is not None else None
        if data:
            headers['Content-Type'] = 'application/json'
        try:
            with self.opener.open(Request(url, data=data, headers=headers, method=method), timeout=30) as r:
                raw = r.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise ValueError('GitHub response too large; coverage incomplete')
                result = json.loads(raw)
                response_headers = {k.lower(): v for k, v in r.headers.items()}
        except HTTPError as e:
            if e.code == 304 and cached and method == 'GET':
                return json.loads(cached[1]), json.loads(cached[2])
            if e.code in {401, 403, 429}:
                self.remaining = 0
            raise ValueError(f'GitHub HTTP {e.code}; no result inferred; retry after resolving access/rate limit') from None
        if method == 'GET':
            with self.db:
                self.db.execute('INSERT INTO github_cache VALUES (?,?,?,?) ON CONFLICT(url) DO UPDATE SET etag=excluded.etag,payload=excluded.payload,headers=excluded.headers',
                                (url, response_headers.get('etag'), encoded(result), encoded(response_headers)))
        return result, response_headers

    def get(self, path, fresh=False):
        return self.request('GET', path, fresh=fresh)[0]

    def pages(self, path, key=None, max_pages=20):
        result = []
        for page in range(1, max_pages + 1):
            data, headers = self.request('GET', path + ('&' if '?' in path else '?') + urlencode({'per_page': 100, 'page': page}))
            batch = data[key] if key else data
            if not isinstance(batch, list):
                raise ValueError('Expected paginated list')
            result.extend(batch)
            link = headers.get('link')
            has_next = 'rel="next"' in link if link is not None else len(batch) == 100
            if not has_next:
                if key and data.get('total_count', len(result)) > len(result):
                    raise ValueError('Incomplete GitHub pagination')
                return result
        raise ValueError('Pagination limit reached; do not infer complete coverage')

    def create_pr(self, repo, body):
        return self.request('POST', '/repos/' + repo + '/pulls', body)[0]


def latest(items, key):
    values = {}
    for item in sorted(items, key=lambda x: (x.get('id', 0), x.get('run_attempt', 0))):
        values[key(item)] = item
    return list(values.values())


def summarize(pr, checks, runs, statuses, reviews):
    """CI, review and merge remain separate axes; no checks means unknown."""
    checks = latest(checks, lambda x: (x.get('app', {}).get('id'), x['name']))
    runs = latest(runs, lambda x: x.get('workflow_id', x.get('name')))
    statuses = latest(statuses, lambda x: x['context'])
    conclusions = [x.get('conclusion') for x in checks + runs]
    states = [x['state'] for x in statuses]
    if 'action_required' in conclusions or any(x.get('status') in {'waiting', 'requested'} for x in runs):
        ci = 'action_required'
    elif any(x in {'failure', 'timed_out', 'cancelled', 'startup_failure', 'stale'} for x in conclusions) or any(x in {'failure', 'error'} for x in states):
        ci = 'failed'
    elif any(x.get('status') != 'completed' for x in checks + runs) or 'pending' in states:
        ci = 'pending'
    elif 'success' in conclusions + states and all(x in {'success', 'neutral', 'skipped'} for x in conclusions) and all(x == 'success' for x in states):
        ci = 'passed'
    else:
        ci = 'unknown'
    decisive = latest([x for x in reviews if x['state'] in {'APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'}], lambda x: x['user']['login'])
    review = ('changes_requested' if any(x['state'] == 'CHANGES_REQUESTED' for x in decisive)
              else 'approved' if any(x['state'] == 'APPROVED' and x.get('commit_id') == pr['head']['sha'] for x in decisive)
              else 'pending')
    flags = ['submitted']
    if ci in {'action_required', 'failed', 'passed'}:
        flags.append('ci_' + ci)
    if review == 'changes_requested':
        flags.append(review)
    elif review == 'pending':
        flags.append('review_pending')
    if pr.get('merged_at'):
        status = 'merged'
    elif pr['state'] == 'closed':
        status = 'closed'
    elif review == 'changes_requested':
        status = review
    elif ci in {'action_required', 'failed', 'passed'}:
        status = 'ci_' + ci
    else:
        status = 'review_pending' if review == 'pending' else 'submitted'
    if status not in flags:
        flags.append(status)
    return {'pr_url': pr['html_url'], 'number': pr['number'], 'commit': pr['head']['sha'],
            'status': status, 'states': flags, 'ci': ci, 'review': review,
            'merged_at': pr.get('merged_at'), 'merge_commit': pr.get('merge_commit_sha'),
            'closed_at': pr.get('closed_at'), 'updated_at': pr.get('updated_at'),
            'checks': [{'name': x['name'], 'status': x['status'], 'conclusion': x.get('conclusion')} for x in checks],
            'workflow_runs': [{'id': x['id'], 'status': x['status'], 'conclusion': x.get('conclusion')} for x in runs],
            'reviews': [{'id': x['id'], 'state': x['state'], 'commit': x.get('commit_id')} for x in decisive],
            'commit_statuses': [{'context': x['context'], 'state': x['state']} for x in statuses],
            'query_source': 'GitHub REST API', 'required_checks_verified': False}


def track(api, spec, pr_url):
    repo = spec['source_repo']['full_name']
    if not re.fullmatch(r'https://github\.com/' + re.escape(repo) + r'/pull/[1-9][0-9]*', pr_url, re.I):
        raise ValueError('PR URL does not match opportunity repository')
    root = '/repos/' + repo
    path = root + '/pulls/' + pr_url.rsplit('/', 1)[1]
    pr = api.get(path)
    if pr['base']['repo']['id'] != spec['source_repo']['repository_id']:
        raise ValueError('Repository identity changed')
    sha = pr['head']['sha']
    checks = api.pages(root + '/commits/' + sha + '/check-runs', 'check_runs')
    runs = api.pages(root + '/actions/runs?' + urlencode({'head_sha': sha}), 'workflow_runs')
    statuses = api.pages(root + '/commits/' + sha + '/statuses')
    reviews = api.pages(path + '/reviews')
    after = api.get(path, fresh=True)
    if after['head']['sha'] != sha or after.get('updated_at') != pr.get('updated_at'):
        raise ValueError('PR changed during query; retry without overwriting the prior outcome')
    return summarize(pr, checks, runs, statuses, reviews)


def dossier(api, spec):
    """Complete bounded preflight evidence for Codex to review before implementation."""
    repo = spec['source_repo']['full_name']
    root = '/repos/' + repo
    metadata = api.get(root, fresh=True)
    if metadata['id'] != spec['source_repo']['repository_id'] or metadata['archived'] or metadata.get('disabled'):
        raise ValueError('Repository identity/availability gate failed')
    commit = api.get(root + '/commits/' + quote(spec['source_repo']['base_branch'], safe=''), fresh=True)['sha']
    if commit != spec['source_repo']['commit']:
        raise ValueError('Base advanced; Scout must revalidate the pinned spec')
    tree = api.get(root + '/git/trees/' + commit + '?recursive=1')
    if tree.get('truncated'):
        raise ValueError('Policy tree truncated; cannot certify applicable instructions')
    policies = []
    for item in tree['tree']:
        name = item['path'].rsplit('/', 1)[-1].lower()
        if item['type'] == 'blob' and (name.startswith(('contributing', 'agents.', 'ai_policy', 'code_of_conduct', 'pull_request_template')) or name in {'license', 'license.md'} or item['path'].lower() == 'readme.md'):
            blob = api.get(root + '/git/blobs/' + item['sha'])
            if blob.get('encoding') != 'base64':
                raise ValueError('Unsupported policy encoding')
            policies.append({'path': item['path'], 'sha': item['sha'], 'text': base64.b64decode(blob['content']).decode('utf-8')})
    prs = api.pages(root + '/pulls?state=all&sort=updated&direction=desc')
    issue, timeline, comments = None, [], []
    if spec['target_issue']:
        path = root + '/issues/' + spec['target_issue'].rsplit('/', 1)[1]
        issue = api.get(path, fresh=True)
        if issue.get('pull_request') or issue['state'] != 'open':
            raise ValueError('Target issue is not an open issue')
        timeline, comments = api.pages(path + '/timeline'), api.pages(path + '/comments')
    return {'repository': {'id': metadata['id'], 'full_name': metadata['full_name'], 'permissions': metadata.get('permissions', {})},
            'commit': commit, 'policies': policies, 'issue': issue, 'timeline': timeline, 'comments': comments,
            'pull_requests': [{'number': p['number'], 'title': p['title'], 'body': p.get('body'), 'state': p['state'],
                               'head': p['head']['label'], 'sha': p['head']['sha'], 'url': p['html_url'],
                               'updated_at': p['updated_at']} for p in prs], 'coverage_complete': True}


def duplicate_blockers(spec, evidence, own_head=None):
    blockers = []
    issue = spec['target_issue'].rsplit('/', 1)[1] if spec['target_issue'] else None
    for p in evidence['pull_requests']:
        if p['head'] == own_head:
            continue
        text = (p['title'] + '\n' + (p['body'] or '')).casefold()
        same_subject = spec['subject'].casefold() in text
        issue_link = issue and (spec['target_issue'].casefold() in text or re.search(r'(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\s+#' + issue + r'\b', text))
        if same_subject or issue_link:
            blockers.append(p['url'])
    for event in evidence['timeline']:
        source = event.get('source', {}).get('issue', {})
        if source.get('pull_request') and source.get('state') == 'open':
            blockers.append(source['html_url'])
    return sorted(set(blockers))
