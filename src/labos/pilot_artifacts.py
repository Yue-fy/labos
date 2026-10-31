"""Durable physical pilot JSON, independent of the simulated spectrum schema."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from pydantic import Field, ValidationError

from .files import atomic_write, contains_credential, json_bytes
from .models import Identifier, Model

MAX_PILOT_ARTIFACT_BYTES = 2_000_000


class PilotArtifact(Model):
    message_id: Identifier
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report: dict


class PilotArtifacts:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS pilot_artifacts (
                agent_id TEXT NOT NULL, message_id TEXT NOT NULL, sha256 TEXT NOT NULL,
                path TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(agent_id,message_id))""")

    def put(self, agent_id, content, digest, credentials):
        from .pilot import PilotPlan

        if len(content) > MAX_PILOT_ARTIFACT_BYTES or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Physical artifact size/checksum mismatch")
        try:
            artifact = PilotArtifact.model_validate_json(content)
            json_bytes(artifact.report)  # Reject nested NaN/Infinity too.
        except (ValueError, ValidationError):
            raise ValueError("Invalid physical pilot artifact") from None
        if contains_credential(artifact.model_dump(), credentials):
            raise ValueError("Credentials cannot be stored in physical artifacts")
        report = artifact.report
        if (
            report.get("status") not in ("COMPLETED", "FAILED", "CANCELLED", "UNKNOWN")
            or type(report.get("acquisition_complete")) is not bool
            or type(report.get("protection_verified")) is not bool
            or not isinstance(report.get("samples"), list)
            or len(report["samples"]) > 30
            or (
                report["status"] == "COMPLETED"
                and not (report["acquisition_complete"] and report["protection_verified"])
            )
        ):
            raise ValueError("Inconsistent physical pilot status or samples")
        for sample in report["samples"]:
            if (
                not isinstance(sample, dict)
                or sample.get("phase") not in ("dark_baseline", "illuminated", "dark_hall_2f")
                or not isinstance(sample.get("channels", {}), dict)
                or ("power_w" in sample and type(sample["power_w"]) not in (int, float))
            ):
                raise ValueError("Invalid physical pilot sample shape")
            for role, channel in sample.get("channels", {}).items():
                if not isinstance(role, str) or not isinstance(channel, dict):
                    raise ValueError("Invalid physical pilot channel shape")
                if any(
                    key in channel and type(channel[key]) not in (int, float)
                    for key in ("x_v", "y_v")
                ):
                    raise ValueError("Physical pilot voltages must be numeric")
        if not isinstance(report.get("rejected_samples", []), list):
            raise ValueError("Rejected physical samples must be an array")
        try:
            plan = PilotPlan.model_validate(report["plan"])
        except (KeyError, ValueError):
            raise ValueError("Physical artifact requires its validated plan") from None
        actual_plan_hash = hashlib.sha256(json_bytes(plan.model_dump(mode="json"))).hexdigest()
        if actual_plan_hash != artifact.plan_sha256:
            raise ValueError("Physical artifact plan fingerprint mismatch")
        with self.store.transaction() as db:
            parent = db.execute(
                "SELECT sender,body FROM correspondence WHERE agent_id=? AND id=?",
                (agent_id, artifact.message_id),
            ).fetchone()
            if parent is None:
                raise KeyError("Physical pilot task not found")
            task = json.loads(parent["body"])["body"]
            if (
                parent["sender"] != "central"
                or task.get("protocol") != "labos-agent-v1"
                or task.get("document_type") != "labos_pilot_task"
                or report.get("task_id") != task.get("task_id")
            ):
                raise ValueError("Physical artifact does not match a central pilot task")
            try:
                expected = PilotPlan.model_validate(task["pilot_plan"])
            except (ValueError, KeyError):
                raise ValueError("Central pilot plan is invalid") from None
            if expected != plan:
                raise ValueError("Physical artifact differs from the central pilot plan")
            old = db.execute(
                "SELECT sha256,path FROM pilot_artifacts WHERE agent_id=? AND message_id=?",
                (agent_id, artifact.message_id),
            ).fetchone()
            path = self.store.root / "pilot-artifacts" / agent_id / (artifact.message_id + ".json")
            if old and (
                old["sha256"] != digest
                or not Path(old["path"]).is_file()
                or hashlib.sha256(Path(old["path"]).read_bytes()).hexdigest() != digest
            ):
                raise ValueError(
                    "Physical artifact already exists with different or unavailable content"
                )
            if not old:
                if path.exists() and path.read_bytes() != content:
                    raise ValueError(
                        "Unindexed physical artifact differs; local reconciliation required"
                    )
                atomic_write(path, content)
                db.execute(
                    "INSERT INTO pilot_artifacts VALUES(?,?,?,?,?)",
                    (agent_id, artifact.message_id, digest, str(path), time.time()),
                )
                self.store.event_db(
                    db,
                    "PHYSICAL_PILOT_ARTIFACT_STORED",
                    {
                        "agent_id": agent_id,
                        "message_id": artifact.message_id,
                        "sha256": digest,
                        "status": report["status"],
                        "samples": len(report["samples"]),
                    },
                )
        return {"accepted": True, "sha256": digest, "message_id": artifact.message_id}

    def get(self, agent_id, message_id):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT path,sha256 FROM pilot_artifacts WHERE agent_id=? AND message_id=?",
                (agent_id, message_id),
            ).fetchone()
        if row is None:
            raise KeyError("Physical pilot artifact not found")
        content = Path(row["path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError("Stored physical artifact checksum mismatch")
        return json.loads(content)


def review_snapshot(artifact, digest):
    """Bounded numerical evidence for model review; full raw data stays downloadable."""
    report = artifact["report"]
    groups = {}
    for sample in report["samples"]:
        phase = sample.get("phase", "unassigned")
        group = groups.setdefault(phase, {"sample_count": 0, "power_w": [], "channels": {}})
        group["sample_count"] += 1
        if type(sample.get("power_w")) in (int, float):
            group["power_w"].append(sample["power_w"])
        for role, values in sample.get("channels", {}).items():
            channel = group["channels"].setdefault(role, {"x_v": [], "y_v": []})
            for key in ("x_v", "y_v"):
                if type(values.get(key)) in (int, float):
                    channel[key].append(values[key])

    def stats(values):
        return (
            {
                "count": len(values),
                "mean": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
            }
            if values
            else None
        )

    for group in groups.values():
        group["power_w"] = stats(group["power_w"])
        group["channels"] = {
            role: {key: stats(vals) for key, vals in values.items()}
            for role, values in group["channels"].items()
        }
    return {
        "central_raw_artifact_verified": True,
        "sha256": digest,
        "task_id": report["task_id"],
        "status": report["status"],
        "plan": report["plan"],
        "preflight": report.get("preflight"),
        "acquisition_complete": report["acquisition_complete"],
        "protection_verified": report["protection_verified"],
        "cleanup": report.get("cleanup", []),
        "error": report.get("error"),
        "phase_statistics": groups,
        "rejected_sample_count": len(report.get("rejected_samples", [])),
        "interpretation": "Numerical raw-response summary; no BVPE/nonlinear-Hall attribution or current calibration is implied.",
    }
