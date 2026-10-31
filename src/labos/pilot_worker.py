"""Opt-in deterministic physical pilot correspondence, separate from model workers."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Literal

import httpx
import yaml
from pydantic import Field

from .cooperation_worker import PROTOCOL, Worker
from .files import InstanceLock, atomic_write, contains_credential, json_bytes
from .models import Identifier, Model
from .pilot import PilotApproval, PilotEngine, PilotPlan


class PilotWorkerConfig(Model):
    role: Literal["pc"] = "pc"
    agent_id: Identifier
    connection_config: Path
    state_dir: Path = Path("data/physical-pilot")
    start_after: int = Field(default=0, ge=0)
    poll_s: float = Field(default=10, ge=1, le=300)
    backend: Literal["pilot"] = "pilot"
    adapter_id: Literal["cryostat_v1"] = "cryostat_v1"
    adapter_config: dict = Field(default_factory=dict)
    approval: PilotApproval | None = None

    @property
    def context_files(self):
        return ()

    @property
    def source_roots(self):
        return {}


def load_pilot_worker_config(path):
    path = Path(path).resolve()
    text = path.read_text(encoding="utf-8-sig")
    try:
        values = json.loads(text)
    except json.JSONDecodeError:
        values = yaml.safe_load(text)
    config = PilotWorkerConfig.model_validate(values)
    for name in ("connection_config", "state_dir"):
        value = getattr(config, name)
        setattr(config, name, value if value.is_absolute() else path.parent / value)
    return config


class PilotTask(Model):
    protocol: Literal["labos-agent-v1"]
    document_type: Literal["labos_pilot_task"]
    task_id: Identifier
    instruction: str = Field(min_length=1, max_length=8000)
    context: dict = Field(default_factory=dict)
    executable: Literal[False] = False
    pilot_plan: PilotPlan


class PilotWorker(Worker):
    def __init__(self, config, transport=None, adapter_factory=None):
        config = PilotWorkerConfig.model_validate(config.model_dump(mode="json"))
        existing = config.state_dir / "correspondence.sqlite"
        if existing.exists():
            try:
                with sqlite3.connect(existing, timeout=10) as db:
                    kind = db.execute("SELECT value FROM state WHERE key='worker_kind'").fetchone()
            except sqlite3.Error as exc:
                raise ValueError("physical pilot requires a separate state directory") from exc
            if kind != ("physical-pilot",):
                raise ValueError("physical pilot requires a separate state directory from the report worker")
        self.adapter_factory = adapter_factory
        self._profile_validated = adapter_factory is not None
        self._cancel = threading.Event()
        super().__init__(config, transport, responder=self)
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO state VALUES('worker_kind','physical-pilot')")
        self.execution_database = config.state_dir / "physical.sqlite"
        with self.physical_db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS executions (
                task_id TEXT PRIMARY KEY, message_id TEXT UNIQUE NOT NULL,
                plan_sha256 TEXT NOT NULL, config_sha256 TEXT NOT NULL,
                state TEXT NOT NULL, result_json TEXT)""")
            db.execute("CREATE TABLE IF NOT EXISTS physical_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            # A committed intent with no finished result may already have operated outputs.
            # Restart does not constitute physical reconciliation.
            unresolved = db.execute("SELECT task_id FROM executions WHERE state='intent' LIMIT 1").fetchone()
            if unresolved:
                self._latch(db, unresolved["task_id"])

    def physical_db(self):
        db = sqlite3.connect(self.execution_database, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _latch(db, task_id):
        db.execute("INSERT OR IGNORE INTO physical_state VALUES('unresolved',?)", (task_id,))

    def _blocked(self, db):
        return db.execute("SELECT value FROM physical_state WHERE key='unresolved'").fetchone()

    def respond(self, message, context):
        task = PilotTask.model_validate(message["body"])
        plan = task.pilot_plan.model_dump(mode="json")
        plan_hash = hashlib.sha256(json_bytes(plan)).hexdigest()
        config_hash = hashlib.sha256(json_bytes(self.config.model_dump(mode="json"))).hexdigest()
        with self.physical_db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM executions WHERE task_id=?", (task.task_id,)).fetchone()
            if previous:
                if previous["message_id"] != message["id"] or previous["plan_sha256"] != plan_hash:
                    raise ValueError("physical task identity must not be reused")
                if previous["state"] == "finished":
                    return json.loads(previous["result_json"])
                config_hash = previous["config_sha256"]
                self._latch(db, task.task_id)
                blocked = True
            else:
                blocked = bool(self._blocked(db))
        if blocked:
            report = self._unknown("A physical outcome is unresolved; actual local reconciliation is required.")
            return self._finish(message, task, plan_hash, config_hash, report)
        try:
            if self.config.approval is None:
                raise ValueError("physical pilot requires local commissioning and approval")
            self.config.approval.validate_plan(task.pilot_plan)
            self._validate_local_profile()
            scope = self.config.adapter_config.get("experiment_scope", "optical_transport")
            if (scope == "dark_a") != (task.pilot_plan.mode == "dark_a"):
                raise ValueError("Task mode differs from the locally commissioned experiment scope.")
        except ValueError as exc:
            return {"backend": "pilot", "answer": {
                "status": "needs_input", "summary": str(exc), "findings": [],
                "questions": ["Commission and authorize the fixed physical profile locally."]}}
        with self.physical_db() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("SELECT task_id FROM executions WHERE state='intent' LIMIT 1").fetchone()
            if self._blocked(db) or active:
                if active:
                    self._latch(db, active["task_id"])
                blocked = True
            else:
                # This transaction commits before constructing the adapter or invoking any I/O.
                db.execute("INSERT INTO executions VALUES(?,?,?,?, 'intent',NULL)",
                           (task.task_id, message["id"], plan_hash, config_hash))
                blocked = False
        if blocked:
            report = self._unknown("A physical outcome is unresolved; actual local reconciliation is required.")
        else:
            done = threading.Event()
            watcher = threading.Thread(target=self._watch_stop, args=(done,), daemon=True)
            watcher.start()
            try:
                factory = self.adapter_factory or _default_adapter_factory
                adapter = factory(self.config.adapter_config)
                report = PilotEngine(adapter).run(task.pilot_plan, self.config.approval, cancel=self._cancel)
                if not isinstance(report, dict) or report.get("status") not in {"COMPLETED", "FAILED", "CANCELLED", "UNKNOWN"}:
                    raise ValueError("invalid physical engine result")
                json_bytes(report)
            except Exception:
                # Adapter construction itself may perform partial I/O. Never infer a safe outcome.
                report = self._unknown("Physical execution did not return a verifiable result.")
            finally:
                done.set()
                watcher.join(timeout=0.2)
        return self._finish(message, task, plan_hash, config_hash, report)

    @staticmethod
    def _unknown(error):
        return {"status": "UNKNOWN", "samples": [], "cleanup": [], "error": error,
                "acquisition_complete": False, "protection_verified": False}

    def _finish(self, message, task, plan_hash, config_hash, report):
        report = {**report, "task_id": task.task_id,
                  "plan": task.pilot_plan.model_dump(mode="json"),
                  "config_sha256": config_hash, "adapter_id": self.config.adapter_id}
        if report["status"] == "UNKNOWN":
            with self.physical_db() as db:
                self._latch(db, task.task_id)
        content = json_bytes({"message_id": message["id"], "plan_sha256": plan_hash, "report": report})
        digest = hashlib.sha256(content).hexdigest()
        relative = Path("artifacts") / f"{task.task_id}_{digest[:16]}.json"
        atomic_write(self.config.state_dir / relative, content)
        error = report.get("error")
        public_error = str(error)[:512] if error else None
        if public_error and contains_credential(public_error, self.credentials):
            public_error = "Physical execution reported an error; inspect the private local raw report."
        details = {"status": report["status"],
                   "acquisition_complete": report["acquisition_complete"],
                   "protection_verified": report["protection_verified"],
                   "sample_count": len(report["samples"]), "error": public_error,
                   "plan_sha256": plan_hash, "config_sha256": config_hash,
                   "artifact": {"path": relative.as_posix(), "sha256": digest, "message_id": message["id"]}}
        completed = report["status"] == "COMPLETED"
        protected = report["protection_verified"] is True
        protection_finding = (
            "Independent cleanup verified laser OFF and minimum 4 mV RMS excitation. "
            "Minimum excitation is not OFF."
            if protected else
            "Outputs were not independently verified for this run; inspect the raw cleanup "
            "records and obtain local readbacks before further physical operation."
        )
        generated = {"backend": "pilot", "pilot_result": details, "answer": {
            "status": "completed" if completed else "failed",
            "summary": f"Physical pilot {report['status']}; {len(report['samples'])} raw samples preserved locally.",
            "findings": [protection_finding],
            "questions": ["Reconcile the physical state locally before any further run."]
            if report["status"] == "UNKNOWN" or not protected else []}}
        with self.physical_db() as db:
            db.execute("""INSERT INTO executions VALUES(?,?,?,?, 'finished',?)
                ON CONFLICT(task_id) DO UPDATE SET state='finished',result_json=excluded.result_json""",
                       (task.task_id, message["id"], plan_hash, config_hash, json.dumps(generated)))
        return generated

    def request_stop(self):
        """Signal cooperative cancellation; this cannot interrupt blocking vendor I/O."""
        self._cancel.set()

    def _watch_stop(self, done):
        while not done.is_set():
            if (self.config.state_dir / "stop.request").exists():
                self.request_stop()
                return
            done.wait(0.05)

    def eligible(self, message):
        body = message["body"]
        if body.get("protocol") != PROTOCOL or body.get("document_type") != "labos_pilot_task":
            return False
        task = PilotTask.model_validate(body)
        if len(json_bytes(task.context)) > 16384:
            raise ValueError("task context exceeds 16 KiB")
        with self.physical_db() as db:
            previous = db.execute("SELECT * FROM executions WHERE task_id=?", (task.task_id,)).fetchone()
        if previous and (previous["message_id"] != message["id"] or previous["plan_sha256"] != hashlib.sha256(json_bytes(task.pilot_plan.model_dump(mode="json"))).hexdigest()):
            raise ValueError("physical task identity must not be reused")
        return True

    def status(self):
        with self.physical_db() as db:
            blocked = bool(self._blocked(db))
        return {**super().status(), "physical_blocked": blocked,
                "physical_enabled": bool(self.config.approval and self.config.approval.enabled
                                         and self._profile_validated and not blocked),
                "hardware_access": "possible_when_commissioned" if self.config.approval and self.config.approval.enabled else False,
                "cancel_requested": self._cancel.is_set()}

    def prepare_delivery(self, response):
        details = response["body"].get("pilot_result")
        if not details:
            return
        try:
            relative = Path(details["artifact"]["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("invalid local artifact path")
            content = (self.config.state_dir / relative).read_bytes()
            if hashlib.sha256(content).hexdigest() != details["artifact"]["sha256"]:
                raise ValueError("local artifact hash differs")
            document = json.loads(content)
            self.check_credentials(document)
            if document["message_id"] != response["in_reply_to"]:
                raise ValueError("artifact does not match original task")
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise httpx.RequestError("Local pilot artifact cannot be delivered safely") from exc
        upload = self.client.post(f"/api/agents/{self.config.agent_id}/pilot-artifacts",
                                  content=content, headers={"Content-Type": "application/json",
                                                            "X-SHA256": details["artifact"]["sha256"]})
        upload.raise_for_status()
        try:
            receipt = upload.json()
        except ValueError as exc:
            raise httpx.RequestError("Central returned an invalid pilot artifact receipt") from exc
        if (not isinstance(receipt, dict) or receipt.get("accepted") is not True
                or receipt.get("sha256") != details["artifact"]["sha256"]
                or receipt.get("message_id") != response["in_reply_to"]):
            raise httpx.RequestError("Central did not acknowledge the pilot artifact")

    def _validate_local_profile(self):
        if self.adapter_factory is None:
            self._profile_validated = False
            try:
                from .cryostat_pilot import validate_adapter_config
                validate_adapter_config(self.config.adapter_config)
            except (ImportError, ValueError) as exc:
                raise ValueError("Local commissioning configuration is incomplete or invalid.") from exc
            self._profile_validated = True

    def doctor(self):
        response = self.client.get("/health")
        response.raise_for_status()
        if response.json().get("service") != "labos-central":
            raise ValueError("destination is not LabOS central")
        self.client.get(self.path, params={"limit": 1}).raise_for_status()
        enabled = bool(self.config.approval and self.config.approval.enabled)
        if enabled:
            self._validate_local_profile()
        return {"authenticated_correspondence": True,
                "hardware_access": "possible_when_commissioned" if enabled else False,
                "instrument_access_performed": False,
                "model_inference_performed": False,
                "physical_enabled": enabled and self._profile_validated}


def _default_adapter_factory(settings):
    # Import only after durable execution intent and local authorization. Doctor and
    # module import must never load vendor drivers or create instruments.
    from .cryostat_pilot import create_adapter
    return create_adapter(settings)


def main(argv=None):
    parser = argparse.ArgumentParser(description="LabOS finite physical pilot worker")
    parser.add_argument("action", choices=["run", "once", "doctor", "status", "stop"])
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    worker = None
    try:
        config = load_pilot_worker_config(args.config)
        stop = config.state_dir / "stop.request"
        if args.action == "status":
            print((config.state_dir / "status.json").read_text(encoding="utf-8"))
            return 0
        if args.action == "stop":
            atomic_write(stop, b"stop\n")
            print("Cooperative cancellation requested. Blocking device I/O must return before cleanup; this is not an emergency hardware stop.")
            return 0
        if args.action == "doctor":
            # Do not interpret an active process's committed intent as a crashed run.
            with InstanceLock(config.state_dir):
                worker = PilotWorker(config)
                print(json.dumps(worker.doctor(), indent=2))
            return 0
        with InstanceLock(config.state_dir):
            worker = PilotWorker(config)
            stop.unlink(missing_ok=True)
            if args.action == "once":
                print(json.dumps(worker.tick(), indent=2))
                return 0
            worker.write_status("started")
            while not stop.exists() and not worker._cancel.is_set():
                worker.tick()
                for _ in range(max(1, int(config.poll_s * 5))):
                    if stop.exists() or worker._cancel.wait(0.2):
                        break
            worker.write_status("stopped")
            return 0
    except KeyboardInterrupt:
        if worker:
            worker.request_stop()
        return 130
    except (OSError, ValueError, RuntimeError, sqlite3.Error, httpx.HTTPError) as exc:
        print(f"LabOS physical pilot worker failed ({type(exc).__name__}). Check the local profile, durable state and HTTPS connectivity.")
        return 1
    finally:
        if worker:
            worker.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
