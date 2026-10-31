"""Outbound program-only correspondence: fixed local programs, no model backend."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
import yaml
from pydantic import Field, model_validator

from .config import AgentConfig, load_config
from .cooperation_worker import PROTOCOL, Task, Worker, WorkerConfig
from .files import InstanceLock, atomic_write, json_bytes
from .models import Identifier, Model


class ParameterLimit(Model):
    type: Literal["string", "integer", "number", "boolean"]
    required: bool = False
    choices: list[str | int | float | bool] | None = Field(
        default=None, min_length=1, max_length=100
    )
    minimum: float | None = None
    maximum: float | None = None
    max_length: int = Field(default=256, ge=1, le=4096)

    @model_validator(mode="after")
    def bounded(self):
        if self.type in {"integer", "number"}:
            if self.minimum is None or self.maximum is None or self.minimum > self.maximum:
                raise ValueError("numeric program parameters require explicit minimum and maximum")
        return self

    def check(self, value):
        valid = {
            "string": isinstance(value, str),
            "integer": type(value) is int,
            "number": type(value) in {int, float},
            "boolean": type(value) is bool,
        }[self.type]
        if not valid:
            raise ValueError("parameter has incorrect type")
        if isinstance(value, str) and len(value) > self.max_length:
            raise ValueError("parameter string is too long")
        if type(value) in {int, float}:
            if not math.isfinite(value):
                raise ValueError("parameter must be finite")
            if self.minimum is not None and value < self.minimum:
                raise ValueError("parameter below local minimum")
            if self.maximum is not None and value > self.maximum:
                raise ValueError("parameter above local maximum")
        if self.choices is not None and not any(
            value == choice
            and (
                type(value) is type(choice)
                or self.type == "number"
                and type(choice) in {int, float}
            )
            for choice in self.choices
        ):
            raise ValueError("parameter is not a locally approved choice")


class ApprovedProgram(Model):
    enabled: bool = False
    argv: list[str] = Field(min_length=1, max_length=40)
    cwd: Path | None = None
    parameters: dict[Identifier, ParameterLimit] = Field(default_factory=dict, max_length=40)
    timeout_s: float = Field(default=30, ge=0.1, le=600)
    max_output_bytes: int = Field(default=8192, ge=256, le=16384)
    hardware: Literal[False] = False

    @model_validator(mode="after")
    def fixed_command(self):
        if any(not arg or "\x00" in arg for arg in self.argv):
            raise ValueError("program argv must contain nonempty fixed arguments")
        if not Path(self.argv[0]).is_absolute():
            raise ValueError("program executable must be a locally configured absolute path")
        if Path(self.argv[0]).suffix.lower() in {".bat", ".cmd", ".ps1"}:
            raise ValueError("shell scripts are not approved program executables")
        return self

    def validate_parameters(self, parameters):
        if not isinstance(parameters, dict) or set(parameters) - set(self.parameters):
            raise ValueError("unknown program parameters")
        if len(json_bytes(parameters)) > 8192:
            raise ValueError("program parameters exceed local limit")
        for name, limit in self.parameters.items():
            if name not in parameters:
                if limit.required:
                    raise ValueError("required program parameter is missing")
            else:
                limit.check(parameters[name])


class ProgramConfig(Model):
    role: Literal["pc"] = "pc"
    agent_id: Identifier
    connection_config: Path
    state_dir: Path = Path("data/program-connector")
    start_after: int = Field(default=0, ge=0)
    poll_s: float = Field(default=10, ge=1, le=300)
    source_roots: dict[Identifier, Path] = Field(default_factory=dict)
    programs: dict[Identifier, ApprovedProgram] = Field(default_factory=dict)

    @model_validator(mode="after")
    def builtin_names(self):
        if {"source_snapshot", "runtime_check"} & set(self.programs):
            raise ValueError("built-in program names cannot be replaced")
        return self


def load_program_config(path):
    path = Path(path).resolve()
    config = ProgramConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8-sig")))
    for name in ("connection_config", "state_dir"):
        value = getattr(config, name)
        setattr(config, name, value if value.is_absolute() else path.parent / value)
    config.source_roots = {
        key: p if p.is_absolute() else path.parent / p for key, p in config.source_roots.items()
    }
    for program in config.programs.values():
        if program.cwd and not program.cwd.is_absolute():
            program.cwd = path.parent / program.cwd
    return config


def report(status, summary, findings=None, questions=None):
    return {
        "backend": "program",
        "answer": {
            "status": status,
            "summary": summary,
            "findings": findings or [],
            "questions": questions or [],
        },
    }


def run_bounded(program, parameters, check_credentials):
    """Drain pipes continuously with a shared memory cap and stop on limit/timeout."""
    process = subprocess.Popen(
        program.argv,
        cwd=program.cwd,
        shell=False,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output = bytearray()
    lock = threading.Lock()
    exceeded = threading.Event()

    def read(pipe):
        try:
            while chunk := pipe.read(1024):
                with lock:
                    remaining = program.max_output_bytes - len(output)
                    output.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        exceeded.set()
                        process.kill()
                        break
        except (OSError, ValueError):
            pass
        finally:
            pipe.close()

    readers = [
        threading.Thread(target=read, args=(pipe,), daemon=True)
        for pipe in (process.stdout, process.stderr)
    ]
    for reader in readers:
        reader.start()

    def write():
        try:
            process.stdin.write(json_bytes(parameters) + b"\n")
            process.stdin.close()
        except (OSError, ValueError):
            pass

    writer = threading.Thread(target=write, daemon=True)
    writer.start()
    try:
        process.wait(timeout=program.timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return report(
            "needs_input",
            "Program time limit reached; reconcile its outcome locally before any new request.",
        )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        writer.join(timeout=1)
        for reader in readers:
            reader.join(timeout=1)
    if exceeded.is_set():
        return report(
            "needs_input",
            "Program output limit reached; reconcile its outcome locally before any new request.",
        )
    text = output.decode("utf-8", errors="replace")
    check_credentials(text)
    findings = [text[i : i + 1800] for i in range(0, len(text), 1800)][:12]
    return report(
        "completed" if process.returncode == 0 else "failed",
        f"Approved program finished with exit code {process.returncode}.",
        findings,
    )


class ProgramResponder:
    """Execution ledger survives crashes and transport-journal replay independently."""

    def __init__(self, owner):
        self.owner = owner

    def respond(self, message, context):
        owner = self.owner
        message_id = message["id"]
        with sqlite3.connect(owner.execution_database) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state,result FROM executions WHERE message_id=?", (message_id,)
            ).fetchone()
            if row:
                if row[0] == "finished":
                    return json.loads(row[1])
                return report(
                    "needs_input",
                    "Previous execution outcome is unknown; local reconciliation is required before any new request.",
                )
            # Commit intent before any subprocess can be started, even on a responder retry.
            db.execute(
                "INSERT INTO executions(message_id,state,result) VALUES(?,'started',NULL)",
                (message_id,),
            )
        try:
            result = self.execute(message)
            owner.check_credentials(result)
        except ValueError:
            result = report(
                "needs_input",
                "Program request or output did not meet local approval and parameter limits. Review the local catalog and supplied evidence.",
            )
        except Exception:
            result = report(
                "needs_input",
                "Program outcome requires local reconciliation. Inspect the local execution ledger before any new request.",
            )
        with sqlite3.connect(owner.execution_database) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute(
                "UPDATE executions SET state='finished',result=? WHERE message_id=?",
                (json.dumps(result), message_id),
            )
        return result

    def execute(self, message):
        body = message["body"]
        program_id, parameters = body.get("program_id"), body.get("parameters", {})
        if program_id in {"runtime_check", "source_snapshot"}:
            if parameters:
                raise ValueError("built-in programs do not accept parameters")
            if program_id == "runtime_check":
                return report(
                    "completed",
                    f"Python {sys.version.split()[0]} runtime is available; no devices were opened.",
                    ["Program-only connector; no local model inference was performed."],
                )
            evidence = message.get("approved_source_evidence", [])
            if not evidence:
                raise ValueError("source_snapshot requires source_requests")
            return report(
                "completed",
                f"Collected {len(evidence)} approved source excerpts without importing production code.",
                ["Source evidence is attached for central review."],
            )
        program = self.owner.program_config.programs.get(program_id)
        if not program or not program.enabled:
            return report(
                "needs_input",
                "The requested program is not enabled in this PC local approval catalog.",
            )
        program.validate_parameters(parameters)
        return run_bounded(program, parameters, self.owner.check_credentials)


class ProgramConnector(Worker):
    def __init__(self, config, transport=None):
        self.program_config = config
        connection = load_config(config.connection_config, AgentConfig)
        if urlsplit(connection.server_url).scheme != "https":
            raise ValueError("program-only PC connections require public HTTPS")
        # Worker receives a deterministic responder explicitly, never its model-backed default.
        worker_config = WorkerConfig(
            role="pc",
            agent_id=config.agent_id,
            connection_config=config.connection_config,
            state_dir=config.state_dir,
            poll_s=config.poll_s,
            start_after=config.start_after,
            source_roots=config.source_roots,
        )
        self.execution_database = config.state_dir / "program-executions.sqlite"
        super().__init__(worker_config, transport=transport, responder=ProgramResponder(self))
        with sqlite3.connect(self.execution_database) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS executions(message_id TEXT PRIMARY KEY, state TEXT NOT NULL, result TEXT)"
            )

    def eligible(self, message):
        body = message["body"]
        if body.get("protocol") != PROTOCOL or body.get("document_type") != "labos_program_task":
            return False
        Task.model_validate(body)
        if not body.get("program_id") or len(json_bytes(body.get("context", {}))) > 16384:
            raise ValueError("program task requires a program ID and bounded context")
        return True

    def doctor(self):
        response = self.client.get("/health")
        response.raise_for_status()
        if response.json().get("service") != "labos-central":
            raise ValueError("destination is not LabOS central")
        self.client.get(self.path, params={"limit": 1}).raise_for_status()
        from .source_context import ReadOnlySources

        ReadOnlySources(self.program_config.source_roots)
        for program in self.program_config.programs.values():
            if program.enabled and (
                not Path(program.argv[0]).is_file() or (program.cwd and not program.cwd.is_dir())
            ):
                raise ValueError("approved executable or working directory is unavailable")
        return {
            "authenticated_correspondence": True,
            "public_https": True,
            "profile": "program_only",
            "hardware_access": self.catalog_hardware_access(),
            "model_inference_performed": False,
            "enabled_programs": ["runtime_check", "source_snapshot"]
            + [key for key, value in self.program_config.programs.items() if value.enabled],
        }

    def catalog_hardware_access(self):
        return (
            "possible_from_local_catalog"
            if any(p.enabled for p in self.program_config.programs.values())
            else False
        )

    def status(self):
        return {
            **super().status(),
            "profile": "program_only",
            "hardware_access": self.catalog_hardware_access(),
            "model_inference_performed": False,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="LabOS outbound program-only connector (no local model)"
    )
    parser.add_argument("action", choices=["run", "once", "doctor", "status", "stop"])
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_program_config(args.config)
        if args.action == "status":
            print((config.state_dir / "status.json").read_text(encoding="utf-8"))
            return 0
        if args.action == "stop":
            atomic_write(config.state_dir / "stop.request", b"stop\n")
            print(
                "Stop requested; the active approved program may finish within its configured timeout."
            )
            return 0
        if args.action == "doctor":
            worker = ProgramConnector(config)
            print(json.dumps(worker.doctor(), indent=2))
            worker.client.close()
            return 0
        with InstanceLock(config.state_dir):
            worker = ProgramConnector(config)
            stop = config.state_dir / "stop.request"
            stop.unlink(missing_ok=True)
            if args.action == "once":
                print(json.dumps(worker.tick(), indent=2))
                worker.client.close()
                return 0
            worker.write_status("started")
            while not stop.exists():
                worker.tick()
                for _ in range(max(1, int(config.poll_s * 5))):
                    if stop.exists():
                        break
                    time.sleep(0.2)
            worker.write_status("stopped")
            worker.client.close()
            return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, httpx.HTTPError, subprocess.SubprocessError):
        print(
            "LabOS program connector failed. Check local approval configuration, paths and public HTTPS connectivity."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
