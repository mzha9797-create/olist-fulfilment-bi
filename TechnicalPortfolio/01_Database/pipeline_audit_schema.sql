CREATE TABLE pipeline_runs (
          run_id TEXT PRIMARY KEY, started_utc TEXT NOT NULL, finished_utc TEXT,
          status TEXT NOT NULL, duration_seconds REAL, source_hashes_json TEXT,
          counts_json TEXT, error TEXT);
