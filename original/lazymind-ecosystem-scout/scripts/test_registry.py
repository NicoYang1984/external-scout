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
        with tempfile.TemporaryDirectory() as directory:
            script = Path(__file__).with_name("registry.py")

            def call(command, *args, payload=None, valid=True):
                argv = [sys.executable, str(script), command, "--data-dir", directory, *args]
                if payload is not None:
                    source = Path(directory) / "input.json"
                    source.write_text(json.dumps(payload))
                    argv += ["--file", str(source)]
                result = subprocess.run(argv, capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, valid, result.stderr)
                return json.loads(result.stdout) if valid else None

            call("init")
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: call("repo-start", "--repo", "Owner/Repo", "--run-id", "r1"), range(2)))
            self.assertEqual(sorted(r["action"] for r in results), ["analyze", "skip_this_run"])
            record = dict(repo="owner/repo", status="completed", run_id="r1",
                          summary="fixture", coverage={"reviewed_urls": []},
                          cursor={"last_issue_number": 120, "pending_issue_numbers": [115]},
                          memory={"architecture": "module A", "handoff": "next issue 121"},
                          next_action="continue")
            call("repo-put", payload=record)
            self.assertEqual(call("repo-start", "--repo", "https://github.com/OWNER/Repo.git/", "--run-id", "r1")["action"], "skip_this_run")
            next_run = call("repo-start", "--repo", "owner/repo", "--run-id", "r2")
            self.assertEqual(next_run["action"], "incremental")
            self.assertEqual(next_run["previous"]["cursor"]["pending_issue_numbers"], [115])
            record.update(run_id="r2", cursor={"last_issue_number": 125}, memory={"handoff": "next issue 126"})
            call("repo-put", payload=record)
            memory = call("repo-memory", "--repo", "owner/repo")["previous"]
            self.assertEqual(memory["memory"]["architecture"], "module A")
            self.assertEqual(memory["cursor"]["pending_issue_numbers"], [115])
            self.assertEqual(memory["cursor"]["last_issue_number"], 125)
            record["cursor"] = {"last_issue_number": 119}
            call("repo-put", payload=record, valid=False)
            self.assertEqual(len(call("repo-history")), 2)
            self.assertIsNone(call("repo-memory", "--repo", "other/repo")["previous"])
            self.assertEqual(call("repo-start", "--repo", "other/repo", "--run-id", "r2")["action"], "analyze")
            record.update(status="partial", cursor={"last_issue_number": 126})
            call("repo-put", payload=record)
            self.assertEqual(call("repo-start", "--repo", "owner/repo", "--run-id", "r3")["action"], "resume")


if __name__ == "__main__":
    unittest.main()
