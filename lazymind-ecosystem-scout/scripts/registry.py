#!/usr/bin/env python3
"""Small persistent opportunity registry; no network or scheduler."""
import argparse
import os
import state
import policy
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_CONFIG = {
    "project_root": None,
    "schedule_enabled": False,
    "timezone": "Asia/Shanghai",
    "max_repositories_per_run": 5,
    "max_deep_analyses_per_run": 2,
    "soft_time_budget_minutes": 20,
    "seed_repositories": [],
    "focus": ["skill_reliability", "workflow_gap", "agent_integration", "upstream_bug"],
    "external_writes_enabled": False,
    "repository_revisit_policy": "incremental",
    "opportunity_policy": "existing_or_easy_extension_only",
}
STATUSES = {"discovered", "analyzed", "verification_pending", "validated",
            "ready_for_review", "rejected", "resolved", "blocked"}
LEVELS = {"hypothesis", "source_reviewed", "reproduced", "comparative_tested"}
SUPPORT_LEVELS = {"existing", "easy_extension", "needs_product_work", "upstream_only", "not_applicable"}


def canonical_url(value):
    p = urlsplit(value)
    parts = p.path.strip("/").split("/")
    if p.scheme != "https" or p.netloc.lower() != "github.com":
        raise ValueError("Expected an https://github.com repository/issue/discussion URL")
    if not (len(parts) == 2 or (len(parts) == 4 and parts[2] in {"issues", "pull", "discussions"}
                             and parts[3].isdigit())) or not all(parts):
        raise ValueError("Expected OWNER/REPO or OWNER/REPO/issues|discussions/NUMBER")
    return "https://github.com/" + "/".join(parts).lower()


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical_repo(value):
    value = value.strip()
    url = canonical_url(value if "://" in value else "https://github.com/" + value)
    parts = urlsplit(url).path.strip("/").split("/")
    if len(parts) != 2:
        raise ValueError("Expected a repository, not an issue URL")
    parts[1] = parts[1].removesuffix(".git")
    if not parts[1]:
        raise ValueError("Repository name is empty")
    return "/".join(parts)


def connect(root, allow_upgrade=False):
    root = Path(root).expanduser()
    database = root / "opportunities.sqlite3"
    if database.exists() and not allow_upgrade:
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as check:
            version = check.execute("PRAGMA user_version").fetchone()[0]
            tables = check.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if tables and version != 2:
                raise ValueError("Existing database is not V2; use migrate.py to create a new copy")
    root.mkdir(parents=True, exist_ok=True)
    config = root / "config.json"
    try:
        with config.open("x", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except FileExistsError:
        pass
    db = sqlite3.connect(root / "opportunities.sqlite3", timeout=10)
    db.executescript("BEGIN IMMEDIATE;" + """
        CREATE TABLE IF NOT EXISTS opportunities (
            url TEXT PRIMARY KEY, updated_at TEXT NOT NULL,
            next_review_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY, url TEXT NOT NULL,
            recorded_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY, run_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS repositories (
            repo TEXT PRIMARY KEY, updated_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS repository_history (
            id INTEGER PRIMARY KEY, repo TEXT NOT NULL,
            recorded_at TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS repository_visits (
            run_id TEXT NOT NULL, repo TEXT NOT NULL, started_at TEXT NOT NULL,
            PRIMARY KEY(run_id, repo));
    """ + state.SCHEMA + "PRAGMA user_version=2; COMMIT;")
    return db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "put", "list", "due", "history", "log", "runs",
                                            "repo-check", "repo-start", "repo-memory", "repo-put", "repos", "repo-history", "repo-identify", "repo-heartbeat", "dispose", "handoff", "handoffs"])
    parser.add_argument("--data-dir", type=Path, default=state.data_dir())
    parser.add_argument("--file", type=Path)
    parser.add_argument("--repo")
    parser.add_argument("--run-id")
    parser.add_argument("--rescan-reason", help="Use only for an explicitly user-requested rescan")
    parser.add_argument("--claim-token")
    parser.add_argument("--repo-id")
    parser.add_argument("--lease-seconds", type=int, default=300)
    args = parser.parse_args()
    data = None
    try:
        if args.command in {"handoff", "handoffs"}:
            from pipeline_store import Store
            store = Store(args.data_dir)
            try:
                if args.command == "handoff" and not args.file:
                    raise ValueError("--file is required")
                result = store.put(json.loads(args.file.read_text())) if args.command == "handoff" else store.list()
                print(json.dumps(result, ensure_ascii=False, indent=2))
            finally:
                store.close()
            return
        if args.command in {"put", "log", "repo-put", "dispose"}:
            if not args.file:
                raise ValueError("--file is required")
            data = json.loads(args.file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Input must be a JSON object")
        if args.command in {"repo-check", "repo-start", "repo-memory", "repo-identify", "repo-heartbeat"}:
            if not args.repo:
                raise ValueError("--repo is required")
            repo = canonical_repo(args.repo)
            if args.command in {"repo-check", "repo-start", "repo-heartbeat"} and not args.run_id:
                raise ValueError("--run-id is required for per-run deduplication")
        if args.command == "repo-put":
            for key in ["repo", "status", "run_id", "summary", "coverage", "next_action"]:
                if not data.get(key):
                    raise ValueError(f"Missing or empty {key}")
            data["repo"] = canonical_repo(data["repo"])
            if data["status"] not in {"partial", "completed", "excluded"}:
                raise ValueError("Invalid repository status")
            if not isinstance(data["coverage"], dict) or not isinstance(data["coverage"].get("reviewed_urls"), list):
                raise ValueError("coverage.reviewed_urls must be a list")
            if "cursor" in data:
                c = data["cursor"]
                if not isinstance(c, dict) or ("last_issue_number" in c and (type(c["last_issue_number"]) is not int or c["last_issue_number"] < 0)):
                    raise ValueError("cursor.last_issue_number must be a nonnegative integer")
                if not isinstance(c.get("pending_issue_numbers", []), list) or any(type(n) is not int or n < 1 for n in c.get("pending_issue_numbers", [])):
                    raise ValueError("pending_issue_numbers must contain positive integers")
            if "memory" in data and not isinstance(data["memory"], dict):
                raise ValueError("memory must be an object")
        if args.command == "put":
            if data.get("schema_version") == 2:
                data["score"] = policy.axis(data["technical_fit"], policy.A_LIMITS)
            for key in ["url", "repo", "title", "route", "category", "status",
                        "evidence_level", "support_level", "capability_evidence",
                        "score", "summary", "sources", "next_action"]:
                if key not in data:
                    raise ValueError(f"Missing {key}")
            if data.get("schema_version") == 2:
                from sources import canonical
                data["url"] = canonical(data["url"])
            else:
                data["url"] = canonical_url(data["url"])
            if urlsplit(data["url"]).hostname == "github.com" and data["repo"].lower() != "/".join(urlsplit(data["url"]).path.strip("/").split("/")[:2]):
                raise ValueError("repo must match URL")
            if data["status"] not in STATUSES or data["evidence_level"] not in LEVELS:
                raise ValueError("Invalid status or evidence_level")
            if data["support_level"] not in SUPPORT_LEVELS:
                raise ValueError("Invalid support_level")
            if not isinstance(data["capability_evidence"], list):
                raise ValueError("capability_evidence must be a list")
            eligible = data["support_level"] in {"existing", "easy_extension"}
            if not eligible and data["status"] not in {"rejected", "resolved"}:
                raise ValueError("Non-deliverable candidates must be rejected or resolved")
            if eligible and not data["capability_evidence"]:
                raise ValueError("Deliverable candidates require current LazyMind capability evidence")
            if data["route"] not in {"small_project", "issue_analysis"}:
                raise ValueError("Invalid route")
            if data["category"] not in set(DEFAULT_CONFIG["focus"]) | {"not_fit"}:
                raise ValueError("Invalid category")
            if type(data["score"]) is not int or not 0 <= data["score"] <= 10:
                raise ValueError("score must be an integer from 0 to 10")
            readiness = data.get("score_breakdown", {}).get("delivery_readiness")
            if data.get("schema_version") != 2 and data["status"] == "ready_for_review" and (
                not eligible or data["score"] < 8 or type(readiness) is not int or readiness < 3
            ):
                raise ValueError("ready_for_review requires eligible support, score >= 8, and delivery_readiness >= 3")
            if not isinstance(data["sources"], list) or not data["sources"]:
                raise ValueError("sources must be a nonempty list")
            policy.validate(data)
            days = data.get("revisit_after_days", 30 if data["status"] in {"rejected", "resolved"} else 7)
            if type(days) is not int or not 0 <= days <= 365:
                raise ValueError("revisit_after_days must be an integer from 0 to 365")
        if args.command == "log":
            if not data.get("run_id") or data.get("status") not in {"started", "completed", "blocked"}:
                raise ValueError("run_id and status (started/completed/blocked) required")
        db = connect(args.data_dir.expanduser())
        with db:
            stamp = now()
            if args.command == "init":
                result = {"data_dir": str(args.data_dir.expanduser().resolve()), "scheduler_created": False}
            elif args.command in {"repo-check", "repo-start", "repo-memory", "repo-identify", "repo-heartbeat"}:
                db.execute("BEGIN IMMEDIATE")
                repo = state.resolve(db, repo)
                if args.command == "repo-identify":
                    result = state.identify(db, repo, args.repo_id)
                elif args.command == "repo-heartbeat":
                    state.require_claim(db, repo, args.run_id, args.claim_token)
                    if not 1 <= args.lease_seconds <= 3600:
                        raise ValueError("lease-seconds must be 1..3600")
                    expires = (datetime.now(timezone.utc) + timedelta(seconds=args.lease_seconds)).isoformat()
                    db.execute("UPDATE claims SET expires=? WHERE repo=?", (expires, repo))
                    result = dict(repo=repo, lease_expires_at=expires)
                else:
                    result = state.claim(db, repo, args.run_id, args.lease_seconds,
                                         preview=args.command != "repo-start", rescan=args.rescan_reason)
                    if args.command == "repo-memory":
                        result.pop("action")
                        result.pop("rescan_reason")
            elif args.command == "repo-put":
                db.execute("BEGIN IMMEDIATE")
                result = state.checkpoint(db, data, args.claim_token)
            elif args.command == "dispose":
                db.execute("BEGIN IMMEDIATE")
                repo = state.resolve(db, canonical_repo(data["repo"]))
                state.require_claim(db, repo, data["run_id"], args.claim_token)
                state.dispose(db, repo, data["number"], data["updated_at"], data["evidence"])
                result = dict(repo=repo, number=data["number"], recorded=True)
            elif args.command == "repos":
                result = [dict(json.loads(p), updated_at=t) for p, t in
                          db.execute("SELECT payload, updated_at FROM repositories ORDER BY repo")]
            elif args.command == "repo-history":
                result = [dict(json.loads(p), recorded_at=t) for p, t in
                          db.execute("SELECT payload, recorded_at FROM repository_history ORDER BY id")]
            elif args.command == "put":
                db.execute("BEGIN IMMEDIATE")
                old_repo = data["repo"].lower()
                data["repo"] = state.resolve(db, old_repo)
                if old_repo != data["repo"]:
                    data["url"] = data["url"].replace("https://github.com/" + old_repo, "https://github.com/" + data["repo"], 1)
                row = db.execute("SELECT payload FROM opportunities WHERE url=?", (data["url"],)).fetchone()
                if row:
                    prior = json.loads(row[0])
                    # Only explicit input fields replace outcomes; defaults do not erase them.
                    explicit = json.loads(args.file.read_text(encoding="utf-8"))
                    for key in set(policy.ACTION_DEFAULTS) | {"action_evidence", "permission_evidence"}:
                        if key not in explicit and key in prior:
                            data[key] = prior[key]
                    data["conversion_evidence"] = state.merge(prior.get("conversion_evidence", []), data["conversion_evidence"])
                    policy.validate(data)
                review = (datetime.fromisoformat(stamp) + timedelta(days=days)).isoformat()
                payload = json.dumps(data, ensure_ascii=False)
                db.execute("INSERT INTO history(url, recorded_at, payload) VALUES (?, ?, ?)",
                           (data["url"], stamp, payload))
                db.execute("""INSERT INTO opportunities VALUES (?, ?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET updated_at=excluded.updated_at,
                    next_review_at=excluded.next_review_at, payload=excluded.payload""",
                           (data["url"], stamp, review, payload))
                result = {"url": data["url"], "next_review_at": review}
            elif args.command in {"list", "due"}:
                query = "SELECT payload, updated_at, next_review_at FROM opportunities"
                params = ()
                if args.command == "due":
                    query += " WHERE next_review_at <= ?"
                    params = (stamp,)
                rows = db.execute(query + " ORDER BY next_review_at, url", params)
                result = [dict(json.loads(p), updated_at=u, next_review_at=n) for p, u, n in rows]
            elif args.command == "log":
                db.execute("INSERT INTO runs(run_id, recorded_at, payload) VALUES (?, ?, ?)",
                           (data["run_id"], stamp, json.dumps(data, ensure_ascii=False)))
                result = {"run_id": data["run_id"], "recorded": True}
            else:
                table = "history" if args.command == "history" else "runs"
                result = [dict(json.loads(p), recorded_at=t) for p, t in
                          db.execute(f"SELECT payload, recorded_at FROM {table} ORDER BY id")]
        db.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, TypeError, AttributeError, OSError, sqlite3.Error) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
