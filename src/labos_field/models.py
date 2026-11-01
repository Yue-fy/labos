from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from labos.models import Identifier, Model
from labos.pilot import PilotPlan

TARGETS = (-0.5, -0.25, 0.0, 0.25, 0.5)


def optical_plan():
    return PilotPlan(sample_id="CrSBr 1", mode="photoresponse", laser_current_a=.020,
                     power_limit_w=1e-6, reference_hz=8., samples_per_phase=3,
                     settle_s=15., phase_timeout_s=60., max_run_s=180.)


class CampaignTask(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)
    protocol: Literal["labos-magnetic-v1"] = "labos-magnetic-v1"
    document_type: Literal["labos_magnetic_campaign_task"] = "labos_magnetic_campaign_task"
    hardware_execution: Literal[True] = True
    task_id: Identifier
    agent_id: Literal["cryostat-pc"] = "cryostat-pc"
    sample_id: Literal["CrSBr 1"] = "CrSBr 1"
    targets_z_t: tuple[float, ...] = TARGETS
    final_z_t: Literal[0.0] = 0.
    optical: PilotPlan = Field(default_factory=optical_plan)
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @field_validator("targets_z_t", mode="before")
    @classmethod
    def targets(cls, values):
        if not isinstance(values, (list, tuple)) or any(type(v) not in (int, float) for v in values):
            raise ValueError("targets require numeric field values")
        if tuple(values) != TARGETS:
            raise ValueError("only the five ordered operator-selected Z targets are supported")
        return tuple(float(v) for v in values)

    @model_validator(mode="after")
    def scope(self):
        if self.optical.model_dump() != optical_plan().model_dump():
            raise ValueError("optical scope differs from the fixed approved pilot")
        lifetime = (self.expires_at - self.issued_at).total_seconds()
        if not 0 < lifetime <= 21600:
            raise ValueError("task validity must be positive and at most six hours")
        return self


def default_task(task_id):
    now = datetime.now(timezone.utc)
    return CampaignTask(task_id=task_id, issued_at=now, expires_at=now + timedelta(hours=3))


class LocalConfig(Model):
    enabled: StrictBool = False
    agent_id: Literal["cryostat-pc"] = "cryostat-pc"
    task_id: Identifier
    message_id: Identifier
    message_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    connection_config: Path
    optical_profile: Path
    optical_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_dir: Path
    magnetic_source_dir: Path
    dll_path: Path
    magnetic_lease_profiles: list[Path] = Field(min_length=2, max_length=2)
    temperature_setpoint_k: Literal[180.0] = 180.
    temperature_baseline_k: float = Field(ge=179.9, le=180.1)
    temperature_drift_max_k: Literal[0.1] = .1
    transition_timeout_s: Literal[900.0] = 900.
    cleanup_timeout_s: Literal[900.0] = 900.
    max_campaign_s: Literal[6300.0] = 6300.
    commissioning_max_age_s: Literal[600] = 600

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.magnetic_lease_profiles)) != 2 or self.optical_profile in self.magnetic_lease_profiles:
            raise ValueError("magnetic leases must be distinct from the optical worker profile")
        return self


def load_config(path):
    path = Path(path).resolve()
    c = LocalConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8-sig")))
    for name in ("connection_config", "optical_profile", "state_dir", "magnetic_source_dir", "dll_path"):
        value = getattr(c, name)
        setattr(c, name, (path.parent / value).resolve() if not value.is_absolute() else value.resolve())
    c.magnetic_lease_profiles = [(path.parent / p).resolve() if not p.is_absolute() else p.resolve()
                                 for p in c.magnetic_lease_profiles]
    return c


def fingerprint(config):
    from .records import digest
    return digest(config.model_dump(mode="json", exclude={"enabled"}))


def authorize(message, message_id, expected_sha, task_id, now=None):
    from .records import digest
    if (message.get("id") != message_id or message.get("sender") != "central"
            or message.get("agent_id") != "cryostat-pc"):
        raise ValueError("campaign message identity, sender or PC mismatch")
    content = {k: message.get(k) for k in ("id", "kind", "in_reply_to", "body")}
    actual = digest(content)
    if actual != expected_sha or message.get("sha256") != actual:
        raise ValueError("campaign message hash mismatch")
    from labos.files import json_bytes
    task = CampaignTask.model_validate_json(json_bytes(message["body"]))
    now = now or datetime.now(timezone.utc)
    if task.task_id != task_id or now < task.issued_at - timedelta(seconds=5) or now >= task.expires_at:
        raise ValueError("campaign task identity or validity interval mismatch")
    return task
