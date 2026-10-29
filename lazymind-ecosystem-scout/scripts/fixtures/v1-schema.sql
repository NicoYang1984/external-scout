
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
    