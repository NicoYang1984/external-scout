"""Deterministic replay of committed historical snapshots; no network or live DB."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'lazymind-ecosystem-scout/scripts'))
from screening import load_policy, evaluate, report, markdown

policy = load_policy()
at = '2026-10-30T12:00:00+00:00'
dest = ROOT / 'pipeline/campaigns/repository-intelligence-replay'
inputs = json.loads((dest / 'input.json').read_text())
results = [evaluate(c, policy, at) for c in inputs]
doc = report(results, policy, 'repository-intelligence-history-replay', at)
comparison = [dict(repo=c['profile']['repo'], campaign=c['campaign_type'],
                   old_decision=c['legacy_decision'], new_decision=r['gate']['decision'],
                   reason=r['gate']['reasons'], historical_reason=c['legacy_reason'])
              for c, r in zip(inputs, results)]
(dest / 'results.json').write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
(dest / 'report.md').write_text(markdown(doc))
(dest / 'comparison.json').write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(doc['funnel'], ensure_ascii=False))
