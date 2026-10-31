"""Persistent, bounded assistant correspondence; separate from hardware execution."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import sqlite3
import ssl
import subprocess
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
import yaml
from pydantic import Field, model_validator

from .config import AgentConfig, CentralConfig, load_config
from .cooperation import MAX_MESSAGE_BYTES
from .cooperation_models import Answer, Responder
from .files import InstanceLock, atomic_write, contains_credential, json_bytes
from .models import Identifier, Model
from .source_context import ReadOnlySources, SourceContextError

PROTOCOL = "labos-agent-v1"


class WorkerConfig(Model):
    role: Literal["pc", "central"]
    agent_id: Identifier
    connection_config: Path
    state_dir: Path = Path("data/cooperation")
    start_after: int = Field(default=0, ge=0)
    poll_s: float = Field(default=10, ge=1, le=300)
    backend: Literal["codex", "local"] = "codex"
    codex_command: list[str] = Field(default_factory=lambda: ["codex"], min_length=1)
    codex_model: str | None = None
    model_timeout_s: float = Field(default=180, ge=5, le=600)
    local_url: str | None = None
    local_model: str | None = None
    context_files: list[Path] = Field(default_factory=list, max_length=12)
    source_roots: dict[Identifier, Path] = Field(default_factory=dict, max_length=8)

    @model_validator(mode="after")
    def endpoints(self):
        if self.backend == "local" and not self.local_url:
            raise ValueError("local backend requires local_url and local_model")
        if bool(self.local_url) != bool(self.local_model):
            raise ValueError("local_url and local_model must be configured together")
        if self.local_url:
            p = urlsplit(self.local_url)
            try:
                loopback = p.hostname == "localhost" or ipaddress.ip_address(p.hostname).is_loopback
            except ValueError:
                loopback = False
            if (not loopback or p.scheme not in {"http", "https"} or p.username or p.password
                    or p.query or p.fragment):
                raise ValueError("local model URL must be a loopback HTTP(S) endpoint")
            self.local_url = self.local_url.rstrip("/")
        return self


class Task(Model):
    protocol: Literal["labos-agent-v1"]
    document_type: Literal["labos_auto_task", "labos_program_task", "labos_pilot_task"]
    task_id: Identifier
    instruction: str = Field(min_length=1, max_length=8000)
    context: dict = Field(default_factory=dict)
    executable: Literal[False] = False
    program_id: Identifier | None = None
    parameters: dict = Field(default_factory=dict)
    pilot_plan: dict | None = None

    @model_validator(mode="after")
    def program_identity(self):
        if self.document_type == "labos_program_task" and not self.program_id:
            raise ValueError("program task requires program_id")
        if self.document_type == "labos_pilot_task":
            from .pilot import PilotPlan
            PilotPlan.model_validate(self.pilot_plan)
        return self


class Result(Model):
    protocol: Literal["labos-agent-v1"]
    document_type: Literal["labos_auto_result"]
    task_id: Identifier
    executable: Literal[False] = False
    backend: str = Field(min_length=1, max_length=64)
    model_attempts: int = Field(ge=0, le=2)
    answer: Answer
    source_evidence: list[dict] = Field(default_factory=list, max_length=6)
    pilot_result: dict | None = None


def load_worker_config(path):
    path = Path(path).resolve()
    config = WorkerConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8-sig")))
    for name in ("connection_config", "state_dir"):
        value = getattr(config, name)
        setattr(config, name, value if value.is_absolute() else path.parent / value)
    config.context_files = [p if p.is_absolute() else path.parent / p for p in config.context_files]
    config.source_roots = {k: p if p.is_absolute() else path.parent / p for k, p in config.source_roots.items()}
    return config


class Worker:
    def __init__(self, config, transport=None, responder=None):
        self.config = config
        self.connection = load_config(config.connection_config, CentralConfig if config.role == "central" else AgentConfig)
        if config.role == "central":
            if config.agent_id not in self.connection.agents:
                raise ValueError("worker PC identity is not enrolled centrally")
            credential = self.connection.admin_token
            self.credentials = [credential, *[a.token for a in self.connection.agents.values()]]
            url = f"http://127.0.0.1:{self.connection.port}"
        else:
            if config.agent_id != self.connection.agent_id:
                raise ValueError("worker PC identity does not match connection configuration")
            credential = self.connection.token
            self.credentials = [credential]
            url = self.connection.server_url
        self.context = ""
        for path in config.context_files:
            if path.stat().st_size > 32768:
                raise ValueError("approved context file exceeds 32 KiB")
            self.context += f"\n--- Approved snapshot: {path.name} ---\n" + path.read_text(encoding="utf-8-sig")
        if len(self.context.encode()) > 32768:
            raise ValueError("approved static context exceeds 32 KiB total")
        self.check_credentials(self.context)
        self.sources = ReadOnlySources(config.source_roots)
        verify = ssl.create_default_context(cafile=str(self.connection.ca_file)) if config.role == "pc" and self.connection.ca_file else True
        self.client = httpx.Client(base_url=url, headers={"Authorization": "Bearer " + credential},
                                  timeout=15, trust_env=False, verify=verify, transport=transport,
                                  proxy=self.connection.proxy_url if config.role == "pc" else None)
        self.path = f"/api/agents/{config.agent_id}/messages"
        self.peer = "pc" if config.role == "central" else "central"
        config.state_dir.mkdir(parents=True, exist_ok=True)
        self.database = config.state_dir / "correspondence.sqlite"
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            marker = db.execute("SELECT value FROM state WHERE key='worker_kind'").fetchone()
            if marker and marker[0] == 'physical-pilot' and config.backend != 'pilot':
                raise ValueError("physical pilot state requires its dedicated worker")
            identity = json.dumps([config.role, config.agent_id, url])
            db.execute("INSERT OR IGNORE INTO state VALUES('identity',?)", (identity,))
            if db.execute("SELECT value FROM state WHERE key='identity'").fetchone()[0] != identity:
                raise ValueError("worker state identity differs; use a separate state directory")
            db.execute("INSERT OR IGNORE INTO state VALUES('cursor',?)", (str(config.start_after),))
            db.execute("""CREATE TABLE IF NOT EXISTS inbox (
                id TEXT PRIMARY KEY, sequence INTEGER UNIQUE NOT NULL, envelope TEXT NOT NULL,
                state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                retry_at REAL NOT NULL DEFAULT 0, response TEXT, error TEXT)""")
        self.responder = responder or Responder(config)

    def db(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def check_credentials(self, text):
        if contains_credential(text, self.credentials):
            raise ValueError("credential found in model input or output")

    def find_own_message(self, message_id):
        after = 0
        while True:
            r = self.client.get(self.path, params={"sender": self.config.role, "after": after})
            r.raise_for_status()
            batch = r.json()
            for message in batch["messages"]:
                if message["id"] == message_id:
                    return message
            if not batch["messages"]:
                return None
            after = batch["next_cursor"]

    def eligible(self, message):
        body = message["body"]
        if body.get("protocol") != PROTOCOL:
            return False
        if body.get("document_type") == "labos_auto_task":
            Task.model_validate(body)
            if len(json_bytes(body.get("context", {}))) > 16384:
                raise ValueError("task context exceeds 16 KiB")
            return True
        if self.config.role == "central" and body.get("document_type") == "labos_auto_result":
            result = Result.model_validate(body)
            if message.get("kind") != "reply":
                raise ValueError("an automatic result must reply to its task")
            parent = self.find_own_message(message.get("in_reply_to"))
            if not parent or parent["body"].get("document_type") not in {"labos_auto_task", "labos_program_task", "labos_pilot_task"}:
                return False
            return Task.model_validate(parent["body"]).task_id == result.task_id
        return False

    def tick(self):
        with self.db() as db:
            cursor = int(db.execute("SELECT value FROM state WHERE key='cursor'").fetchone()[0])
        try:
            response = self.client.get(self.path, params={"sender": self.peer, "after": cursor})
            response.raise_for_status()
            batch = response.json()
            with self.db() as db:
                for message in batch["messages"]:
                    db.execute("INSERT OR IGNORE INTO inbox(id,sequence,envelope,state) VALUES(?,?,?,'pending')",
                               (message["id"], message["sequence"], json.dumps(message)))
                db.execute("UPDATE state SET value=? WHERE key='cursor'", (str(batch["next_cursor"]),))
        except httpx.HTTPError:
            return self.write_status("network_unavailable")
        with self.db() as db:
            row = db.execute("SELECT * FROM inbox WHERE state IN ('pending','ready') AND retry_at<=? ORDER BY sequence LIMIT 1",
                             (time.time(),)).fetchone()
        if row:
            self.process(row)
        return self.write_status("listening")

    def process(self, row):
        message = json.loads(row["envelope"])
        if row["state"] == "pending":
            try:
                self.check_credentials(message)
                eligible = self.eligible(message)
            except (ValueError, TypeError, KeyError):
                self.update(row["id"], state="rejected", error="invalid automation input")
                return
            except httpx.HTTPError:
                return
            if not eligible:
                self.update(row["id"], state="archived")
                return
            attempts = row["attempts"] + 1
            source_evidence = []
            try:
                model_input = message
                requests = message["body"].get("context", {}).get("source_requests")
                if requests is not None and message["body"]["document_type"] in {"labos_auto_task", "labos_program_task"}:
                    source_evidence = self.sources.collect(requests)
                    try:
                        self.check_credentials(source_evidence)
                    except ValueError:
                        source_evidence = []
                        raise SourceContextError("Collected source contains a configured credential; evidence was not exported") from None
                    model_input = {**message, "approved_source_evidence": source_evidence}
                if message["body"]["document_type"] == "labos_auto_result":
                    model_input = {**message, "original_task": self.find_own_message(message["in_reply_to"])["body"]}
                    pilot_result = message['body'].get('pilot_result')
                    if message['body'].get('backend') == 'pilot' and pilot_result is not None:
                        from .pilot_artifacts import review_snapshot
                        reference = pilot_result.get('artifact', {})
                        if reference.get('message_id') != message['in_reply_to']:
                            raise ValueError('pilot artifact does not match its task')
                        loaded = self.client.get(f"/api/pilot-artifacts/{self.config.agent_id}/{message['in_reply_to']}")
                        loaded.raise_for_status()
                        artifact = loaded.json()
                        digest = hashlib.sha256(json_bytes(artifact)).hexdigest()
                        if digest != reference.get('sha256'):
                            raise ValueError('pilot artifact review checksum mismatch')
                        snapshot = review_snapshot(artifact, digest)
                        self.check_credentials(snapshot)
                        model_input['stored_pilot_evidence'] = snapshot
                generated = self.responder.respond(model_input, self.context)
                answer = Answer.model_validate(generated["answer"]).model_dump()
                self.check_credentials(generated)
            except SourceContextError as exc:
                generated = {"backend": "source_context"}
                answer = {"status": "needs_input", "summary": str(exc), "findings": [],
                          "questions": ["Register the approved source roots or correct the bounded source request locally."]}
            except Exception as exc:
                # A bounded provider failure is durable and cannot consume tokens every poll.
                if attempts < 2:
                    self.update(row["id"], attempts=attempts, retry_at=time.time() + 60,
                                error=type(exc).__name__)
                    return
                generated = {"backend": "unavailable"}
                answer = {"status": "failed", "summary": "Report generation failed after two attempts. Check worker diagnostics and model availability.",
                          "findings": [], "questions": []}
            review = message["body"]["document_type"] == "labos_auto_result"
            body = {"protocol": PROTOCOL, "document_type": "labos_auto_review" if review else "labos_auto_result",
                    "task_id": message["body"]["task_id"], "executable": False,
                    "backend": generated["backend"], "answer": answer,
                    "model_attempts": 0 if generated["backend"] in {"program", "source_context", "pilot"} else attempts}
            if generated.get("pilot_result") is not None:
                body["pilot_result"] = generated["pilot_result"]
            if source_evidence:
                body["source_evidence"] = source_evidence
            response = {"id": "msg_auto_" + hashlib.sha256((self.config.role + ":" + row["id"]).encode()).hexdigest()[:40],
                        "kind": "reply", "in_reply_to": row["id"], "body": body}
            if len(json_bytes(response)) > MAX_MESSAGE_BYTES:
                response["body"]["answer"] = {"status": "failed", "summary": "Generated report exceeded the message size limit; request a shorter analysis.",
                                               "findings": [], "questions": []}
            self.update(row["id"], state="ready", response=json.dumps(response), attempts=attempts, retry_at=0)
        else:
            response = json.loads(row["response"])
        try:
            self.prepare_delivery(response)
            result = self.client.post(self.path, json=response)
            result.raise_for_status()
            self.update(row["id"], state="sent", error=None)
        except httpx.HTTPError as exc:
            code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            if code is not None and 400 <= code < 500 and code not in {401, 403, 408, 429}:
                self.update(row["id"], state="rejected", error=f"reply rejected (HTTP {code}); cached response retained")
            else:
                self.update(row["id"], retry_at=time.time() + self.config.poll_s,
                            error="reply delivery failed; cached response retained")

    def prepare_delivery(self, response):
        """Optional deterministic prerequisite; subclasses preserve cached reply IDs."""

    def update(self, message_id, **values):
        allowed = {"state", "attempts", "retry_at", "response", "error"}
        if not set(values) <= allowed:
            raise ValueError("invalid journal update")
        with self.db() as db:
            db.execute("UPDATE inbox SET " + ",".join(k + "=?" for k in values) + " WHERE id=?",
                       [*values.values(), message_id])

    def status(self):
        with self.db() as db:
            counts = {r["state"]: r["n"] for r in db.execute("SELECT state,COUNT(*) AS n FROM inbox GROUP BY state")}
            cursor = int(db.execute("SELECT value FROM state WHERE key='cursor'").fetchone()[0])
        return {"role": self.config.role, "agent_id": self.config.agent_id, "cursor": cursor,
                "counts": counts, "hardware_access": False, "pid": os.getpid(), "observed_at_unix": time.time()}

    def write_status(self, phase):
        status = {**self.status(), "phase": phase}
        atomic_write(self.config.state_dir / "status.json", json_bytes(status))
        return status

    def doctor(self):
        r = self.client.get("/health")
        r.raise_for_status()
        if r.json().get("service") != "labos-central":
            raise ValueError("destination is not LabOS central")
        self.client.get(self.path, params={"limit": 1}).raise_for_status()
        checks = {"authenticated_correspondence": True}
        if self.config.backend == "codex":
            p = subprocess.run([*self.config.codex_command, "exec", "--help"], capture_output=True, text=True, timeout=15)
            if p.returncode or any(flag not in p.stdout for flag in ("--ignore-user-config", "--ephemeral", "--output-schema")):
                raise ValueError("Codex CLI must support --ignore-user-config, --ephemeral and --output-schema; configure its executable path")
            p = subprocess.run([*self.config.codex_command, "login", "status"], capture_output=True, timeout=15)
            if p.returncode:
                raise ValueError("Codex CLI is not logged in for this Windows/user account")
            checks["codex_cli_authenticated"] = True
        if self.config.local_url:
            with httpx.Client(timeout=10, trust_env=False) as client:
                r = client.get(self.config.local_url + "/models")
                r.raise_for_status()
                if self.config.local_model not in [m["id"] for m in r.json().get("data", [])]:
                    raise ValueError("configured local model is not available")
            checks["local_model_available"] = True
        return {**checks, "hardware_access": False, "model_inference_performed": False,
                "registered_source_roots": list(self.sources.roots)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="LabOS background report cooperation")
    parser.add_argument("action", choices=["run", "once", "doctor", "status", "stop"])
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_worker_config(args.config)
        if args.action == "status":
            print((config.state_dir / "status.json").read_text(encoding="utf-8"))
            return 0
        if args.action == "stop":
            atomic_write(config.state_dir / "stop.request", b"stop\n")
            print("Stop requested; an active model call may take up to its configured timeout.")
            return 0
        if args.action == "doctor":
            worker = Worker(config)
            print(json.dumps(worker.doctor(), indent=2))
            return 0
        with InstanceLock(config.state_dir):
            worker = Worker(config)
            stop = config.state_dir / "stop.request"
            stop.unlink(missing_ok=True)
            if args.action == "once":
                print(json.dumps(worker.tick(), indent=2))
                return 0
            worker.write_status("started")
            while not stop.exists():
                worker.tick()
                for _ in range(max(1, int(config.poll_s * 5))):
                    if stop.exists():
                        break
                    time.sleep(0.2)
            worker.write_status("stopped")
            return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, httpx.HTTPError, subprocess.SubprocessError) as exc:
        # Print types, not provider output, URLs, configuration or request bodies.
        print(f"LabOS cooperation worker failed ({type(exc).__name__}). Check config paths, CLI login and HTTPS connectivity.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
