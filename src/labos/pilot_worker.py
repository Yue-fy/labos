"""Opt-in deterministic physical pilot correspondence, separate from model workers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
import yaml
from pydantic import Field

from .cooperation_worker import PROTOCOL, Task, Worker, delivery_failure_answer, evidence_delivery_blocked
from .sqlite_state import owned_connection
from .files import InstanceLock, atomic_write, contains_credential, json_bytes
from .models import Identifier, Model
from .pilot import PilotApproval, PilotEngine, PilotPlan
from .pilot_events import EventJournal
from .pilot_authority import Scope, config_fingerprint


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
    experiment_scope: Scope


class PilotWorker(Worker):
    deterministic = True

    def __init__(self, config, transport=None, adapter_factory=None):
        config = PilotWorkerConfig.model_validate(config.model_dump(mode="json"))
        self.launch_id = os.environ.get("LABOS_PILOT_LAUNCH_ID")
        if self.launch_id is not None and not re.fullmatch(r"[0-9a-f]{32}", self.launch_id):
            raise ValueError("pilot launch ID must be exactly 32 lowercase hexadecimal characters")
        self.instance_id = uuid.uuid4().hex
        self._execution_snapshot = config.model_dump_json()
        self.config_sha256 = config_fingerprint(config)
        self._authority_ready = False
        self._authority_checked_at_utc = None
        self._phase = "ready"
        self._status_lock = threading.RLock()
        self._failure_class = None
        self._exit_status = None
        self._journal_failures = 0
        self._status_failures = 0
        self._last_stage = None
        self.events = EventJournal(config.state_dir)
        existing = config.state_dir / "correspondence.sqlite"
        if existing.exists():
            try:
                with owned_connection(existing, timeout=10) as db:
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
            db.execute("CREATE TABLE IF NOT EXISTS authority_attempts (task_id TEXT PRIMARY KEY, nonce TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS physical_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            # A committed intent with no finished result may already have operated outputs.
            # Restart does not constitute physical reconciliation.
            unresolved = db.execute("SELECT task_id FROM executions WHERE state='intent' LIMIT 1").fetchone()
            if unresolved:
                self._latch(db, unresolved["task_id"])

    def physical_db(self):
        return owned_connection(self.execution_database, timeout=10, rows=True)

    @staticmethod
    def _latch(db, task_id):
        db.execute("INSERT OR IGNORE INTO physical_state VALUES('unresolved',?)", (task_id,))

    def _blocked(self, db):
        return db.execute("SELECT value FROM physical_state WHERE key='unresolved'").fetchone()

    @staticmethod
    def _not_executed():
        return {"backend": "pilot", "answer": {
            "status": "needs_input",
            "summary": "Physical authority did not authorize this invocation; no adapter was constructed.",
            "findings": [], "questions": ["Review central authority and local physical history before further operation."]}}

    def respond(self, message, context):
        metadata = Task.model_validate(message["body"])
        plan = PilotPlan.model_validate(metadata.pilot_plan)
        plan_hash = hashlib.sha256(json_bytes(plan.model_dump(mode="json"))).hexdigest()
        # Deserialize a private validated snapshot; caller mutations cannot change execution.
        execution = PilotWorkerConfig.model_validate_json(self._execution_snapshot)
        config_hash = self.config_sha256
        with self.physical_db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM executions WHERE task_id=?", (metadata.task_id,)).fetchone()
            if previous:
                if previous["message_id"] != message["id"] or previous["plan_sha256"] != plan_hash:
                    raise ValueError("physical task identity must not be reused")
                if previous["result_json"] is not None:
                    return json.loads(previous["result_json"])
                self._latch(db, metadata.task_id)
                return self._not_executed()
            if self._blocked(db):
                return self._not_executed()
        task = PilotTask.model_validate(message["body"])
        try:
            if execution.approval is None:
                raise ValueError("physical pilot requires local commissioning and approval")
            execution.approval.validate_plan(task.pilot_plan)
            self._validate_local_profile(execution)
            scope = execution.adapter_config.get("experiment_scope", "optical_transport")
            if scope != task.experiment_scope:
                raise ValueError("Task differs from the locally commissioned experiment scope.")
            if (scope == "dark_a") != (task.pilot_plan.mode == "dark_a"):
                raise ValueError("Task mode differs from the locally commissioned experiment scope.")
            if scope == "optical_readback" and task.pilot_plan.mode != "photoresponse":
                raise ValueError("Optical readback supports only the finite OFF/ON photoresponse plan.")
        except ValueError as exc:
            return {"backend": "pilot", "answer": {
                "status": "needs_input", "summary": str(exc), "findings": [],
                "questions": ["Commission and authorize the fixed physical profile locally."]}}
        nonce = uuid.uuid4().hex
        with self.physical_db() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("SELECT task_id FROM executions WHERE state='intent' LIMIT 1").fetchone()
            if self._blocked(db) or active:
                if active:
                    self._latch(db, active["task_id"])
                return self._not_executed()
            # Commit both intent and nonce before the request and any adapter construction.
            db.execute("INSERT INTO executions VALUES(?,?,?,?, 'intent',NULL)",
                       (task.task_id, message["id"], plan_hash, config_hash))
            db.execute("INSERT INTO authority_attempts VALUES(?,?)", (task.task_id, nonce))
        self._authority_ready = False
        request = {"message_id": message["id"], "task_id": task.task_id,
                   "plan_sha256": plan_hash, "config_sha256": config_hash,
                   "experiment_scope": scope, "attempt_nonce": nonce}
        definitive = False
        try:
            response = self.client.post(f"/api/agents/{execution.agent_id}/pilot-claims", json=request)
            response.raise_for_status()
            receipt = response.json()
            definitive = (isinstance(receipt, dict) and receipt.get("granted") is False)
            valid = receipt == {"granted": True, "agent_id": execution.agent_id, **request}
            # JSON booleans are required: integer 1 must not masquerade as True.
            valid = valid and receipt.get("granted") is True
        except (httpx.HTTPError, ValueError):
            valid = False
        if not valid:
            result = self._not_executed()
            with self.physical_db() as db:
                if not definitive:
                    self._latch(db, task.task_id)
                db.execute("UPDATE executions SET state=?,result_json=? WHERE task_id=?",
                           ('denied' if definitive else 'intent', json.dumps(result), task.task_id))
            return result
        done = threading.Event()
        watcher = threading.Thread(target=self._watch_stop, args=(done,), daemon=True)
        watcher.start()
        self._event("begin", scope="execution")
        try:
            factory = self.adapter_factory or _default_adapter_factory
            adapter = factory(execution.adapter_config)
            report = PilotEngine(adapter, observer=self._observe_engine).run(
                task.pilot_plan, execution.approval, cancel=self._cancel)
            if not isinstance(report, dict) or report.get("status") not in {"COMPLETED", "FAILED", "CANCELLED", "UNKNOWN"}:
                raise ValueError("invalid physical engine result")
            json_bytes(report)
            failure = report.get("failure")
            if isinstance(failure, dict) and failure.get("exception_type"):
                self._event("failure", scope="execution", failure_class=failure["exception_type"])
        except Exception as exc:
            self._event("failure", scope="execution", failure_class=type(exc).__name__)
            report = self._unknown("Physical execution did not return a verifiable result.")
        except BaseException as exc:
            self._event("failure", scope="execution", failure_class=type(exc).__name__)
            raise
        finally:
            done.set()
            watcher.join(timeout=0.2)
            self._event("end", scope="execution")
        return self._finish(message, task, plan_hash, config_hash, report, nonce)

    @staticmethod
    def _unknown(error):
        return {"status": "UNKNOWN", "samples": [], "cleanup": [], "error": error,
                "acquisition_complete": False, "protection_verified": False}

    def _finish(self, message, task, plan_hash, config_hash, report, nonce):
        report = {**report, "task_id": task.task_id,
                  "plan": task.pilot_plan.model_dump(mode="json"),
                  "config_sha256": config_hash, "adapter_id": self.config.adapter_id,
                  "experiment_scope": task.experiment_scope}
        if report["status"] == "UNKNOWN":
            with self.physical_db() as db:
                self._latch(db, task.task_id)
        content = json_bytes({"message_id": message["id"], "plan_sha256": plan_hash,
                              "attempt_nonce": nonce, "report": report})
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
        from .pilot_artifacts import MAX_PILOT_ARTIFACT_BYTES
        if len(content) > MAX_PILOT_ARTIFACT_BYTES:
            generated["pilot_result"] = evidence_delivery_blocked(
                details, "raw_artifact_exceeds_capacity", raw_bytes=len(content),
                max_raw_bytes=MAX_PILOT_ARTIFACT_BYTES)
            generated["answer"] = delivery_failure_answer()
        with self.physical_db() as db:
            db.execute("""INSERT INTO executions VALUES(?,?,?,?, 'finished',?)
                ON CONFLICT(task_id) DO UPDATE SET state='finished',result_json=excluded.result_json""",
                       (task.task_id, message["id"], plan_hash, config_hash, json.dumps(generated)))
        return generated

    def request_stop(self):
        """Signal cooperative cancellation; this cannot interrupt blocking vendor I/O."""
        self._cancel.set()
        if self._phase not in {"stopped", "failed"}:
            self._safe_status("stopping")

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
        metadata = Task.model_validate(body)
        plan = PilotPlan.model_validate(metadata.pilot_plan)
        if len(json_bytes(metadata.context)) > 16384:
            raise ValueError("task context exceeds 16 KiB")
        with self.physical_db() as db:
            previous = db.execute("SELECT * FROM executions WHERE task_id=?", (metadata.task_id,)).fetchone()
        if previous and (previous["message_id"] != message["id"] or previous["plan_sha256"] != hashlib.sha256(json_bytes(plan.model_dump(mode="json"))).hexdigest()):
            raise ValueError("physical task identity must not be reused")
        if previous is None:
            PilotTask.model_validate(body)
        return True

    @staticmethod
    def _utc_now():
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _identity(self):
        return {"instance_id": self.instance_id, "config_sha256": self.config_sha256,
                **({"launch_id": self.launch_id} if self.launch_id is not None else {})}

    def _event(self, event, **fields):
        # Only structural fields are accepted here. In particular, never stringify
        # an exception, task, config, raw report, or vendor diagnostic for logging.
        try:
            record = {"event": event, "updated_at_utc": self._utc_now(),
                      **self._identity(), **fields}
            if contains_credential(record, self.credentials):
                record = {"event": "redacted", "updated_at_utc": self._utc_now(), **self._identity()}
                if contains_credential(record, self.credentials):
                    return
            self.events.append(record)
        except BaseException:
            # Even an interrupt raised by telemetry cannot skip protection/close.
            self._journal_failures += 1

    def _observe_engine(self, record):
        self._last_stage = {key: record.get(key) for key in
                            ("stage", "phase", "started_elapsed_s", "duration_s", "outcome")}
        self._event("progress", scope="execution", **self._last_stage)
        self._safe_status("executing")

    def _safe_status(self, phase):
        try:
            self.write_status(phase)
        except BaseException:
            # Status persistence is observation, never a prerequisite for cleanup.
            pass

    def status(self):
        with self.physical_db() as db:
            blocked = bool(self._blocked(db))
            active = db.execute("SELECT 1 FROM executions WHERE state='intent' LIMIT 1").fetchone() is not None
        execution = PilotWorkerConfig.model_validate_json(self._execution_snapshot)
        configured = bool(execution.approval and execution.approval.enabled)
        running = self._phase in {"started", "listening", "network_unavailable", "executing"}
        return {**super().status(), **self._identity(), "phase": self._phase,
                "configured_approval_enabled": configured,
                "profile_validated": self._profile_validated,
                "profile_ready": configured and self._profile_validated,
                "physical_blocked": blocked, "active_intent": active,
                "authority_ready": self._authority_ready and not blocked and not active,
                "authority_checked_at_utc": self._authority_checked_at_utc,
                "physical_enabled": bool(running and configured and self._profile_validated
                                         and self._authority_ready and not blocked and not active
                                         and not self._cancel.is_set()),
                "hardware_access": "possible_when_commissioned" if configured else False,
                "cancel_requested": self._cancel.is_set(),
                "snapshot_only": True, "process_liveness": "unknown",
                "instrument_output_state": "unknown", "updated_at_utc": self._utc_now(),
                "failure_class": self._failure_class, "exit_status": self._exit_status,
                "last_engine_stage": self._last_stage, "journal_failures": self._journal_failures,
                "status_failures": self._status_failures}

    def write_status(self, phase):
        with self._status_lock:
            if self._phase in {"stopped", "failed"} and phase not in {"stopped", "failed"}:
                # A delayed stop watcher/observer may outlive the ownership scope.
                # It must not replace this terminal snapshot or a successor's.
                return self.status()
            if self._cancel.is_set() and phase in {"started", "listening", "network_unavailable", "executing"}:
                phase = "stopping"
            self._phase = phase
            event = "begin" if phase == "started" else "end" if phase in {"stopped", "failed"} else "progress"
            if phase in {"started", "stopping", "stopped", "failed"}:
                self._event(event, scope="worker", phase=phase, failure_class=self._failure_class,
                            exit_status=self._exit_status)
            status = self.status()
            try:
                atomic_write(self.config.state_dir / "status.json", json_bytes(status))
            except BaseException as exc:
                self._status_failures += 1
                status["status_failures"] = self._status_failures
                self._event("failure", scope="status", failure_class=type(exc).__name__)
            return status

    def prepare_delivery(self, response):
        details = response["body"].get("pilot_result")
        if not details:
            return
        delivery = details.get("evidence_delivery", {})
        if (details.get("artifact", {}).get("availability") in {"local_only", "unknown", "central_indexed"}
                and delivery.get("status") == "blocked"):
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
        from .pilot_artifacts import MAX_PILOT_ARTIFACT_BYTES
        if len(content) > MAX_PILOT_ARTIFACT_BYTES:
            response["body"]["pilot_result"] = evidence_delivery_blocked(
                details, "raw_artifact_exceeds_capacity", raw_bytes=len(content),
                max_raw_bytes=MAX_PILOT_ARTIFACT_BYTES)
            response["body"]["answer"] = delivery_failure_answer()
            return
        upload = self.client.post(f"/api/agents/{self.config.agent_id}/pilot-artifacts",
                                  content=content, headers={"Content-Type": "application/json",
                                                            "X-SHA256": details["artifact"]["sha256"]})
        if upload.status_code == 413:
            response["body"]["pilot_result"] = evidence_delivery_blocked(
                details, "remote_capacity_refusal", raw_bytes=len(content), http_status=413)
            # An earlier upload may have been indexed before its receipt was lost.
            response["body"]["pilot_result"]["artifact"]["availability"] = "unknown"
            response["body"]["answer"] = delivery_failure_answer()
            return
        upload.raise_for_status()
        try:
            receipt = upload.json()
        except ValueError as exc:
            raise httpx.RequestError("Central returned an invalid pilot artifact receipt") from exc
        if (not isinstance(receipt, dict) or receipt.get("accepted") is not True
                or receipt.get("sha256") != details["artifact"]["sha256"]
                or receipt.get("message_id") != response["in_reply_to"]):
            raise httpx.RequestError("Central did not acknowledge the pilot artifact")

    def _validate_local_profile(self, execution=None):
        execution = execution or PilotWorkerConfig.model_validate_json(self._execution_snapshot)
        if self.adapter_factory is None:
            self._profile_validated = False
            try:
                from .cryostat_pilot import validate_adapter_config
                validate_adapter_config(execution.adapter_config)
            except (ImportError, ValueError) as exc:
                raise ValueError("Local commissioning configuration is incomplete or invalid.") from exc
            self._profile_validated = True

    def tick(self):
        # Readiness is an observation at a poll boundary, never an execution grant.
        # Keep polling and finished-result delivery available even when not ready.
        self._refresh_authority_readiness()
        return super().tick()

    def _refresh_authority_readiness(self, *, require_valid_profile=False):
        # Never perform HTTP from status writers or engine observer callbacks.
        self._authority_ready = False
        execution = PilotWorkerConfig.model_validate_json(self._execution_snapshot)
        enabled = bool(execution.approval and execution.approval.enabled)
        if enabled:
            try:
                self._validate_local_profile(execution)
            except ValueError:
                if require_valid_profile:
                    raise
        authority = None
        try:
            response = self.client.get(f"/api/agents/{execution.agent_id}/pilot-claims")
            response.raise_for_status()
            authority = response.json()
        except (httpx.HTTPError, ValueError):
            pass
        self._authority_checked_at_utc = self._utc_now()
        with self.physical_db() as db:
            blocked = bool(self._blocked(db))
            active = db.execute("SELECT 1 FROM executions WHERE state='intent' LIMIT 1").fetchone() is not None
        self._authority_ready = bool(
            isinstance(authority, dict) and authority.get("commissioned") is True
            and authority.get("blocked") is False
            and authority.get("config_sha256") == self.config_sha256
            and authority.get("experiment_scope") == execution.adapter_config.get("experiment_scope", "optical_transport")
            and not blocked and not active and enabled and self._profile_validated)
        return {"authority_ready": self._authority_ready,
                "authority_checked_at_utc": self._authority_checked_at_utc,
                "physical_blocked": blocked, "active_intent": active,
                "config_sha256": self.config_sha256,
                "hardware_access": "possible_when_commissioned" if enabled else False,
                "instrument_access_performed": False,
                "model_inference_performed": False,
                "configured_approval_enabled": enabled,
                "profile_validated": self._profile_validated,
                "profile_ready": enabled and self._profile_validated,
                "physical_enabled": False, "phase": "ready",
                "instrument_output_state": "unknown"}

    def doctor(self):
        response = self.client.get("/health")
        response.raise_for_status()
        if response.json().get("service") != "labos-central":
            raise ValueError("destination is not LabOS central")
        self.client.get(self.path, params={"limit": 1}).raise_for_status()
        return {**self._refresh_authority_readiness(require_valid_profile=True),
                "authenticated_correspondence": True}


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
    close_attempted = False
    try:
        config = load_pilot_worker_config(args.config)
        stop = config.state_dir / "stop.request"
        if args.action == "status":
            snapshot = json.loads((config.state_dir / "status.json").read_text(encoding="utf-8"))
            snapshot.update(snapshot_only=True, process_liveness="unknown", readiness_uncertain=True,
                            physical_enabled=False, instrument_output_state="unknown")
            print(json.dumps(snapshot, indent=2))
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
            # Terminal persistence belongs to this ownership interval. An older
            # process must never overwrite a replacement worker after unlocking.
            phase, exit_status = "failed", 1
            try:
                stop.unlink(missing_ok=True)
                worker._refresh_authority_readiness()
                worker.write_status("started")
                if args.action == "once":
                    print(json.dumps(worker.tick(), indent=2))
                else:
                    while not stop.exists() and not worker._cancel.is_set():
                        worker.tick()
                        for _ in range(max(1, int(config.poll_s * 5))):
                            if stop.exists() or worker._cancel.wait(0.2):
                                break
                phase, exit_status = "stopped", 0
            except KeyboardInterrupt:
                worker._failure_class = "KeyboardInterrupt"
                worker.request_stop()
                phase, exit_status = "stopped", 130
            except BaseException as exc:
                worker._failure_class = type(exc).__name__
                worker._event("failure", scope="worker", failure_class=worker._failure_class)
                raise
            finally:
                try:
                    close_attempted = True
                    worker.client.close()
                except BaseException as exc:
                    worker._event("failure", scope="client_close", failure_class=type(exc).__name__)
                    if worker._failure_class is None:
                        worker._failure_class = type(exc).__name__
                        if isinstance(exc, KeyboardInterrupt):
                            worker.request_stop()
                            phase, exit_status = "stopped", 130
                        else:
                            phase, exit_status = "failed", 1
                        raise
                    # An earlier worker fault remains primary, including its exit
                    # code. The secondary close fault is retained in the journal.
                finally:
                    worker._exit_status = exit_status
                    worker._safe_status(phase)
            return exit_status
    except KeyboardInterrupt:
        if worker:
            worker.request_stop()
        return 130
    except Exception as exc:
        print(f"LabOS physical pilot worker failed ({type(exc).__name__}). Check the local profile, durable state and HTTPS connectivity.")
        return 1
    finally:
        if worker and not close_attempted and not worker.client.is_closed:
            worker.client.close()


if __name__ == "__main__":
    raise SystemExit(main())
