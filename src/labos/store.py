from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .files import Measurement, atomic_write, json_bytes
from .models import QualityPolicy
from .quality import UNASSESSED, assess


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "central.sqlite"
        self.lock = threading.RLock()
        with self.transaction() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS agents (
              id TEXT PRIMARY KEY, boot_id TEXT, seen REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS instruments (
              id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, spec TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT '{}', seen REAL DEFAULT 0, lock_run TEXT);
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY, status TEXT NOT NULL, plan TEXT NOT NULL, setup TEXT NOT NULL,
              preflight TEXT NOT NULL, created REAL NOT NULL, error TEXT, points INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS commands (
              id TEXT PRIMARY KEY, unique_key TEXT UNIQUE NOT NULL, agent_id TEXT NOT NULL,
              instrument_id TEXT NOT NULL, run_id TEXT NOT NULL, op TEXT NOT NULL,
              parameters TEXT NOT NULL, state TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}',
              created REAL NOT NULL, dispatched REAL, boot_id TEXT);
            CREATE TABLE IF NOT EXISTS measurements (
              id TEXT PRIMARY KEY, run_id TEXT NOT NULL, point_index INTEGER NOT NULL,
              sha TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(run_id,point_index));
            CREATE TABLE IF NOT EXISTS events (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, time REAL NOT NULL,
              run_id TEXT, category TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS qualifications (
              measurement_id TEXT PRIMARY KEY, status TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reviews (
              id TEXT PRIMARY KEY, run_id TEXT NOT NULL, version INTEGER NOT NULL,
              sha256 TEXT NOT NULL, created REAL NOT NULL, body TEXT NOT NULL,
              UNIQUE(run_id,version));
            """)

    @contextmanager
    def transaction(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    @staticmethod
    def event_db(db, category, detail, run_id=None):
        db.execute("INSERT INTO events(time,run_id,category,detail) VALUES(?,?,?,?)",
                   (time.time(), run_id, category, json_bytes(detail).decode()))

    def event(self, category, detail, run_id=None):
        with self.transaction() as db:
            self.event_db(db, category, detail, run_id)

    def enroll(self, agent_id, instruments):
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO agents(id) VALUES(?)", (agent_id,))
            for spec in instruments:
                row = db.execute("SELECT agent_id FROM instruments WHERE id=?", (spec.id,)).fetchone()
                if row and row["agent_id"] != agent_id:
                    raise ValueError("instrument ownership cannot change")
                db.execute("""INSERT INTO instruments(id,agent_id,spec) VALUES(?,?,?)
                ON CONFLICT(id) DO UPDATE SET spec=excluded.spec""",
                           (spec.id, agent_id, spec.model_dump_json()))

    @staticmethod
    def session(db, agent_id, boot_id):
        row = db.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
        if not row or row["boot_id"] != boot_id:
            raise ValueError("invalid agent session")
        return row

    def register(self, agent_id, boot_id, now=None, offline_after=10):
        now = time.time() if now is None else now
        with self.transaction() as db:
            row = db.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
            if not row:
                raise ValueError("agent not enrolled")
            if row["boot_id"] and row["boot_id"] != boot_id and now-row["seen"] < offline_after:
                raise ValueError("another live agent session exists")
            if row["boot_id"] != boot_id:
                db.execute("UPDATE commands SET state='UNKNOWN',result=? WHERE agent_id=? AND state='DISPATCHED'",
                           (json.dumps({"error": "agent session changed"}), agent_id))
            db.execute("UPDATE agents SET boot_id=?,seen=? WHERE id=?", (boot_id, now, agent_id))
            self.event_db(db, "AGENT_REGISTERED", {"agent_id": agent_id, "boot_id": boot_id})

    def heartbeat(self, agent_id, boot_id, statuses, now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            self.session(db, agent_id, boot_id)
            db.execute("UPDATE agents SET seen=? WHERE id=?", (now, agent_id))
            for instrument_id, status in statuses.items():
                row = db.execute("SELECT agent_id FROM instruments WHERE id=?", (instrument_id,)).fetchone()
                if not row or row["agent_id"] != agent_id:
                    raise ValueError("instrument ownership mismatch")
                db.execute("UPDATE instruments SET status=?,seen=? WHERE id=?",
                           (json_bytes(status).decode(), now, instrument_id))

    def disconnect(self, agent_id, boot_id):
        with self.transaction() as db:
            self.session(db, agent_id, boot_id)
            db.execute("UPDATE agents SET seen=0 WHERE id=?", (agent_id,))
            db.execute("UPDATE instruments SET seen=0 WHERE agent_id=?", (agent_id,))

    def registry(self, offline_after=10):
        with self.transaction() as db:
            agents = [dict(r) for r in db.execute("SELECT id,seen FROM agents ORDER BY id")]
            instruments = [dict(r) for r in db.execute("SELECT * FROM instruments ORDER BY id")]
        now = time.time()
        for agent in agents:
            agent["online"] = now-agent["seen"] < offline_after
        for instrument in instruments:
            instrument["spec"] = json.loads(instrument["spec"])
            instrument["status"] = json.loads(instrument["status"])
            instrument["online"] = now-instrument["seen"] < offline_after
        return {"agents": agents, "instruments": instruments}

    @staticmethod
    def decode_run(row):
        if not row:
            raise KeyError("run not found")
        result = dict(row)
        for key in ("plan", "setup", "preflight"):
            result[key] = json.loads(result[key])
        return result

    def create_run(self, plan, setup, snapshot):
        run_id = "exp_" + uuid.uuid4().hex
        with self.transaction() as db:
            specs = {}
            for instrument_id in setup.devices.values():
                row = db.execute("SELECT lock_run FROM instruments WHERE id=?", (instrument_id,)).fetchone()
                if not row:
                    raise ValueError("instrument not registered")
                if row["lock_run"]:
                    raise ValueError("instrument already reserved")
                enrolled = dict(db.execute("SELECT agent_id,spec FROM instruments WHERE id=?",
                                           (instrument_id,)).fetchone())
                specs[instrument_id] = {"agent_id": enrolled["agent_id"], "spec": json.loads(enrolled["spec"])}
            snapshot = {**snapshot, "fingerprints": {
                "plan_sha256": hashlib.sha256(json_bytes(plan.model_dump())).hexdigest(),
                "configuration_sha256": hashlib.sha256(json_bytes({"setup": setup.model_dump(),
                                                                   "instruments": specs})).hexdigest()}}
            db.execute("INSERT INTO runs(id,status,plan,setup,preflight,created) VALUES(?,'RUNNING',?,?,?,?)",
                       (run_id, plan.model_dump_json(), setup.model_dump_json(),
                        json_bytes(snapshot).decode(), time.time()))
            for instrument_id in setup.devices.values():
                db.execute("UPDATE instruments SET lock_run=? WHERE id=?", (run_id, instrument_id))
            self.event_db(db, "RUN_STARTED", {"plan": plan.model_dump()}, run_id)
        return self.run(run_id)

    def provenance(self, run_id):
        return self.run(run_id)["preflight"].get("fingerprints", {})

    def run(self, run_id):
        with self.transaction() as db:
            return self.decode_run(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())

    def runs(self):
        with self.transaction() as db:
            return [self.decode_run(r) for r in db.execute("SELECT * FROM runs ORDER BY created DESC LIMIT 100")]

    def set_run(self, run_id, status, error=None, release=False):
        with self.transaction() as db:
            db.execute("UPDATE runs SET status=?,error=? WHERE id=?", (status, error, run_id))
            if release:
                db.execute("UPDATE instruments SET lock_run=NULL WHERE lock_run=?", (run_id,))
            self.event_db(db, "WORKFLOW_STATE", {"status": status, "error": error}, run_id)

    def transition(self, run_id, allowed, target):
        with self.transaction() as db:
            row = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row or row["status"] not in allowed:
                raise ValueError("invalid run state transition")
            db.execute("UPDATE runs SET status=? WHERE id=?", (target, run_id))
            self.event_db(db, "USER_ACTION", {"status": target}, run_id)

    def begin_reconcile(self, run_id):
        with self.transaction() as db:
            run = self.decode_run(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
            if run["status"] not in {"FAILED", "INTERRUPTED"}:
                raise ValueError("invalid run state transition")
            for instrument_id in run["setup"]["devices"].values():
                row = db.execute("SELECT lock_run FROM instruments WHERE id=?", (instrument_id,)).fetchone()
                if not row or row["lock_run"] not in {None, run_id}:
                    raise ValueError("reconciliation device is reserved by another run")
            for instrument_id in run["setup"]["devices"].values():
                db.execute("UPDATE instruments SET lock_run=? WHERE id=?", (run_id, instrument_id))
            db.execute("UPDATE runs SET status='RECONCILING' WHERE id=?", (run_id,))
            self.event_db(db, "USER_ACTION", {"status": "RECONCILING"}, run_id)

    def recover(self):
        with self.transaction() as db:
            db.execute("UPDATE runs SET status='INTERRUPTED',error='central restarted; reconcile before reuse' WHERE status IN ('RUNNING','PAUSING','PAUSED','STOPPING','RECONCILING')")
            db.execute("UPDATE commands SET state='CANCELLED' WHERE state='QUEUED'")
            db.execute("UPDATE commands SET state='UNKNOWN',result=? WHERE state='DISPATCHED'",
                       (json.dumps({"error": "central restarted; dispatch outcome unknown"}),))
            self.event_db(db, "CENTRAL_RECOVERY", {})

    @staticmethod
    def decode_command(row):
        if not row:
            raise KeyError("command not found")
        result = dict(row)
        for name in ("parameters", "result"):
            result[name] = json.loads(result[name])
        return result

    def new_command(self, run_id, key, instrument_id, op, parameters):
        unique_key = f"{run_id}:{key}"
        encoded = json_bytes(parameters).decode()
        with self.transaction() as db:
            row = db.execute("SELECT * FROM commands WHERE unique_key=?", (unique_key,)).fetchone()
            if row:
                if (row["instrument_id"], row["op"], row["parameters"]) != (instrument_id, op, encoded):
                    raise ValueError("command key has different payload")
                return self.decode_command(row)
            instrument = db.execute("SELECT * FROM instruments WHERE id=?", (instrument_id,)).fetchone()
            if not instrument:
                raise ValueError("unknown instrument")
            if instrument["lock_run"] != run_id:
                raise ValueError("command resource ownership mismatch")
            command_id = "cmd_" + uuid.uuid4().hex
            db.execute("""INSERT INTO commands(id,unique_key,agent_id,instrument_id,run_id,op,parameters,state,created)
            VALUES(?,?,?,?,?,?,?,'QUEUED',?)""", (command_id, unique_key, instrument["agent_id"],
                                                 instrument_id, run_id, op, encoded, time.time()))
            self.event_db(db, "COMMAND_QUEUED", {"command_id": command_id, "op": op,
                                                "instrument_id": instrument_id}, run_id)
        return self.command(command_id)

    def command(self, command_id):
        with self.transaction() as db:
            return self.decode_command(db.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone())

    def claim(self, agent_id, boot_id):
        with self.transaction() as db:
            self.session(db, agent_id, boot_id)
            row = db.execute("""SELECT * FROM commands WHERE agent_id=? AND state='QUEUED'
            ORDER BY CASE WHEN op='safe_shutdown' THEN 0 ELSE 1 END,created LIMIT 1""", (agent_id,)).fetchone()
            if not row:
                return None
            db.execute("UPDATE commands SET state='DISPATCHED',boot_id=?,dispatched=? WHERE id=?",
                       (boot_id, time.time(), row["id"]))
            result = self.decode_command(row)
            result.update(state="DISPATCHED", boot_id=boot_id)
            self.event_db(db, "COMMAND_DISPATCHED", {"command_id": row["id"]}, row["run_id"])
            return result

    def complete_command(self, agent_id, boot_id, command_id, state, result):
        if state not in {"COMPLETED", "FAILED", "UNKNOWN"}:
            raise ValueError("invalid terminal command state")
        encoded = json_bytes(result).decode()
        with self.transaction() as db:
            self.session(db, agent_id, boot_id)
            row = db.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
            if not row or row["agent_id"] != agent_id:
                raise ValueError("command ownership mismatch")
            if row["state"] in {"COMPLETED", "FAILED"}:
                if row["state"] != state or row["result"] != encoded:
                    raise ValueError("different duplicate command result")
                return
            if row["state"] not in {"DISPATCHED", "UNKNOWN"}:
                raise ValueError("command was not dispatched")
            # A new session may report a saved old result, but it cannot claim an old action.
            db.execute("UPDATE commands SET state=?,result=? WHERE id=?", (state, encoded, command_id))
            self.event_db(db, "COMMAND_RESULT", {"command_id": command_id, "state": state}, row["run_id"])

    def timeout_command(self, command_id):
        with self.transaction() as db:
            db.execute("UPDATE commands SET state=CASE WHEN state='QUEUED' THEN 'CANCELLED' ELSE 'UNKNOWN' END,result=? WHERE id=? AND state IN ('QUEUED','DISPATCHED')",
                       (json.dumps({"error": "command deadline exceeded; no automatic retry"}), command_id))

    def cancel_queued(self, run_id):
        with self.transaction() as db:
            db.execute("UPDATE commands SET state='CANCELLED' WHERE run_id=? AND state='QUEUED' AND op!='safe_shutdown'", (run_id,))

    def cancelled_runs(self, agent_id):
        with self.transaction() as db:
            return [r[0] for r in db.execute("""SELECT DISTINCT runs.id FROM runs JOIN commands
            ON runs.id=commands.run_id WHERE commands.agent_id=?
            AND runs.status IN ('STOPPING','INTERRUPTED','FAILED','ABORTED','RECONCILING')""", (agent_id,))]

    def accept_artifact(self, agent_id, content, sha):
        if len(content) > 2_000_000 or hashlib.sha256(content).hexdigest() != sha:
            raise ValueError("artifact size/hash mismatch")
        measurement = Measurement.model_validate_json(content)
        command = self.command(measurement.command_id)
        if (command["agent_id"] != agent_id or measurement.agent_id != agent_id
                or measurement.instrument_id != command["instrument_id"]):
            raise ValueError("artifact ownership mismatch")
        if (command["op"] != "acquire_and_store" or command["state"] in {"QUEUED", "CANCELLED"}
                or measurement.experiment_id != command["run_id"]):
            raise ValueError("artifact does not belong to a dispatched acquisition")
        with self.transaction() as db:
            spec = json.loads(db.execute("SELECT spec FROM instruments WHERE id=?",
                                         (measurement.instrument_id,)).fetchone()[0])
        expected_provenance = command["parameters"].get("provenance", {})
        expected_workflow = "polarization-0.2.0" if expected_provenance else "polarization-0.1.0"
        if (measurement.simulated is not True or measurement.driver_version != spec["driver_version"]
                or measurement.workflow_version != expected_workflow):
            raise ValueError("artifact mode/driver/workflow is not approved")
        if (measurement.provenance != expected_provenance
                or (expected_provenance and expected_provenance != self.provenance(command["run_id"]))):
            raise ValueError("artifact provenance disagrees with immutable plan/configuration")
        for field in ("point_index", "sample_id", "wavelength_nm", "angle_deg", "exposure_ms",
                      "power_percent", "readbacks"):
            if getattr(measurement, field) != command["parameters"].get(field):
                raise ValueError(f"artifact {field} disagrees with acquisition")
        run = self.run(command["run_id"])
        # Historical evidence must not be re-admitted against a newer Plan schema.
        quality = assess(measurement, QualityPolicy.model_validate(run["plan"].get("quality", {})),
                         run["preflight"].get("instruments", {}).get("spectrometer", {}).get("spec", spec)
                         .get("detector_max_counts"))
        with self.transaction() as db:
            row = db.execute("SELECT sha FROM measurements WHERE id=?", (measurement.measurement_id,)).fetchone()
            if row:
                if row["sha"] != sha:
                    raise ValueError("different duplicate artifact")
                return measurement.measurement_id
            atomic_write(self.root / "raw" / f"{measurement.measurement_id}.json", content)
            db.execute("INSERT INTO measurements(id,run_id,point_index,sha,body) VALUES(?,?,?,?,?)",
                       (measurement.measurement_id, measurement.experiment_id, measurement.point_index,
                        sha, measurement.model_dump_json()))
            db.execute("INSERT INTO qualifications(measurement_id,status,body) VALUES(?,?,?)",
                       (measurement.measurement_id, quality["status"], json_bytes(quality).decode()))
            db.execute("""UPDATE runs SET points=(SELECT COUNT(*) FROM measurements m
                       JOIN qualifications q ON m.id=q.measurement_id WHERE m.run_id=?
                       AND q.status='accepted') WHERE id=?""",
                       (measurement.experiment_id, measurement.experiment_id))
            self.event_db(db, "DATA_SYNCHRONIZED", {"measurement_id": measurement.measurement_id,
                                                   "sha256": sha, "quality": quality}, measurement.experiment_id)
        return measurement.measurement_id

    def measurements(self, run_id, qualified_only=False):
        with self.transaction() as db:
            return [json.loads(r[0]) for r in db.execute(
                """SELECT m.body FROM measurements m LEFT JOIN qualifications q ON m.id=q.measurement_id
                   WHERE m.run_id=? AND (?=0 OR q.status='accepted') ORDER BY m.point_index""",
                (run_id, int(qualified_only)))]

    def qualification(self, measurement_id):
        with self.transaction() as db:
            row = db.execute("SELECT body FROM qualifications WHERE measurement_id=?", (measurement_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def export_snapshot(self, run_id):
        with self.transaction() as db:
            run = self.decode_run(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
            rows = db.execute("""SELECT m.body,m.sha,q.body AS quality FROM measurements m
                LEFT JOIN qualifications q ON m.id=q.measurement_id
                WHERE m.run_id=? ORDER BY m.point_index""", (run_id,)).fetchall()
            return run, [{"measurement": json.loads(r["body"]), "sha256": r["sha"],
                          "quality": json.loads(r["quality"]) if r["quality"] else UNASSESSED}
                         for r in rows]

    def artifact_sha(self, measurement_id):
        with self.transaction() as db:
            return db.execute("SELECT sha FROM measurements WHERE id=?", (measurement_id,)).fetchone()[0]

    def measurement_summary(self, run_id):
        summary = {"accepted": 0, "rejected": 0, "unassessed": 0, "total": 0}
        with self.transaction() as db:
            rows = db.execute("""SELECT COALESCE(q.status,'unassessed'),COUNT(*) FROM measurements m
                LEFT JOIN qualifications q ON m.id=q.measurement_id WHERE m.run_id=?
                GROUP BY COALESCE(q.status,'unassessed')""", (run_id,)).fetchall()
        for status, count in rows:
            summary[status] = count
            summary["total"] += count
        return summary

    def evidence_citations(self, ids):
        if not ids:
            return []
        with self.transaction() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='evidence'").fetchone():
                raise ValueError("plan references unknown evidence")
            citations = []
            for record_id in dict.fromkeys(ids):
                row = db.execute("SELECT * FROM evidence WHERE id=?", (record_id,)).fetchone()
                if not row:
                    raise ValueError("plan references unknown evidence")
                doc = json.loads(row["body"])
                latest = db.execute("SELECT MAX(version) FROM evidence WHERE source=?", (row["source"],)).fetchone()[0]
                if not doc["reviewed"] or latest != row["version"]:
                    raise ValueError("plan evidence must be reviewed and current; retrieve it again")
                citations.append({k: row[k] for k in ("id", "sha256", "source", "version")})
        return citations

    def save_review(self, run_id, body):
        self.run(run_id)
        if body.get("run_id") != run_id:
            raise ValueError("review run identity mismatch")
        encoded = json_bytes(body).decode()
        sha = hashlib.sha256(encoded.encode()).hexdigest()
        record_id = "review_" + sha
        with self.transaction() as db:
            row = db.execute("SELECT * FROM reviews WHERE id=?", (record_id,)).fetchone()
            if not row:
                version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM reviews WHERE run_id=?",
                                     (run_id,)).fetchone()[0]
                db.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?)",
                           (record_id, run_id, version, sha, time.time(), encoded))
                self.event_db(db, "RUN_REVIEW_CREATED", {"id": record_id, "sha256": sha}, run_id)
                row = db.execute("SELECT * FROM reviews WHERE id=?", (record_id,)).fetchone()
        return {**dict(row), "body": json.loads(row["body"])}

    def reviews(self, run_id):
        with self.transaction() as db:
            rows = db.execute("SELECT * FROM reviews WHERE run_id=? ORDER BY version DESC", (run_id,)).fetchall()
            return [{**dict(r), "body": json.loads(r["body"])} for r in rows]

    def latest_review(self, run_id):
        rows = self.reviews(run_id)
        return rows[0] if rows else None

    def events(self, run_id=None):
        with self.transaction() as db:
            rows = db.execute("SELECT * FROM events WHERE (? IS NULL OR run_id=?) ORDER BY sequence DESC LIMIT 200",
                              (run_id, run_id)).fetchall()
            return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]
