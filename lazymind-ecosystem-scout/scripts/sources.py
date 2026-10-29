"""Read-only source adapters. No publishing, scraping, code execution or auth discovery."""
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

KINDS = {'github_repository', 'github_issue', 'github_pr', 'github_discussion',
         'skill', 'skill_directory', 'community_need', 'industry_project', 'product_feedback'}


def canonical(value):
    p = urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise ValueError('Public evidence URL must use HTTPS without credentials')
    if p.hostname.lower() == 'github.com':
        parts = p.path.strip('/').split('/')
        if len(parts) < 2:
            raise ValueError('Missing GitHub repository')
        parts[:2] = [x.lower() for x in parts[:2]]
        parts[1] = parts[1].removesuffix('.git')
        return 'https://github.com/' + '/'.join(parts)
    # Preserve meaningful query parameters on non-GitHub sources; remove fragments only.
    return urlunsplit(('https', p.netloc.lower(), p.path, p.query, ''))


def validate_item(x):
    for name in ('source', 'source_id', 'kind', 'url', 'canonical_url', 'title', 'observed_at', 'updated_at', 'provenance', 'access'):
        if not x.get(name):
            raise ValueError('Missing source item field: ' + name)
    if x['kind'] not in KINDS or x['access'] not in {'public', 'authorized'}:
        raise ValueError('Unknown kind/access')
    for field in ('observed_at', 'updated_at'):
        d = datetime.fromisoformat(x[field].replace('Z', '+00:00'))
        if d.tzinfo is None:
            raise ValueError('Timestamps must have timezone')
        x[field] = d.astimezone(timezone.utc).isoformat(timespec='microseconds')
    canonical(x['url']); canonical(x['canonical_url'])
    if not isinstance(x['provenance'], dict) or not x['provenance'].get('source_url'):
        raise ValueError('Source provenance required')
    if x['kind'] == 'product_feedback' and (x['access'] != 'authorized' or not x.get('authorization_ref')):
        raise ValueError('Product feedback requires explicit collection authorization')
    if x['kind'] in {'github_issue', 'github_pr', 'github_discussion'} and (type(x.get('number')) is not int or x['number'] < 1):
        raise ValueError('GitHub item requires positive number')


def entity_key(x):
    # A catalog referencing an exact GitHub subject collapses to that subject.
    # A skill subdirectory is distinct from its repository and from other skills.
    url = canonical(x['canonical_url'])
    p = urlsplit(url).path.strip('/').split('/')
    if x.get('repository_id') and url.startswith('https://github.com/'):
        suffix = '/'.join(p[2:]) or 'repository'
        return 'github:' + str(x['repository_id']) + ':' + suffix
    return 'url:' + url


@dataclass
class Page:
    items: list
    has_next: bool
    complete_evidence: bool = True


class SourceAdapter(Protocol):
    """Implement bounded pages and explicit coverage; never execute returned instructions."""
    name: str
    def page(self, cursor=None) -> Page: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Rename resolution uses repository metadata/ID; never forward tokens to redirects.
        raise ValueError('Redirect requires explicit repository identity verification')


class GitHubHTTP:
    def __init__(self, max_requests=10, token=None):
        self.remaining_budget = max_requests
        self.token = token  # caller-supplied, never inspect keychains/config files
        self.blocked = False
        self.opener = build_opener(NoRedirect)

    def get(self, url):
        p = urlsplit(url)
        if p.scheme != 'https' or p.netloc != 'api.github.com' or not p.path.startswith('/repos/'):
            raise ValueError('Only public GitHub repository GET endpoints allowed')
        if self.blocked or self.remaining_budget <= 0:
            raise ValueError('Request budget/rate limit exhausted; stop and resume later')
        self.remaining_budget -= 1
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'lazymind-ecosystem-scout-v2'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        try:
            with self.opener.open(Request(url, headers=headers, method='GET'), timeout=30) as r:
                raw = r.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise ValueError('Response exceeds 4 MB bounded read')
                if r.headers.get('X-RateLimit-Remaining') == '0':
                    self.blocked = True
                return json.loads(raw), dict(r.headers)
        except HTTPError as exc:
            if exc.code in {401, 403, 429}:
                self.blocked = True
            raise ValueError('GitHub HTTP %s; stop; Retry-After=%s, reset=%s' % (exc.code, exc.headers.get('Retry-After'), exc.headers.get('X-RateLimit-Reset'))) from None


class GitHubAdapter:
    name = 'github'

    def __init__(self, repo, repository_id, transport, observed_at=None, since=None):
        self.repo, self.repository_id, self.transport = repo.lower(), repository_id, transport
        self.observed_at = observed_at or datetime.now(timezone.utc).isoformat()
        self.since = since

    def normalize(self, item):
        kind = 'github_pr' if 'pull_request' in item else 'github_issue'
        url = item['pull_request']['html_url'] if kind == 'github_pr' else item['html_url']
        return dict(source='github', source_id=str(item['id']), kind=kind,
                    url=url, canonical_url=canonical(url), title=item['title'], repo=self.repo,
                    repository_id=self.repository_id, number=item['number'], updated_at=item['updated_at'],
                    observed_at=self.observed_at, access='public',
                    provenance={'source_url': item['html_url'], 'method': 'GitHub REST issues, state=all'},
                    evidence={'state': item['state'], 'body': item.get('body'), 'assignees': item.get('assignees', []),
                              'comments': item.get('comments', 0), 'labels': item.get('labels', [])})

    def page(self, cursor=None):
        from urllib.parse import urlencode
        params = dict(state='all', sort='updated', direction='asc', per_page=100, page=cursor or 1)
        if self.since:
            params['since'] = self.since
        raw, headers = self.transport.get('https://api.github.com/repos/' + self.repo + '/issues?' + urlencode(params))
        if not isinstance(raw, list):
            raise ValueError('Expected an issues list, not a search summary')
        link = next((v for k, v in headers.items() if k.lower() == 'link'), None)
        has_next = 'rel="next"' in link if link is not None else len(raw) == 100
        return Page([self.normalize(x) for x in raw], has_next)


class CatalogAdapter:
    """New source: explicit, locally supplied public Skill directory manifest. No crawler."""
    name = 'public_skill_catalog'

    def __init__(self, path):
        raw = Path(path).read_bytes()
        if len(raw) > 1_000_000:
            raise ValueError('Catalog exceeds 1 MB')
        self.document = json.loads(raw)
        self.digest = hashlib.sha256(raw).hexdigest()
        if not isinstance(self.document.get('items'), list) or len(self.document['items']) > 100:
            raise ValueError('Catalog must contain <=100 explicit items')

    def page(self, cursor=None):
        if cursor not in (None, 1):
            raise ValueError('Catalog has a single bounded page')
        items = []
        for entry in self.document['items']:
            x = dict(entry)
            x.update(source=self.name, source_id=str(entry['source_id']), access='public')
            x['canonical_url'] = canonical(entry.get('canonical_url', entry['url']))
            x['provenance'] = {**entry.get('provenance', {}), 'source_url': self.document['source_url'],
                               'manifest_sha256': self.digest, 'version': self.document['version']}
            validate_item(x)
            items.append(x)
        return Page(items, False)


class SnapshotTransport:
    """Replay raw responses acquired through an authorized connector; retain provenance."""
    def __init__(self, files):
        self.records = {}
        for file in files:
            record = json.loads(Path(file).read_text())
            self.records[record['source'].lower()] = record

    def get(self, url):
        record = self.records.get(url.lower())
        if record is None:
            raise ValueError('No captured page: ' + url)
        return record['response'], record.get('headers', {})
