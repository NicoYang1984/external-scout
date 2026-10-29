"""Run with python3 test_registry.py; all records stay in a temporary directory."""
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class RegistryTest(unittest.TestCase):
    def test_only_current_or_easy_capabilities_become_opportunities(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(__file__).with_name("registry.py")

            def put(payload, valid=True):
                source = Path(directory) / "opportunity.json"
                source.write_text(json.dumps(payload))
                result = subprocess.run(
                    [sys.executable, str(script), "put", "--data-dir", directory, "--file", str(source)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode == 0, valid, result.stderr)

            base = {
                "url": "https://github.com/example/repo/issues/1",
                "repo": "example/repo",
                "title": "Fixture",
                "route": "issue_analysis",
                "category": "workflow_gap",
                "status": "ready_for_review",
                "evidence_level": "source_reviewed",
                "support_level": "existing",
                "capability_evidence": [{"path": "README.md", "finding": "already implemented"}],
                "score": 8,
                "score_breakdown": {"delivery_readiness": 4},
                "summary": "fixture",
                "sources": [{"url": "https://github.com/example/repo/issues/1", "finding": "fixture"}],
                "next_action": "fixture",
            }
            put(base)
            put({**base, "url": "https://github.com/example/repo/issues/2",
                 "support_level": "needs_product_work"}, valid=False)
            put({**base, "url": "https://github.com/example/repo/issues/3",
                 "support_level": "existing", "capability_evidence": []}, valid=False)
            put({**base, "url": "https://github.com/example/repo/issues/4",
                 "score": 7}, valid=False)
            put({**base, "url": "https://github.com/example/repo/issues/5",
                 "support_level": "needs_product_work", "capability_evidence": [],
                 "status": "rejected", "score": 2,
                 "score_breakdown": {"delivery_readiness": 0}})

    def test_incremental_memory_and_run_deduplication(self):
        # V1 scenario retained; V2 requires a claim token and scanner page receipts.
        import registry
        import state
        from sources import GitHubAdapter
        with tempfile.TemporaryDirectory() as directory:
            db = registry.connect(Path(directory))
            with db:
                first = state.claim(db, "owner/repo", "r1")
                self.assertEqual(first["action"], "analyze")
                self.assertEqual(state.claim(db, "owner/repo", "r1")["action"], "skip_this_run")
                state.begin_scan(db, "owner/repo", "r1", first["claim_token"], "s1")
                item = GitHubAdapter("owner/repo", 1, None).normalize(dict(
                    id=115, number=115, title="Pending", html_url="https://github.com/owner/repo/issues/115",
                    updated_at="2026-01-01T00:00:00Z", state="open"))
                state.ingest_page(db, "owner/repo", "r1", first["claim_token"], "s1", 1, [item], False)
                state.checkpoint(db, dict(repo="owner/repo",status="completed",run_id="r1",
                    summary="fixture",coverage={"reviewed_urls":[]},memory={"architecture":"module A", "handoff":"next"}, next_action="continue"),first["claim_token"])
                second = state.claim(db, "owner/repo", "r2")
                self.assertEqual(second["action"], "incremental")
                state.checkpoint(db, dict(repo="owner/repo",status="partial",run_id="r2",
                    summary="fixture",coverage={"reviewed_urls":[]},memory={"handoff":"new"},next_action="continue"),second["claim_token"])
            memory = state.read_repo(db, "owner/repo")
            self.assertEqual(memory["memory"]["architecture"], "module A")
            self.assertEqual(memory["cursor"]["pending_issue_numbers"], [115])
            self.assertEqual(memory["cursor"]["last_issue_number"], 115)
            with self.assertRaises(ValueError), db:
                state.checkpoint(db, dict(repo="owner/repo",run_id="r2",status="partial",cursor={"last_issue_number":119}),second["claim_token"])
            with db:
                db.execute("UPDATE claims SET expires='2000-01-01' WHERE repo='owner/repo'")
                self.assertEqual(state.claim(db, "owner/repo", "r3")["action"], "resume")
            self.assertIsNone(state.read_repo(db,"other/repo"))
            db.close()


if __name__ == "__main__":
    unittest.main()
