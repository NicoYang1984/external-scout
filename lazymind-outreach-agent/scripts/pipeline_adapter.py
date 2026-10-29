"""Import explicit pipeline contact candidates without creating drafts or approvals."""
import json
from datetime import datetime, timezone

from outreach_core import stable_json, utcnow


def import_pipeline(store, path):
    document = json.loads(path.read_text())
    imported, skipped = [], []
    for task in document['tasks']:
        if task['status'] != 'candidate_review' or task['send_authorized'] is not False:
            raise ValueError('Pipeline can only hand off unapproved candidate tasks')
        if task['source_campaign'] not in {'resource_listing', 'native_skill_fix', 'product_integration'}:
            raise ValueError('Unknown source campaign')
        channel = task['channel']
        date = datetime.fromisoformat(channel['verified_at'].replace('Z', '+00:00'))
        if date.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - date).total_seconds() <= 30 * 86400:
            raise ValueError('Refresh channel evidence before import')
        ids = {x['id'] for x in task['evidence']}
        if channel['suitable'] is not True or not channel['value'] or not channel['purpose'] or not channel['evidence_ids'] or not set(channel['evidence_ids']) <= ids:
            raise ValueError('Explicit suitable collaboration channel evidence required')
        source = 'pipeline:' + task['opportunity_id']
        # Never overwrite a prior contact, suppression, approval or newer lead state.
        if store.conn.execute('SELECT 1 FROM scout_records WHERE source_id=?', (source,)).fetchone():
            skipped.append(source)
            continue
        existing = store.conn.execute('SELECT id FROM leads WHERE normalized_contact=? AND campaign_type=?',
                                      (channel['value'].strip().rstrip('/').casefold(), 'developer_collaboration')).fetchone()
        if existing:
            skipped.append(source)
            continue
        lead = store.upsert_lead({
            'id': task['task_id'], 'organization': task['source_repo'], 'project_name': task['source_repo'],
            'campaign_type': 'developer_collaboration', 'source_kind': 'opportunity_pipeline',
            'scout_source_id': source, 'source_url': task['pr_url'],
            'pain_point': task['expected_user_value'],
            'evidence': [{'url': x['source'], 'finding': x['finding']} for x in task['evidence']],
            'contact_channel': channel['kind'], 'contact_value': channel['value'],
            'allowed_purpose': channel['purpose'], 'permission_status': 'not_granted',
            'permission_verified_at': None, 'language': 'language_unknown',
            'case_links': [task['pr_url']], 'risk_notes': 'Source campaign: ' + task['source_campaign'] +
                '; observed PR status: ' + task['observed_status'] + '; no send authorization transferred.',
            'status': 'discovered',
        })
        store.conn.execute('INSERT INTO scout_records VALUES (?,?,?,?,?,?,?)',
                           (source, 'pipeline_candidate', task['pr_url'], stable_json(task), '[]', '', utcnow()))
        store.conn.commit()
        imported.append(lead)
    return {'imported': imported, 'skipped_existing': skipped, 'drafts_created': 0, 'messages_sent': 0}
