from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .files import json_bytes


class Journal:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "journal.sqlite"
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS commands (
              id TEXT PRIMARY KEY, signature TEXT NOT NULL, payload TEXT NOT NULL,
              state TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}', acked INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS artifacts (
              id TEXT PRIMARY KEY, path TEXT NOT NULL, sha TEXT NOT NULL, acked INTEGER DEFAULT 0);
            """)
            db.execute("UPDATE commands SET state='UNKNOWN', result=? WHERE state='STARTED'",
                       (json.dumps({"error": "agent restarted during command; not replayed"}),))

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def get(self, command_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
            return self.decode(row) if row else None

    @staticmethod
    def decode(row):
        result = dict(row)
        for name in ("payload", "result"):
            result[name] = json.loads(result[name])
        return result

    def start(self, command):
        # Session/dispatch state are transport fields, not action identity.
        payload = {k: command[k] for k in ("id", "instrument_id", "run_id", "op", "parameters")
                   if k in command}
        encoded = json_bytes(payload)
        signature = hashlib.sha256(encoded).hexdigest()
        with self.connect() as db:
            row = db.execute("SELECT * FROM commands WHERE id=?", (command["id"],)).fetchone()
            if row:
                if row["signature"] != signature:
                    raise ValueError("duplicate command has different payload")
                return self.decode(row)
            db.execute("INSERT INTO commands(id,signature,payload,state) VALUES(?,?,?,'STARTED')",
                       (command["id"], signature, encoded.decode()))
        return None

    def finish(self, command_id, state, result):
        if state not in {"COMPLETED", "FAILED", "UNKNOWN"}:
            raise ValueError("invalid terminal state")
        with self.connect() as db:
            db.execute("UPDATE commands SET state=?,result=?,acked=0 WHERE id=?",
                       (state, json_bytes(result).decode(), command_id))

    def pending_results(self):
        with self.connect() as db:
            return [self.decode(r) for r in db.execute(
                "SELECT * FROM commands WHERE state!='STARTED' AND acked=0")]

    def ack_result(self, command_id):
        with self.connect() as db:
            db.execute("UPDATE commands SET acked=1 WHERE id=?", (command_id,))

    def add_artifact(self, command_id, path, sha):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO artifacts(id,path,sha) VALUES(?,?,?)",
                       (command_id, str(path), sha))

    def pending_artifacts(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM artifacts WHERE acked=0")]

    def ack_artifact(self, command_id):
        with self.connect() as db:
            db.execute("UPDATE artifacts SET acked=1 WHERE id=?", (command_id,))
