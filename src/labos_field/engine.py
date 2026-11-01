from __future__ import annotations

from datetime import datetime, timezone
import math
import json
import time
from types import SimpleNamespace

from labos.cryostat_pilot import ReadingFault
from labos.files import json_bytes
from labos.pilot import PilotEngine
from . import __version__, CORE_VERSION
from .magnet import validate_state, SOURCE_SHA, DLL_SHA, READS, WRITES
from .models import CampaignTask, HYSTERESIS_TARGETS
from .records import digest


def accept_point(point, config):
    z = point["target_z_t"]
    validate_state(point["field"]["state"], config, target=z, require_control=True)
    if point["field"].get("qualified") is not True:
        raise ValueError("field point lacks qualification")
    result = point["optical"]
    if (
        result.get("status") != "COMPLETED"
        or result.get("acquisition_complete") is not True
        or result.get("protection_verified") is not True
        or result.get("close_error") is not None
        or result.get("rejected_samples")
        or not result.get("cleanup")
        or not all(c.get("verified") is True for c in result["cleanup"])
    ):
        raise ValueError("optical point failed completeness or protection requirements")
    samples = result["samples"]
    if len(samples) != 6:
        raise ValueError("point must retain exactly six raw samples")
    for phase in ("dark_baseline", "illuminated"):
        selected = [s for s in samples if s.get("phase") == phase]
        if len(selected) != 3 or [s.get("sample_index") for s in selected] != [0, 1, 2]:
            raise ValueError("missing, duplicated or misordered phase samples")
    for sample in samples:
        if sample.get("simulated") is not False or sample.get("excitation_v_rms") != 0.004:
            raise ValueError("invalid physical sample identity/excitation")
        if sample.get("laser_enabled") is not (sample["phase"] == "illuminated"):
            raise ValueError("sample laser/phase mismatch")
        power = sample.get("power_w")
        if type(power) not in (float, int) or not math.isfinite(power) or not 0 <= power <= 1e-6:
            raise ValueError("invalid power sample")
        for role in ("xx", "xy"):
            channel = sample["channels"][role]
            if (
                channel.get("harmonic") != 1
                or channel.get("lia_status_raw") != 0
                or channel.get("error_status_raw") != 0
            ):
                raise ValueError("invalid lock-in settings or status")
            for key in ("x_v", "y_v"):
                if type(channel.get(key)) not in (float, int) or not math.isfinite(channel[key]):
                    raise ValueError("missing finite lock-in channel")
        for when in ("magnetic_before", "magnetic_after"):
            validate_state(sample[when]["state"], config, target=z, require_control=True)
    return True


class PointView:
    """Borrow campaign sessions; close releases only the point view."""

    def __init__(self, optical, magnet, config, z, deadline, records, emit, check, point_index):
        self.optical, self.magnet, self.config, self.z = optical, magnet, config, z
        self.deadline = deadline
        self.records, self.emit, self.check = records, emit, check
        self.point_index = point_index

    def set_guard(self, deadline, cancel):
        deadline = min(deadline, self.deadline)
        self.optical.set_guard(deadline, cancel)
        guard = getattr(self.magnet, "set_guard", None)
        if guard:
            guard(deadline)

    def open(self):
        pass

    def preflight(self):
        validate_state(self.magnet.read()["state"], self.config, self.z, True)
        return self.optical.preflight()

    def configure(self, phase, plan):
        self.optical.configure(phase, plan)

    def laser_on(self, current):
        self.optical.laser_on(current)

    def laser_off(self):
        return self.optical.laser_off()

    def protect_excitation(self):
        return self.optical.protect_excitation()

    def close(self):
        pass

    def read_sample(self, phase):
        raw = {}
        before = None
        try:
            before = self.magnet.read()
            validate_state(before["state"], self.config, self.z, True)
            raw = self.optical.read_sample(phase)
            raw["magnetic_before"] = before
            record = {
                "phase": phase,
                "raw": json.loads(json_bytes(raw)),
                "acceptance": "captured_before_native_engine_validation",
            }
            self.records.append(record)
            self.emit(
                {
                    "event": "sample_raw_captured",
                    "point_index": self.point_index,
                    "target_z_t": self.z,
                    "record_index": len(self.records) - 1,
                    "record": json.loads(json_bytes(record)),
                }
            )
            self.check()
            after = self.magnet.read()
            raw["magnetic_after"] = after
            validate_state(after["state"], self.config, self.z, True)
            record["raw"] = json.loads(json_bytes(raw))
            self.emit(
                {
                    "event": "sample_context_completed",
                    "point_index": self.point_index,
                    "target_z_t": self.z,
                    "record_index": len(self.records) - 1,
                    "record": record,
                }
            )
            self.check()
            return raw
        except Exception as exc:
            rejected = getattr(exc, "raw_sample", raw)
            if isinstance(rejected, dict):
                rejected = {**rejected, "magnetic_before": before, "field_target_z_t": self.z}
            raise ReadingFault(f"{type(exc).__name__}: {exc}", rejected) from exc


class CampaignEngine:
    def __init__(self, optical, magnet, config, clock=time.monotonic, sleep=time.sleep):
        self.optical, self.magnet, self.config = optical, magnet, config
        self.clock, self.sleep = clock, sleep

    def run(self, task, approval, event_sink=lambda event: None):
        task = CampaignTask.model_validate_json(json_bytes(task.model_dump(mode="json")))
        approval.validate_plan(task.optical)
        result = {
            "status": "FAILED",
            "task": task.model_dump(mode="json"),
            "task_sha256": digest(task.model_dump(mode="json")),
            "extension_version": __version__,
            "core_version": CORE_VERSION,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "points": [],
            "error": None,
            "protection": [],
            "zero": None,
            "close_error": None,
            "evidence_errors": [],
            "temperature_baseline_k": self.config.temperature_baseline_k,
            "temperature_setpoint_k": self.config.temperature_setpoint_k,
            "temperature_drift_max_k": self.config.temperature_drift_max_k,
            "ramp_rate": "unknown_preserved_by_native_controller",
            "quality_flags": [
                "sdk_values_server_cached_no_device_timestamp",
                "pm_pickoff_not_calibrated_sample_power",
                "sample_current_uncalibrated",
                "single_hysteresis_cycle"
                if task.targets_z_t == HYSTERESIS_TARGETS
                else "single_ordered_sweep",
                "optical_modulation_unverified",
            ],
        }
        deadline = self.clock() + self.config.max_campaign_s - self.config.cleanup_timeout_s - 30.0
        optical_opened = magnetic_opened = owned = False
        close_errors = []

        def emit(event):
            try:
                event_sink(event)
            except Exception as exc:
                result["evidence_errors"].append(f"{type(exc).__name__}: {exc}")

        def guard():
            if result["evidence_errors"]:
                raise ValueError("raw evidence persistence failed; stop acquisition")
            if self.clock() >= deadline:
                raise TimeoutError("campaign acquisition deadline exceeded")

        def magnetic_guard(value):
            method = getattr(self.magnet, "set_guard", None)
            if method:
                method(value)

        def protect(where):
            record = PilotEngine(self.optical, self.clock, self.sleep)._protect(where, 0.004)
            result["protection"].append(record)
            emit({"event": "output_protection", "record": record})
            return record["verified"]

        try:
            guard()
            self.optical.set_guard(deadline, None)
            optical_opened = True
            self.optical.open()
            result["preflight"] = self.optical.preflight()
            if (
                result["preflight"].get("ready") is not True
                or result["preflight"].get("laser_enabled") is not False
            ):
                raise ValueError("campaign does not own a laser-OFF preflighted station")
            owned = True
            if not protect("before_magnetic_open"):
                raise ValueError("initial optical protection failed")
            magnetic_guard(deadline)
            magnetic_opened = True
            result["magnetic_initial"] = self.magnet.open(writes=True)
            for index, z in enumerate(task.targets_z_t):
                guard()
                if not protect("before_field_" + str(index)):
                    raise ValueError("optical protection failed before changing field")
                magnetic_guard(deadline)
                field = self.magnet.move(z)
                guard()
                validate_state(field["state"], self.config, z, True)
                point = {
                    "point_index": index,
                    "target_z_t": z,
                    "field": field,
                    "session_close_semantics": "point_view_released_campaign_retains_hardware",
                }
                result["points"].append(point)
                emit({"event": "field_qualified", "point": dict(point)})
                guard()
                point["raw_reads"] = []
                view = PointView(
                    self.optical,
                    self.magnet,
                    self.config,
                    z,
                    deadline,
                    point["raw_reads"],
                    emit,
                    guard,
                    index,
                )
                try:
                    point["optical"] = PilotEngine(view, self.clock, self.sleep).run(
                        task.optical, approval
                    )
                except BaseException as exc:
                    point["optical"] = {
                        "status": "CANCELLED",
                        "error": f"{type(exc).__name__}: {exc}",
                        "samples": [],
                        "rejected_samples": [],
                        "acquisition_complete": False,
                        "protection_verified": False,
                        "close_error": None,
                        "partial_data_location": "point.raw_reads and sample_raw_captured events",
                    }
                    raise
                finally:
                    emit({"event": "optical_point_finished", "point": point})
                guard()
                accept_point(point, self.config)
            result["status"] = "COMPLETED"
        except BaseException as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            emit({"event": "campaign_error", "error": result["error"]})
        finally:
            cleanup_deadline = self.clock() + self.config.cleanup_timeout_s
            magnetic_guard(cleanup_deadline)
            if owned and not protect("campaign_final"):
                result["status"] = "UNKNOWN"
            if magnetic_opened:
                try:
                    if not getattr(self.magnet, "healthy", True):
                        raise ValueError("uncertain SDK child; no blind zero command")
                    result["zero"] = self.magnet.zero()
                    if (
                        result["zero"].get("zero_verified") is not True
                        or result["zero"].get("initial_control_restored") is not True
                    ):
                        raise ValueError("final zero or initial control mode is unverified")
                    validate_state(result["zero"]["state"], self.config, target=0.0)
                except BaseException as exc:
                    result["status"] = "UNKNOWN"
                    result["zero_error"] = f"{type(exc).__name__}: {exc}"
                try:
                    result["magnetic_close"] = self.magnet.close()
                except BaseException as exc:
                    close_errors.append("magnetic: " + f"{type(exc).__name__}: {exc}")
            if optical_opened:
                try:
                    self.optical.close()
                except BaseException as exc:
                    close_errors.append("optical: " + f"{type(exc).__name__}: {exc}")
            if close_errors:
                result["close_error"] = "; ".join(close_errors)
                result["status"] = "UNKNOWN"
            result["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
            emit(
                {
                    "event": "campaign_finished",
                    "status": result["status"],
                    "zero": result["zero"],
                    "close_error": result["close_error"],
                }
            )
            if result["evidence_errors"]:
                result["status"] = "UNKNOWN"
        return result


def validate_campaign(result, *, expected_task=None, expected_message_sha=None, require_raw=False):
    if result.get("status") != "COMPLETED":
        return {
            "accepted": False,
            "status": result.get("status"),
            "reason": "campaign incomplete/failed/unknown",
        }
    task = CampaignTask.model_validate_json(json_bytes(result["task"]))
    if expected_task is not None and task.model_dump(mode="json") != expected_task.model_dump(
        mode="json"
    ):
        raise ValueError("result differs from original central task")
    if expected_message_sha is not None and result.get("message_sha256") != expected_message_sha:
        raise ValueError("original central task message hash differs")
    if digest(task.model_dump(mode="json")) != result["task_sha256"]:
        raise ValueError("campaign task hash mismatch")
    if (
        result.get("close_error") is not None
        or not result.get("protection")
        or not all(p.get("verified") is True for p in result["protection"])
        or result.get("magnetic_close", {}).get("closed") is not True
    ):
        raise ValueError("campaign closure/protection failed")
    config = SimpleNamespace(
        temperature_baseline_k=result["temperature_baseline_k"],
        temperature_setpoint_k=180.0,
        temperature_drift_max_k=0.1,
    )
    points = result["points"]
    if [p["target_z_t"] for p in points] != list(task.targets_z_t):
        raise ValueError("campaign field order or point count differs")
    for index, point in enumerate(points):
        if point.get("point_index") != index:
            raise ValueError("point index mismatch")
        accept_point(point, config)
    zero = result["zero"]
    if zero.get("zero_verified") is not True or zero.get("initial_control_restored") is not True:
        raise ValueError("final zero or initial mode restoration failed")
    initial_mode = result["magnetic_initial"]["initial_state"]["field_control_enabled"]
    validate_state(zero["state"], config, target=0.0, require_control=initial_mode)
    if require_raw:
        events = result.get("magnetic_events")
        if (
            not events
            or result["magnetic_initial"].get("source_hashes") != SOURCE_SHA
            or result["magnetic_initial"].get("dll_sha256") != DLL_SHA
        ):
            raise ValueError("missing raw SDK/source provenance")
        requested, returned = {}, {}
        for event in events:
            if event.get("event") != "sdk_call":
                continue
            group = (
                requested
                if event.get("phase") == "requested"
                else returned
                if event.get("phase") == "returned"
                else None
            )
            ident = event.get("call_id")
            if group is None or not ident or ident in group:
                raise ValueError("invalid/duplicate raw SDK call record")
            group[ident] = event
        if not requested or set(requested) != set(returned):
            raise ValueError("incomplete raw SDK call records")
        names = []
        z_writes = []
        for ident, req in requested.items():
            ret = returned[ident]
            name = req["symbol"].removeprefix("AttoDRY_Interface_")
            if (
                name not in READS | WRITES
                or req["symbol"] != ret.get("symbol")
                or ret.get("return_code") != 0
                or ret.get("error")
            ):
                raise ValueError("raw SDK calls contain failed/unapproved commands")
            names.append(name)
            if name == "setUserMagneticFieldZ":
                z_writes.append(req["arguments_before"][0])
            if name == "setUserMagneticFieldX" and req["arguments_before"] != [0.0]:
                raise ValueError("raw SDK attempted a nonzero transverse-axis command")
        if z_writes != list(task.targets_z_t) or any(
            names.count(n) != 1
            for n in ("begin", "Connect", "Disconnect", "end", "sweepFieldToZero")
        ):
            raise ValueError("raw SDK target path or owned lifecycle differs")
        observations = zero.get("post_restore_zero_observations", [])
        if (
            len(observations) < 3
            or observations[-1]["observed_monotonic_s"] - observations[0]["observed_monotonic_s"]
            < 10
        ):
            raise ValueError("raw zero-field dwell evidence is incomplete")
        for observation in observations:
            validate_state(observation["state"], config, target=0.0, require_control=initial_mode)
        for axis in ("bx_t", "bz_t"):
            values = [o["state"]["field"][axis] for o in observations]
            if max(values) - min(values) > 0.0005:
                raise ValueError("raw final zero field is not stable")
        from .evidence import validate_raw_evidence

        validate_raw_evidence(result, config)
    return {
        "accepted": True,
        "points": len(task.targets_z_t),
        "samples": len(task.targets_z_t) * 6,
        "actual_zero_verified": True,
        "close_error": None,
    }
