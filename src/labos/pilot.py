"""Finite, locally authorized pilot acquisition with an injected device boundary.

This module contains no instrument drivers. A verified minimum SR830 excitation
is 4 mV RMS at the terminal; it is neither excitation OFF nor a sample current.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


Positive = Annotated[float, Field(gt=0)]


class _PilotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True,
                              validate_default=True, strict=True)


class PilotPlan(_PilotModel):
    sample_id: Annotated[str, Field(min_length=1, max_length=160)]
    mode: Literal["photoresponse", "dark_hall", "combined", "dark_a"]
    laser_current_a: Positive | None = None
    power_limit_w: Positive | None = None
    reference_hz: Positive
    excitation_v_rms: Literal[0.004] = 0.004
    samples_per_phase: Annotated[int, Field(ge=1, le=10, strict=True)] = 1
    interval_s: Annotated[float, Field(ge=0, le=10)] = 0
    settle_s: Annotated[float, Field(ge=0, le=30)] = 0
    phase_timeout_s: Annotated[float, Field(ge=5, le=90)] = 30
    max_run_s: Annotated[float, Field(ge=5, le=300)] = 120

    @model_validator(mode="after")
    def check_mode(self):
        if not self.sample_id.strip():
            raise ValueError("sample_id must not be blank")
        if self.mode in {"photoresponse", "combined"}:
            if self.laser_current_a is None or self.power_limit_w is None:
                raise ValueError("photoresponse requires laser current and power limits")
        elif self.laser_current_a is not None or self.power_limit_w is not None:
            raise ValueError("dark modes must not request laser current or optical power")
        return self


class PilotApproval(_PilotModel):
    enabled: StrictBool = False
    sample_id: Annotated[str, Field(min_length=1, max_length=160)]
    laser_current_max_a: Positive | None = None
    power_limit_max_w: Positive | None = None
    reference_hz: Positive
    excitation_v_rms: Literal[0.004] = 0.004
    max_phase_s: Annotated[float, Field(ge=5, le=90)]
    max_run_s: Annotated[float, Field(ge=5, le=300)]

    @model_validator(mode="after")
    def check_sample(self):
        if not self.sample_id.strip():
            raise ValueError("sample_id must not be blank")
        return self

    def validate_plan(self, plan: PilotPlan) -> None:
        """Raise before device access unless this local profile authorizes the plan."""
        if not self.enabled:
            raise ValueError("physical pilot is disabled by local approval")
        if plan.sample_id != self.sample_id:
            raise ValueError("sample does not match local approval")
        if plan.reference_hz != self.reference_hz:
            raise ValueError("reference frequency does not match local approval")
        if plan.excitation_v_rms != self.excitation_v_rms:
            raise ValueError("excitation does not match local approval")
        if plan.phase_timeout_s > self.max_phase_s or plan.max_run_s > self.max_run_s:
            raise ValueError("requested duration exceeds local approval")
        if plan.mode in {"photoresponse", "combined"}:
            if (self.laser_current_max_a is None
                    or plan.laser_current_a > self.laser_current_max_a):
                raise ValueError("laser current exceeds or lacks local approval")
            if self.power_limit_max_w is None or plan.power_limit_w > self.power_limit_max_w:
                raise ValueError("optical power exceeds or lacks local approval")


class PilotEngine:
    """Own a finite run; adapters may guard inner I/O with set_guard(deadline, cancel).

    Guard deadlines are absolute monotonic times. An adapter's independent
    protection methods must bypass acquisition guards so expired budgets never
    suppress protection. Adapters can raise PilotCancelled for guarded I/O.
    """

    def __init__(self, adapter, clock=time.monotonic, sleep=time.sleep):
        self.adapter = adapter
        self.clock = clock
        self.sleep = sleep

    def run(self, plan, approval, cancel=None) -> dict:
        result = {"status": "FAILED", "samples": [], "rejected_samples": [],
                  "cleanup": [], "error": None,
                  "acquisition_complete": False, "protection_verified": False,
                  "preflight": None, "close_error": None}
        try:
            plan = PilotPlan.model_validate(plan.model_dump() if isinstance(plan, PilotPlan)
                                            else plan)
            approval = PilotApproval.model_validate(
                approval.model_dump() if isinstance(approval, PilotApproval) else approval)
            approval.validate_plan(plan)
        except (ValueError, TypeError) as exc:
            result["error"] = str(exc)
            return result

        result.update(sample_id=plan.sample_id, mode=plan.mode,
                      plan_sha256=_digest(plan), approval_sha256=_digest(approval))
        start = self.clock()
        deadline = start + plan.max_run_s
        opened = False
        owned = False
        try:
            self._check(cancel, deadline)
            self._set_guard(deadline, cancel)
            # Even a partial open must be closed, but open/preflight must not alter outputs.
            opened = True
            self.adapter.open()
            self._check(cancel, deadline)
            self._set_guard(deadline, cancel)
            preflight = _json_object(self.adapter.preflight(), "preflight")
            result["preflight"] = preflight
            if preflight.get("ready") is not True or preflight.get("laser_enabled") is not False:
                raise ValueError("preflight refused local ownership or laser is not verified OFF")
            owned = True
            self._check(cancel, deadline)
            for phase in _phases(plan.mode):
                self._check(cancel, deadline)
                self._set_guard(deadline, cancel)
                phase_deadline = min(deadline, self.clock() + plan.phase_timeout_s)
                try:
                    self._set_guard(phase_deadline, cancel)
                    self.adapter.configure(phase, plan)
                    self._check(cancel, phase_deadline)
                    if phase == "illuminated":
                        self._set_guard(phase_deadline, cancel)
                        self.adapter.laser_on(plan.laser_current_a)
                        self._check(cancel, phase_deadline)
                    self._pause(plan.settle_s, cancel, phase_deadline)
                    for index in range(plan.samples_per_phase):
                        self._check(cancel, phase_deadline)
                        self._set_guard(phase_deadline, cancel)
                        try:
                            raw = self.adapter.read_sample(phase)
                        except Exception as exc:
                            if hasattr(exc, "raw_sample"):
                                result["rejected_samples"].append(
                                    self._rejected(exc.raw_sample, phase, index, start, exc))
                            raise
                        try:
                            # A blocking call or validation can consume its remaining budget.
                            self._check(cancel, phase_deadline)
                            sample = _sample(raw, phase, plan.power_limit_w)
                            timestamp = self._check(cancel, phase_deadline)
                        except Exception as exc:
                            result["rejected_samples"].append(
                                self._rejected(raw, phase, index, start, exc))
                            raise
                        sample.update(phase=phase, sample_index=index,
                                      timestamp_monotonic_s=timestamp,
                                      elapsed_s=timestamp - start)
                        result["samples"].append(sample)
                        if index + 1 < plan.samples_per_phase:
                            self._pause(plan.interval_s, cancel, phase_deadline)
                finally:
                    result["cleanup"].append(self._protect(phase, plan.excitation_v_rms))
                if not result["cleanup"][-1]["verified"]:
                    raise _ProtectionFailure("phase protection could not be verified")
                self._check(cancel, phase_deadline)
            result["acquisition_complete"] = True
            self._check(cancel, deadline)
            result["status"] = "COMPLETED"
        except PilotCancelled as exc:
            result.update(status="CANCELLED", error=str(exc))
        except Exception as exc:
            result.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
        finally:
            # Never protect a foreign owner when read-only preflight refuses the run.
            if owned:
                result["cleanup"].append(self._protect("final", plan.excitation_v_rms))
                result["protection_verified"] = all(item["verified"] for item in result["cleanup"])
                if not result["protection_verified"]:
                    result["status"] = "UNKNOWN"
                    if result["error"] is None:
                        result["error"] = "output protection could not be verified"
            if opened:
                try:
                    self.adapter.close()
                except BaseException as exc:
                    result["close_error"] = f"{type(exc).__name__}: {exc}"
                    result["status"] = "UNKNOWN"
                    result["error"] = result["error"] or "adapter close failed"
        if result["status"] == "COMPLETED":
            # Finish every protection/release attempt even when the run budget expires.
            try:
                self._check(cancel, deadline)
            except PilotCancelled as exc:
                result.update(status="CANCELLED", error=str(exc))
            except Exception as exc:
                result.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
        return result

    def _rejected(self, raw, phase, index, start, error):
        timestamp = self.clock()
        record = {"phase": phase, "sample_index": index,
                  "timestamp_monotonic_s": timestamp, "elapsed_s": timestamp - start,
                  "reason": f"{type(error).__name__}: {error}"[:2048], "raw": None}
        try:
            record["raw"] = _json_object(raw, "rejected sample")
        except Exception as exc:
            record["raw_error"] = f"{type(exc).__name__}: {exc}"[:2048]
        return record

    def _set_guard(self, deadline, cancel):
        guard = getattr(self.adapter, "set_guard", None)
        if guard is not None:
            guard(deadline, cancel)

    def _check(self, cancel, deadline):
        if cancel is not None:
            cancelled = cancel() if callable(cancel) else cancel.is_set()
            if cancelled:
                raise PilotCancelled("pilot cancellation requested")
        now = self.clock()
        if now >= deadline:
            raise TimeoutError("pilot deadline exceeded")
        return now

    def _pause(self, duration, cancel, deadline):
        end = self.clock() + duration
        while True:
            self._check(cancel, deadline)
            remaining = end - self.clock()
            if remaining <= 0:
                return
            self.sleep(min(remaining, 0.1))

    def _protect(self, scope, expected_v_rms):
        """Attempt both protections even if either command/readback fails."""
        record = {"scope": scope}
        try:
            laser = _json_object(self.adapter.laser_off(), "laser protection readback")
            laser["laser_off_verified"] = laser.get("laser_off_verified") is True
        except BaseException as exc:
            laser = {"laser_off_verified": False, "error": f"{type(exc).__name__}: {exc}"}
        record["laser_off"] = laser
        try:
            excitation = _json_object(self.adapter.protect_excitation(),
                                      "excitation protection readback")
            actual = excitation.get("actual_v_rms")
            excitation["minimum_excitation_verified"] = (
                excitation.get("minimum_excitation_verified") is True
                and _finite_number(actual) and actual == expected_v_rms)
        except BaseException as exc:
            excitation = {"minimum_excitation_verified": False,
                          "error": f"{type(exc).__name__}: {exc}"}
        record["protect_excitation"] = excitation
        record["verified"] = (laser["laser_off_verified"]
                              and excitation["minimum_excitation_verified"])
        return record


class PilotCancelled(Exception):
    """Cancellation raised by the engine or an adapter's per-I/O guard."""


class _ProtectionFailure(Exception):
    pass


def _phases(mode):
    if mode == "dark_a":
        return ["dark_a_1f", "dark_a_2f"]
    phases = []
    if mode in {"photoresponse", "combined"}:
        phases.extend(["dark_baseline", "illuminated"])
    if mode in {"dark_hall", "combined"}:
        phases.append("dark_hall_2f")
    return phases


def _digest(model):
    payload = json.dumps(model.model_dump(mode="json"), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _json_object(value, label):
    """Copy bounded finite JSON, avoiding aliases to mutable backend buffers."""
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    budget = [4096]

    def check(item, depth=0):
        budget[0] -= 1
        if budget[0] < 0 or depth > 16:
            raise ValueError(f"{label} exceeds JSON structure bounds")
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError(f"{label} has a non-string JSON key")
                check(child, depth + 1)
        elif type(item) is list:
            for child in item:
                check(child, depth + 1)
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError(f"{label} contains a nonfinite value")
        elif item is not None and type(item) not in (str, int, bool):
            raise ValueError(f"{label} contains a non-JSON value")

    check(value)
    encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode()) > 65536:
        raise ValueError(f"{label} exceeds JSON size bounds")
    return json.loads(encoded)


def _sample(raw, phase, power_limit_w):
    sample = _json_object(raw, "sample")
    channels = sample.get("channels")
    if not isinstance(channels, dict) or not channels:
        raise ValueError("sample requires per-role raw channels")
    if any(not isinstance(values, dict) or not values for values in channels.values()):
        raise ValueError("each raw channel requires a nonempty JSON object")
    if phase == "illuminated":
        power = sample.get("power_w")
        if not _finite_number(power) or power < 0:
            raise ValueError("illuminated sample requires finite nonnegative power_w")
        if power > power_limit_w:
            raise ValueError("measured optical power exceeds approved power limit")
    return sample
