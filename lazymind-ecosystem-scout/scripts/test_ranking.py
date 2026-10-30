"""Discovery ranking boundaries; fixtures are not live acceptance evidence."""
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from ranking import WEIGHTS, collect, rank, recent_pages

NOW = datetime.now(timezone.utc)


def candidate(kind='resource_listing'):
    return dict(key='owner/repo#7', campaign_type=kind,
                quick_checks={k: 'pass' for k in ('policy', 'no_duplicate', 'category', 'test_plan')},
                metrics=dict(checked_at=NOW.isoformat(), archived=False, stars=0, forks=0,
                             external_merged_60d=10, external_closed_unmerged_60d=2,
                             closed_unmerged_60d=3, open_prs=1, human_commits_30d=10,
                             human_commits_60d=20, code_commits_30d=10, code_commits_60d=20,
                             coverage=dict(prs_complete=True, commits_complete=True, code_complete=True)),
                ratings=dict(audience=4, defect_tests=5, estimated_minutes=15),
                rating_evidence=['Reviewed issue and regression plan'])


class RankingTests(unittest.TestCase):
    def test_requested_weights_and_no_minimum_stars(self):
        self.assertEqual(list(WEIGHTS['resource_listing'].values()), [25, 25, 20, 20, 10])
        self.assertEqual(list(WEIGHTS['native_skill_fix'].values()), [35, 25, 20, 10, 10])
        for kind in ('resource_listing', 'native_skill_fix'):
            result = rank(candidate(kind), NOW)
            self.assertEqual(result['status'], 'ranked_for_review')
            self.assertEqual(result['points']['reach'], 0)
            self.assertFalse(result['publication_authorized'])
            self.assertEqual(sum(result['weights'].values()), 100)

    def test_popularity_cannot_override_quick_checks(self):
        for field in ('policy', 'no_duplicate', 'category', 'test_plan'):
            c = candidate(); c['metrics']['stars'] = 10**9
            c['quick_checks'][field] = 'fail'
            self.assertEqual(rank(c, NOW)['status'], 'screened_out')
            c['quick_checks'][field] = 'unknown'
            self.assertIsNone(rank(c, NOW)['score'])

    def test_existing_gate_and_product_capabilities_still_required(self):
        from test_pipeline import candidate as spec
        from test_v2 import candidate as capabilities
        c = candidate('product_integration')
        self.assertEqual(rank(c, NOW)['status'], 'technical_gate_blocked')
        c['spec'] = spec('product_integration')
        self.assertIsNone(rank(c)['score'])
        c['spec']['capability_context'] = capabilities()
        self.assertEqual(rank(c)['status'], 'ranked_for_review')
        self.assertEqual(rank(c)['priority_key'][0], 8)
        c['spec']['capability_context']['technical_fit']['capability_match'] = 1
        c['metrics']['stars'] = 10**9
        self.assertEqual(rank(c)['status'], 'technical_gate_blocked')
        c = candidate(); c['spec'] = spec('resource_listing')
        c['spec']['contribution_policy']['prerequisites_met'] = False
        self.assertEqual(rank(c)['status'], 'execution_gate_blocked')

    def test_spec_campaign_cannot_be_relabelled(self):
        from test_pipeline import candidate as spec
        c = candidate('product_integration'); c['spec'] = spec('resource_listing')
        with self.assertRaises(ValueError): rank(c)

    def test_missing_partial_stale_and_future_not_zero(self):
        for field in candidate()['metrics']:
            if field in ('coverage', 'archived'): continue
            c = candidate(); c['metrics'][field] = None
            if field.startswith('code_'): continue  # listing activity is documentation-aware
            self.assertIsNone(rank(c, NOW)['score'], field)
        for days in (-1, 8):
            c = candidate(); c['metrics']['checked_at'] = (NOW-timedelta(days=days)).isoformat()
            self.assertIsNone(rank(c, NOW)['score'])
        for field in ('prs_complete', 'commits_complete', 'code_complete'):
            c = candidate('native_skill_fix'); c['metrics']['coverage'][field] = False
            self.assertIsNone(rank(c, NOW)['score'])

    def test_backlog_rejections_and_cost_reduce_rank(self):
        c = candidate(); original = rank(c, NOW)['score']
        for field in ('open_prs', 'external_closed_unmerged_60d'):
            x = deepcopy(c); x['metrics'][field] = 100
            x['metrics']['closed_unmerged_60d'] = 100
            self.assertLess(rank(x, NOW)['score'], original)
        c['ratings']['estimated_minutes'] = 45
        self.assertEqual(rank(c, NOW)['points']['cost'], 0)
        c['metrics']['external_merged_60d'] = 0
        self.assertEqual(rank(c, NOW)['status'], 'ranked_for_review')

    def test_invalid_numbers_and_inconsistent_counts(self):
        for value in (-1, True, float('nan'), float('inf')):
            c = candidate(); c['metrics']['stars'] = value
            with self.assertRaises(ValueError): rank(c, NOW)
        c = candidate(); c['metrics']['code_commits_30d'] = 100  # only relevant for native
        c['campaign_type'] = 'native_skill_fix'
        with self.assertRaises(ValueError): rank(c, NOW)
        c = candidate(); c['ratings']['audience'] = 6
        with self.assertRaises(ValueError): rank(c, NOW)
        c = candidate(); c['rating_evidence'] = []
        self.assertIsNone(rank(c, NOW)['score'])


class PaginationTests(unittest.TestCase):
    def test_bounded_pages_deduplicate_and_do_not_claim_complete(self):
        class API:
            def request(self, *args, **kwargs):
                return [{'id': 1, 'updated_at': NOW.isoformat()}], {'link': '<next>; rel="next"'}
        values, complete = recent_pages(API(), '/repos/x/y/pulls', max_pages=2)
        self.assertEqual(len(values), 1)
        self.assertFalse(complete)
        _, complete = recent_pages(API(), '/repos/x/y/pulls', NOW+timedelta(days=1), max_pages=2)
        self.assertTrue(complete)

    def test_terminal_full_page_is_complete_with_link_header(self):
        class API:
            def request(self, *args, **kwargs):
                return [{'id': i} for i in range(100)], {'link': '<previous>; rel="prev"'}
        self.assertTrue(recent_pages(API(), '/repos/x/y/pulls', max_pages=1)[1])


class CollectionTests(unittest.TestCase):
    def api(self, paginated_files=False):
        stamp = lambda days: (NOW-timedelta(days=days)).isoformat()
        def pr(i, days, merged=True, association='NONE', user_type='User'):
            return dict(id=i, html_url='https://github.com/o/r/pull/'+str(i), updated_at=stamp(0),
                        closed_at=stamp(days), merged_at=stamp(days) if merged else None,
                        author_association=association, user=dict(type=user_type))
        def commit(sha, days, bot=False, merge=False):
            return dict(sha=sha, author=dict(type='Bot' if bot else 'User'),
                        commit=dict(author=dict(name='person'), committer=dict(date=stamp(days))),
                        parents=[{}, {}] if merge else [{}])
        class API:
            def get(self, path, fresh=False):
                return dict(full_name='o/r', id=1, default_branch='main', archived=False,
                            stargazers_count=5, forks_count=2)
            def request(self, method, path, fresh=False):
                if '/pulls?state=closed' in path:
                    return [pr(1, 2), pr(2, 70), pr(3, 2, association='MEMBER'),
                            pr(4, 2, user_type='Bot'), pr(5, 2, merged=False),
                            pr(6, 70, merged=False)], {}
                if '/pulls?state=open' in path: return [pr(7, 0)], {}
                if '/commits?' in path:
                    return [commit('code', 2), commit('docs', 45), commit('bot', 1, bot=True),
                            commit('merge', 1, merge=True)], {}
                files = [{'filename': 'main.py' if '/code?' in path else 'README.md'}]
                return {'files': files}, {'link': '<next>; rel="next"'} if paginated_files else {}
        return API()

    def test_event_dates_external_authors_and_code_activity(self):
        m = collect(self.api(), 'o/r', now=NOW, max_code_commits=10)
        self.assertEqual(m['external_merged_60d'], 1)
        self.assertEqual(m['closed_unmerged_60d'], 1)
        self.assertEqual(m['external_closed_unmerged_60d'], 1)
        self.assertEqual(m['open_prs'], 1)
        self.assertEqual((m['human_commits_30d'], m['human_commits_60d']), (1, 2))
        self.assertEqual((m['code_commits_30d'], m['code_commits_60d']), (1, 1))
        self.assertTrue(m['coverage']['code_complete'])

    def test_positive_code_match_needs_no_remaining_file_pages(self):
        api = self.api(True)
        original = api.request
        def request(method, path, fresh=False):
            data, headers = original(method, path, fresh=fresh)
            if '/docs?' in path: headers = {}
            return data, headers
        api.request = request
        self.assertTrue(collect(api, 'o/r', now=NOW, max_code_commits=10)['coverage']['code_complete'])

    def test_detail_cap_and_truncated_files_are_partial(self):
        self.assertFalse(collect(self.api(), 'o/r', now=NOW)['coverage']['code_complete'])
        m = collect(self.api(True), 'o/r', now=NOW, max_code_commits=10)
        self.assertFalse(m['coverage']['code_complete'])
        self.assertEqual(m['code_commits_60d'], 1)


if __name__ == '__main__':
    unittest.main()
