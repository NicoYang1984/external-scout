"""Capability gates, independent scores and evidence-backed action outcomes."""
import json
from datetime import datetime, timezone
from pathlib import Path

STATUSES = {'documented', 'implemented', 'unit_tested', 'e2e_verified', 'known_failure', 'unavailable'}
A_LIMITS = {'capability_match': 4, 'integration_cost': 2, 'validation': 2, 'recovery_fit': 2}
B_LIMITS = {'user_value': 4, 'collaboration': 3, 'audience_evidence': 3}
ACTION_DEFAULTS = dict(proposed_action='Read-only validation', validation_status='not_run',
                       public_contribution_url=None, review_status='not_requested', outreach_channel=None,
                       outreach_permission='not_granted', reply_status='not_contacted', trial_status='not_started',
                       conversion_evidence=[], next_follow_up=None)
ACTION_ENUMS = {
    'validation_status': {'not_run', 'planned', 'passed', 'failed', 'blocked'},
    'review_status': {'not_requested', 'pending', 'changes_requested', 'approved', 'merged', 'closed'},
    'outreach_permission': {'not_granted', 'granted', 'revoked'},
    'reply_status': {'not_contacted', 'awaiting', 'replied', 'declined'},
    'trial_status': {'not_started', 'invited', 'started', 'completed', 'failed', 'converted'},
}


def catalog(path=None):
    return json.loads(Path(path or Path(__file__).resolve().parents[1] / 'references/capabilities.json').read_text())


def axis(values, limits):
    if not isinstance(values, dict) or set(values) != set(limits):
        raise ValueError('Score axis must contain exactly ' + ', '.join(limits))
    for key, maximum in limits.items():
        if type(values[key]) is not int or not 0 <= values[key] <= maximum:
            raise ValueError('Score component out of range: ' + key)
    return sum(values.values())


def assess(data, facts=None, now=None):
    facts = facts or catalog()
    ids = data.get('capability_ids', [])
    if not ids:
        return False, 'No scoped capability mapping'
    records = {x['id']: x for x in facts['capabilities']}
    for id_ in ids:
        fact = records.get(id_)
        if not fact or fact['status'] not in {'implemented', 'unit_tested', 'e2e_verified'}:
            return False, 'Capability is absent, documented-only, failed or unavailable: ' + id_
        if not fact.get('runnable') or not fact.get('sources') or not fact.get('version'):
            return False, 'Missing runnable, versioned evidence: ' + id_
        checked = datetime.fromisoformat(fact['last_verified']).date()
        age = ((now or datetime.now(timezone.utc)).date() - checked).days
        if age < 0 or age > facts.get('max_age_days', 90):
            return False, 'Capability evidence needs refresh: ' + id_
    if data.get('support_level') not in {'existing', 'easy_extension'}:
        return False, 'Requires product work or upstream-only repair'
    if not data.get('runnable_path') or not data.get('capability_evidence'):
        return False, 'Opportunity needs a concrete bounded runnable path'
    return True, 'Scoped capability gate passed; deployment still requires verification'


def validate(data, facts=None):
    # Legacy records remain readable but cannot be promoted by old score/evidence alone.
    for key, value in ACTION_DEFAULTS.items():
        data.setdefault(key, value)
    for key, values in ACTION_ENUMS.items():
        if data[key] not in values:
            raise ValueError('Invalid ' + key)
    if not isinstance(data['conversion_evidence'], list):
        raise ValueError('conversion_evidence must be a list')
    if data['outreach_permission'] == 'granted' and not data.get('permission_evidence'):
        raise ValueError('Outreach permission requires scope and authorization evidence')
    evidence = data.get('action_evidence', {})
    for field, states in {'validation_status': {'passed'}, 'review_status': {'approved', 'merged'},
                          'reply_status': {'replied'}, 'trial_status': {'started', 'completed', 'converted'}}.items():
        if data[field] in states:
            proof = evidence.get(field, {})
            if proof.get('state') != data[field] or not proof.get('source') or not proof.get('checked_at'):
                raise ValueError(field + ' requires matching independently observed state, source and date')
    if data['review_status'] == 'merged' and (not data['public_contribution_url'] or not evidence['review_status'].get('merged_at')):
        raise ValueError('PR URL/creation is not merge proof')
    if data['trial_status'] == 'converted' and not data['conversion_evidence']:
        raise ValueError('A comment/reply is not conversion proof')
    if data.get('schema_version') != 2:
        data['legacy_unverified'] = True
        if data['status'] in {'validated', 'ready_for_review'}:
            data['status'] = 'verification_pending'
        return
    a, b = axis(data['technical_fit'], A_LIMITS), axis(data['ecosystem_value'], B_LIMITS)
    if not data.get('score_evidence'):
        raise ValueError('Scores require explicit evidence and uncertainty')
    ok, reason = assess(data, facts)
    data['technical_score'], data['ecosystem_score'] = a, b
    data['eligibility_reason'] = reason
    data['eligible'] = ok
    if not ok and data['status'] not in {'rejected', 'blocked', 'resolved'}:
        raise ValueError(reason)
    if data['status'] in {'validated', 'ready_for_review'} and data['validation_status'] != 'passed':
        raise ValueError('Validated/ready requires actual validation evidence')
    if data['status'] == 'ready_for_review' and (a < 8 or data['technical_fit']['capability_match'] < 3):
        raise ValueError('High stars/value never override low technical fit')
    data['recommended_for_validation'] = ok and a >= 8 and data['technical_fit']['capability_match'] >= 3
    data['promotion_priority'] = 'candidate' if data['validation_status'] == 'passed' and data['recommended_for_validation'] and b >= 7 and data['ecosystem_value']['audience_evidence'] >= 2 else 'not_established'
