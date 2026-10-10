"""Persistent full-refresh batch audit. Run this entry point for reproducible builds.

The audit database survives replacement of fulfilment.sqlite. No incremental or
row-level change capture is claimed. A failed run is recorded and re-raised.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, sqlite3, time, uuid
import run_etl
from contextlib import closing

def utc():
    return datetime.now(timezone.utc).isoformat()

def execute(job=None, audit_path=None):
    path = Path(audit_path or run_etl.DBDIR/'pipeline_audit.sqlite')
    run_id = str(uuid.uuid4())
    files = {p.name:hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((run_etl.DATA/'03_Raw_Dataset').glob('*.csv'))}
    started = time.perf_counter()
    with closing(sqlite3.connect(path)) as c, c:
        c.execute('''CREATE TABLE IF NOT EXISTS pipeline_runs (
          run_id TEXT PRIMARY KEY, started_utc TEXT NOT NULL, finished_utc TEXT,
          status TEXT NOT NULL, duration_seconds REAL, source_hashes_json TEXT,
          counts_json TEXT, error TEXT)''')
        c.execute('INSERT INTO pipeline_runs(run_id,started_utc,status,source_hashes_json) VALUES(?,?,?,?)',
                  (run_id,utc(),'RUNNING',json.dumps(files,sort_keys=True)))
    try:
        (job or run_etl.main)()
        counts={}
        if job is None:
            with sqlite3.connect(run_etl.DBDIR/'fulfilment.sqlite') as c:
                counts={n:c.execute('SELECT COUNT(*) FROM '+n).fetchone()[0] for n in run_etl.NAMES}
        status,error='SUCCESS',None
    except BaseException as exc:
        status,error,counts='FAILED',f'{type(exc).__name__}: {exc}',{}
        raise
    finally:
        with closing(sqlite3.connect(path)) as c, c:
            c.execute('UPDATE pipeline_runs SET finished_utc=?,status=?,duration_seconds=?,counts_json=?,error=? WHERE run_id=?',
                      (utc(),status,time.perf_counter()-started,json.dumps(counts),error,run_id))
    return run_id

if __name__=='__main__':
    execute()

