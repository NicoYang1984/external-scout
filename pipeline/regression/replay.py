#!/usr/bin/env python3
"""Offline regression of real captured cases in a disposable database; no network writes."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'lazymind-ecosystem-scout/scripts'))
from opportunity import gate, outreach_candidate
from pipeline_github import summarize
from pipeline_store import Store


def main():
    capture = json.loads((Path(__file__).parent / 'github-cases.json').read_text())
    result = {'mode': 'historical_snapshot_replay', 'captured_at': capture['captured_at'],
              'new_external_prs': 0, 'new_merges': 0, 'cases': []}
    with tempfile.TemporaryDirectory() as directory:
        store = Store(directory)
        try:
            for path in sorted((ROOT / 'pipeline/examples').glob('*.json')):
                imported = store.put(json.loads(path.read_text()))
                oid = imported['opportunity_id']
                spec = store.get(oid)
                key = {'resource_listing': 'awesome', 'product_integration': 'marketing'}.get(spec['campaign_type'])
                outcome = {}
                if key:
                    x = capture['cases'][key]
                    outcome = summarize(x['pr'], x['checks'], x['runs'], x['statuses'], x['reviews'])
                    outcome['query_source'] = 'Captured GitHub REST API snapshot'
                    store.observe(oid, outcome)
                    assert not store.observe(oid, outcome)['changed']
                assert store.put(spec)['duplicate']
                result['cases'].append({'opportunity_id': oid, 'campaign_type': spec['campaign_type'],
                                        'provenance': spec['provenance']['kind'], 'gate': gate(spec),
                                        'outcome': outcome or {'status': 'blocked_duplicate', 'existing_fix': capture['cases']['native']['linked_prs']},
                                        'outreach_candidate': outreach_candidate(spec, outcome)})
        finally:
            store.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
