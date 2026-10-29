"""Scout-owned handoff contract and independent campaign gates (stdlib only)."""
import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import policy
from registry import canonical_repo, canonical_url
from sources import canonical

ROOT = Path(__file__).resolve().parents[2] / 'pipeline'
CAMPAIGN_CHECKS = {
    'resource_listing': ('listing_rules', 'category_fit', 'no_duplicate', 'project_entry'),
    'native_skill_fix': ('real_defect', 'minimal_fix', 'regression_test', 'no_duplicate'),
    'product_integration': ('technical_adaptation', 'integration_validation', 'no_duplicate'),
}


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def timestamp(value):
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None:
        raise ValueError('Timestamp needs timezone')
    return date


def validate_schema(value, schema, path='$'):
    """Validate the intentionally small JSON Schema vocabulary used by our contract.

    This is not a general JSON Schema library. Keep the bundled schema within this
    subset; the test suite also checks it with jsonschema when available.
    """
    types = {'object': dict, 'array': list, 'string': str, 'integer': int,
             'boolean': bool, 'null': type(None)}
    kind = schema.get('type')
    if kind and type(value) not in [types[x] for x in ([kind] if isinstance(kind, str) else kind)]:
        raise ValueError(path + ': invalid type')
    if 'const' in schema and value != schema['const']:
        raise ValueError(path + ': invalid constant')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(path + ': invalid enum')
    if isinstance(value, str):
        if len(value.strip()) < schema.get('minLength', 0):
            raise ValueError(path + ': empty string')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            raise ValueError(path + ': invalid pattern')
        if schema.get('format') == 'date-time':
            timestamp(value)
    if type(value) is int and not schema.get('minimum', value) <= value <= schema.get('maximum', value):
        raise ValueError(path + ': out of range')
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            raise ValueError(path + ': too few items')
        for i, item in enumerate(value):
            validate_schema(item, schema.get('items', {}), path + f'[{i}]')
    if isinstance(value, dict):
        for key in schema.get('required', []):
            if key not in value:
                raise ValueError(path + ': missing ' + key)
        for key, item in value.items():
            child = schema.get('properties', {}).get(key, schema.get('additionalProperties', {}))
            if child is False:
                raise ValueError(path + ': unknown field ' + key)
            validate_schema(item, child if isinstance(child, dict) else {}, path + '.' + key)


def safe_path(path):
    p = PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts or not p.parts or '.git' in p.parts or '\\' in path or path.startswith('-'):
        raise ValueError('Expected repository-relative file path: ' + path)
    return path


def normalize(raw):
    spec = deepcopy(raw)
    validate_schema(spec, json.loads((ROOT / 'schemas/opportunity.schema.json').read_text()))
    repo = spec['source_repo']
    repo['full_name'] = canonical_repo(repo['full_name'])
    if not re.fullmatch(r'[a-z0-9_.-]+/[a-z0-9_.-]+', repo['full_name']):
        raise ValueError('Invalid GitHub repository name')
    if repo['base_branch'].startswith('-') or any(c in repo['base_branch'] for c in ' ~^:?*[\\'):
        raise ValueError('Invalid base branch')
    if spec['target_issue']:
        url = canonical_url(spec['target_issue'])
        if not url.startswith('https://github.com/' + repo['full_name'] + '/issues/'):
            raise ValueError('target_issue must be an issue in source_repo, never a PR')
        number = int(url.rsplit('/', 1)[1])
        if number < 1:
            raise ValueError('Issue number must be positive')
        spec['target_issue'] = url.rsplit('/', 1)[0] + '/' + str(number)
    spec['subject'] = canonical(spec['subject'])
    if spec.get('existing_pr'):
        url = canonical_url(spec['existing_pr'])
        if not url.startswith('https://github.com/' + repo['full_name'] + '/pull/'):
            raise ValueError('existing_pr belongs to another repository or is not a PR')
        number = int(url.rsplit('/', 1)[1])
        if number < 1:
            raise ValueError('PR number must be positive')
        spec['existing_pr'] = url.rsplit('/', 1)[0] + '/' + str(number)
    # Repository IDs survive rename; title, prose and branch movement do not change identity.
    subject = ('issue:' + spec['target_issue'].rsplit('/', 1)[1]) if spec['target_issue'] else spec['subject']
    identity = [repo['repository_id'], spec['campaign_type'], subject]
    oid = 'opp_' + digest(identity)[:24]
    if spec.get('opportunity_id', oid) != oid:
        raise ValueError('opportunity_id does not match canonical identity')
    spec['opportunity_id'] = oid
    evidence_ids = [e['id'] for e in spec['evidence']]
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ValueError('Duplicate evidence IDs')
    for check in spec['checks'].values():
        if not set(check['evidence_ids']) <= set(evidence_ids):
            raise ValueError('Check refers to missing evidence')
    for file in spec['proposed_change']['files']:
        safe_path(file)
    if spec['campaign_type'] == 'native_skill_fix' and not spec['target_issue']:
        raise ValueError('Native fix needs a concrete issue')
    historical = spec['provenance']['kind'] == 'historical_import'
    if historical != (spec['status'] == 'historical'):
        raise ValueError('Historical provenance must retain historical status')
    if spec.get('outreach_channel'):
        if not set(spec['outreach_channel']['evidence_ids']) <= set(evidence_ids):
            raise ValueError('Channel refers to missing evidence')
    return spec


def gate(spec, now=None):
    now = now or datetime.now(timezone.utc)
    reasons = []
    if spec['provenance']['kind'] == 'historical_import' or spec.get('existing_pr'):
        reasons.append('Existing contribution: track only; never submit again')
    p = spec['contribution_policy']
    if p['verdict'] != 'allowed' or not p['prerequisites_met']:
        reasons.append('Contribution policy or maintainer prerequisites not satisfied')
    evidence = {x['id']: x for x in spec['evidence']}
    for name in CAMPAIGN_CHECKS[spec['campaign_type']]:
        check = spec['checks'].get(name, {})
        if check.get('result') != 'pass':
            reasons.append(name + ': ' + check.get('result', 'missing'))
        elif any(not 0 <= (now - timestamp(evidence[x]['checked_at'])).total_seconds() <= 30 * 86400
                 for x in check['evidence_ids']):
            reasons.append(name + ': evidence needs refresh')
    if spec['campaign_type'] == 'product_integration':
        context = spec.get('capability_context', {})
        ok, reason = policy.assess(context)
        if not ok:
            reasons.append(reason)
        try:
            if policy.axis(context.get('technical_fit'), policy.A_LIMITS) < 8 or context['technical_fit']['capability_match'] < 3:
                reasons.append('Technical fit below existing policy threshold')
        except (ValueError, KeyError, TypeError):
            reasons.append('Missing technical fit evidence')
        if not context.get('score_evidence'):
            reasons.append('Missing score evidence')
    if spec['status'] not in {'ready', 'historical'}:
        reasons.append('Scout status is not ready')
    return {'decision': 'NO-GO' if reasons else 'GO', 'reasons': reasons,
            'campaign_type': spec['campaign_type'], 'next_action': spec['next_action']}


def outreach_candidate(spec, outcome, now=None):
    """No automatic contact inference from a merge, issue author or public email."""
    now = now or datetime.now(timezone.utc)
    channel = spec.get('outreach_channel')
    if not channel or channel['suitable'] is not True or not outcome.get('pr_url'):
        return None
    if not 0 <= (now - timestamp(channel['verified_at'])).total_seconds() <= 30 * 86400:
        return None
    if outcome.get('status') in {'closed', 'changes_requested', 'ci_failed'}:
        return None
    return {'task_id': 'outreach_' + spec['opportunity_id'], 'opportunity_id': spec['opportunity_id'],
            'source_campaign': spec['campaign_type'], 'source_repo': spec['source_repo']['full_name'],
            'channel': channel, 'pr_url': outcome['pr_url'], 'observed_status': outcome['status'],
            'historical_contribution': spec['provenance']['kind'] == 'historical_import',
            'expected_user_value': spec['expected_user_value'], 'evidence': spec['evidence'],
            'status': 'candidate_review', 'send_authorized': False,
            'next_action': 'Review purpose, channel and exact draft in Outreach Agent; obtain send approval'}
