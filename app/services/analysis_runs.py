"""Local analysis history. Reading a run never executes it or contacts Redis/LLMs."""
import hashlib
import json
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path

from app.core.config import settings


class RunAlreadyStarted(RuntimeError):
    pass


class AnalysisRunStore:
    def __init__(self):
        self.path = (Path(__file__).resolve().parents[2] / settings.ANALYSIS_RUN_DB).resolve()

    def start(self, task_id, metadata):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            version = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                cwd=Path(__file__).resolve().parents[2], text=True, timeout=2).strip()
        except (OSError, subprocess.SubprocessError):
            version = 'unknown'
        now = time.time()
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, status TEXT,
                created_at REAL, updated_at REAL, code_commit TEXT, metadata TEXT,
                input_json TEXT, result_json TEXT, error TEXT)''')
            db.execute('''CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY,
                run_id TEXT, event_json TEXT)''')
            db.execute('CREATE INDEX IF NOT EXISTS events_by_run ON events(run_id, seq)')
            return db.execute('INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?,?,NULL,NULL,NULL)',
                (task_id, 'STARTED', now, now, version, json.dumps(metadata))).rowcount == 1

    def set_metadata(self, task_id, values):
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            row = db.execute('SELECT metadata FROM runs WHERE id=?', (task_id,)).fetchone()
            metadata = {**json.loads(row[0]), **values}
            db.execute('UPDATE runs SET metadata=?,updated_at=? WHERE id=?',
                       (json.dumps(metadata), time.time(), task_id))

    def save_input(self, task_id, payload):
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            row = db.execute('SELECT metadata FROM runs WHERE id=?', (task_id,)).fetchone()
            metadata = json.loads(row[0])
            metadata.update({"match_id": payload.get("match_id"), "map": payload.get("map_name")})
            metadata['payload_sha256'] = hashlib.sha256(encoded.encode()).hexdigest()
            db.execute('UPDATE runs SET input_json=?, metadata=?, updated_at=? WHERE id=?',
                (encoded, json.dumps(metadata), time.time(), task_id))

    def event(self, task_id, event):
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute('INSERT INTO events(run_id,event_json) VALUES (?,?)',
                (task_id, json.dumps(event, ensure_ascii=False)))
            db.execute('UPDATE runs SET updated_at=? WHERE id=?', (time.time(), task_id))

    def finish(self, task_id, result=None, error=None):
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            db.execute('UPDATE runs SET status=?,result_json=?,error=?,updated_at=? WHERE id=?',
                ('FAILURE' if error else 'SUCCESS', json.dumps(result, ensure_ascii=False) if result is not None else None,
                 error, time.time(), task_id))

    def get(self, task_id):
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            row = db.execute('SELECT id,status,created_at,updated_at,code_commit,metadata,result_json,error FROM runs WHERE id=?',
                             (task_id,)).fetchone()
            if row is None:
                return None
            events = [json.loads(r[0]) for r in db.execute(
                'SELECT event_json FROM events WHERE run_id=? ORDER BY seq', (task_id,))]
        result = dict(zip(('task_id','status','created_at','updated_at','code_commit','metadata','result','error'), row))
        result['metadata'] = json.loads(result['metadata'])
        result['result'] = json.loads(result['result']) if result['result'] else None
        result['events'] = events
        result['storage'] = 'local'
        return result

    def recent(self, limit=20):
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            rows = db.execute('SELECT id,status,created_at,updated_at,metadata FROM runs ORDER BY created_at DESC LIMIT ?',
                              (limit,)).fetchall()
        return [dict(task_id=r[0], status=r[1], created_at=r[2], updated_at=r[3], metadata=json.loads(r[4])) for r in rows]
