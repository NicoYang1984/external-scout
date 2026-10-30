"""Read-only, campaign-specific discovery ranking; never grants a Pipeline GO."""
import argparse
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from opportunity import gate, timestamp
from registry import canonical_repo

WEIGHTS = {
    'resource_listing': dict(audience=25, acceptance=25, activity=20, reach=20, cost=10),
    'native_skill_fix': dict(defect_tests=35, acceptance=25, activity=20, reach=10, cost=10),
    'product_integration': dict(audience=25, acceptance=25, activity=20, reach=20, cost=10),
}
BUDGETS = dict(resource_listing=45, native_skill_fix=90, product_integration=180)
CODE_SUFFIXES = {'.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.go', '.rs',
                 '.java', '.c', '.cpp', '.h', '.cs', '.rb', '.sh', '.bash', '.ps1'}


def recent_pages(api, path, cutoff=None, max_pages=3):
    """Read updated-desc PRs or since-filtered commits; capped samples stay partial."""
    result = {}
    for page in range(1, max_pages + 1):
        batch, headers = api.request('GET', path + ('&' if '?' in path else '?') +
                                     urlencode(dict(per_page=100, page=page)), fresh=True)
        for item in batch:
            result[item.get('id', item.get('sha'))] = item
        if cutoff and any(timestamp(p['updated_at']) < cutoff for p in batch):
            return list(result.values()), True
        if 'rel="next"' not in headers.get('link', '') and len(batch) < 100:
            return list(result.values()), True
        if 'link' in headers and 'rel="next"' not in headers['link']:
            return list(result.values()), True
    return list(result.values()), False


def external(pr):
    return (pr['user']['type'] != 'Bot' and pr['author_association'] not in
            {'OWNER', 'MEMBER', 'COLLABORATOR'})


def human_commit(commit):
    author = commit.get('author') or {}
    return (author.get('type') != 'Bot' and
            '[bot]' not in commit['commit']['author'].get('name', '').lower() and
            len(commit.get('parents', [])) < 2)


def collect(api, repo, now=None, max_pages=3, max_code_commits=0):
    now = now or datetime.now(timezone.utc)
    root = '/repos/' + canonical_repo(repo)
    meta = api.get(root, fresh=True)
    cutoff = now - timedelta(days=60)
    closed, closed_ok = recent_pages(api, root + '/pulls?state=closed&sort=updated&direction=desc', cutoff, max_pages)
    opened, open_ok = recent_pages(api, root + '/pulls?state=open&sort=updated&direction=desc', max_pages=max_pages)
    commits, commits_ok = recent_pages(api, root + '/commits?' + urlencode({
        'sha': meta['default_branch'], 'since': cutoff.isoformat(), 'until': now.isoformat()}), max_pages=max_pages)
    in_window = lambda value, days: bool(value) and now - timedelta(days=days) <= timestamp(value) <= now
    merged = [p for p in closed if in_window(p.get('merged_at'), 60)]
    rejected = [p for p in closed if not p.get('merged_at') and in_window(p.get('closed_at'), 60)]
    commits = [c for c in commits if human_commit(c) and in_window(c['commit']['committer']['date'], 60)]
    code, files_ok = [], True
    for commit in commits[:max_code_commits]:
        detail, headers = api.request('GET', root + '/commits/' + commit['sha'] + '?per_page=100', fresh=True)
        has_code = any(Path(f['filename']).suffix.lower() in CODE_SUFFIXES or
                       f['filename'].startswith('.github/workflows/') for f in detail.get('files', []))
        # One matching file proves this commit changed code; a negative needs all files.
        files_ok &= isinstance(detail.get('files'), list) and (has_code or 'rel="next"' not in headers.get('link', ''))
        if has_code:
            code.append(commit)
    count = lambda items, days: sum(in_window(c['commit']['committer']['date'], days) for c in items)
    return dict(repo=meta['full_name'], repository_id=meta['id'], checked_at=now.isoformat(),
                window_start=cutoff.isoformat(), archived=meta['archived'], stars=meta['stargazers_count'],
                forks=meta['forks_count'], external_merged_60d=sum(external(p) for p in merged),
                closed_unmerged_60d=len(rejected), external_closed_unmerged_60d=sum(external(p) for p in rejected),
                open_prs=len(opened), human_commits_30d=count(commits, 30), human_commits_60d=count(commits, 60),
                code_commits_30d=count(code, 30), code_commits_60d=count(code, 60),
                coverage=dict(prs_complete=closed_ok and open_ok, commits_complete=commits_ok,
                              code_complete=commits_ok and files_ok and len(commits) <= max_code_commits),
                sources=[root, root + '/pulls', root + '/commits'],
                evidence=dict(merged=[p['html_url'] for p in merged if external(p)],
                              closed_unmerged=[p['html_url'] for p in rejected],
                              open_prs=[p['html_url'] for p in opened],
                              human_commits=[c['sha'] for c in commits], code_commits=[c['sha'] for c in code]))


def number(value, key, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        raise ValueError('Invalid ranking value: ' + key)
    return value


def rank(candidate, now=None):
    now = now or datetime.now(timezone.utc)
    kind = candidate['campaign_type']
    weights = WEIGHTS[kind]
    result = dict(key=candidate['key'], campaign_type=kind, score=None, weights=weights,
                  status='needs_evidence', publication_authorized=False)
    checks = candidate.get('quick_checks', {})
    required = ['policy', 'no_duplicate', 'category', 'test_plan']
    if any(checks.get(k) == 'fail' for k in required):
        return dict(result, status='screened_out', reason='Failed quick check; popularity cannot override it')
    if any(checks.get(k) != 'pass' for k in required):
        return dict(result, reason='Quick policy/duplicate/category/test-plan review incomplete')
    spec = candidate.get('spec')
    if spec:
        if spec.get('campaign_type') != kind:
            raise ValueError('Ranking campaign must match OpportunitySpec')
        result['execution_gate'] = gate(spec, now)
        if result['execution_gate']['decision'] != 'GO':
            return dict(result, status='technical_gate_blocked' if kind == 'product_integration' else 'execution_gate_blocked')
    elif kind == 'product_integration':
        return dict(result, status='technical_gate_blocked', reason='Existing verified capability gate required before reach ranking')
    m = candidate.get('metrics', {})
    if not m.get('checked_at') or not 0 <= (now - timestamp(m['checked_at'])).total_seconds() <= 7 * 86400:
        return dict(result, reason='Ranking metrics missing, future-dated or older than seven days')
    if m.get('archived'):
        return dict(result, status='screened_out', reason='Archived repository')
    fields = ['stars', 'forks', 'external_merged_60d', 'external_closed_unmerged_60d', 'closed_unmerged_60d', 'open_prs']
    activity = 'human' if kind == 'resource_listing' else 'code'
    fields += [activity + '_commits_30d', activity + '_commits_60d']
    coverage = m.get('coverage', {})
    if (any(m.get(k) is None for k in fields) or not coverage.get('prs_complete') or
        not coverage.get('commits_complete') or (activity == 'code' and not coverage.get('code_complete'))):
        return dict(result, reason='Partial window or missing metrics; counts are lower bounds, not zeros')
    for field in fields:
        number(m[field], field)
    if m['external_closed_unmerged_60d'] > m['closed_unmerged_60d'] or m[activity+'_commits_30d'] > m[activity+'_commits_60d']:
        raise ValueError('Inconsistent time-window counts')
    ratings = candidate.get('ratings', {})
    rating_key = 'defect_tests' if kind == 'native_skill_fix' else 'audience'
    if not candidate.get('rating_evidence') or ratings.get(rating_key) is None or ratings.get('estimated_minutes') is None:
        return dict(result, reason='Evidence-backed fit/feasibility and cost estimate required')
    fit = number(ratings[rating_key], rating_key, 5) / 5
    minutes = number(ratings['estimated_minutes'], 'estimated_minutes')
    if minutes <= 0:
        raise ValueError('Estimated cost must be positive')
    merged, declined, backlog = m['external_merged_60d'], m['external_closed_unmerged_60d'], m['open_prs']
    # Smoothed acceptance, volume, and throughput/backlog; consistent external denominator.
    acceptance = (.5 * merged / (merged + declined + 2) + .3 * min(merged / 10, 1) +
                  .2 * (merged + declined) / (merged + declined + backlog + 1))
    reach = (.75 * min(math.log1p(m['stars']) / math.log1p(10000), 1) +
             .25 * min(math.log1p(m['forks']) / math.log1p(1000), 1))
    activity_score = (.5 * min(m[activity + '_commits_30d'] / 10, 1) +
                      .5 * min(m[activity + '_commits_60d'] / 20, 1))
    fractions = dict(acceptance=acceptance, reach=reach, activity=activity_score,
                     cost=max(0, 1 - minutes / BUDGETS[kind]), **{rating_key: fit})
    points = {k: round(weights[k] * fractions[k], 2) for k in weights}
    score = round(sum(points.values()), 2)
    result.update(status='ranked_for_review', score=score, points=points, priority_key=[score],
                  next_action='Select top candidates for complete dossier; existing Pipeline gates still required')
    if kind == 'product_integration':
        result['priority_key'] = [sum(spec['capability_context']['technical_fit'].values()), score]
    return result


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] in {"profile", "screen"}:
        from screening import main as screen_main
        return screen_main(sys.argv[1:])
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('profile', help='Versioned repository intelligence; see profile --help')
    sub.add_parser('screen', help='Deterministic screening/report/handoff; see screen --help')
    c = sub.add_parser('collect')
    c.add_argument('--repo', required=True)
    c.add_argument('--data-dir', type=Path, required=True)
    c.add_argument('--output', type=Path, required=True)
    c.add_argument('--max-pages', type=int, default=3, choices=range(1, 11))
    c.add_argument('--max-code-commits', type=int, default=0, choices=range(0, 101))
    r = sub.add_parser('rank')
    r.add_argument('--input', type=Path, required=True)
    r.add_argument('--output', type=Path, required=True)
    r.add_argument('--limit', type=int, default=8, choices=range(1, 13))
    args = p.parse_args()
    if args.command == 'collect':
        from pipeline_github import GitHub
        from pipeline_store import Store
        store = Store(args.data_dir)
        try:
            result = collect(GitHub(store.db, os.environ.get('GITHUB_TOKEN'), budget=150),
                             args.repo, max_pages=args.max_pages, max_code_commits=args.max_code_commits)
        finally:
            store.close()
    else:
        candidates = json.loads(args.input.read_text())
        if len({c['key'] for c in candidates}) != len(candidates):
            raise ValueError('Duplicate opportunity key; do not count twice')
        ranked = [rank(c) for c in candidates]
        result = {'rankings': ranked, 'shortlist_by_campaign': {k: [x['key'] for x in sorted(
            (x for x in ranked if x['campaign_type'] == k and x['score'] is not None),
            key=lambda x: x['priority_key'], reverse=True)[:args.limit]] for k in WEIGHTS}}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
