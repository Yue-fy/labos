"""Deterministic simulated bench tests; these are not hardware acceptance tests."""

import hashlib
import json
import math
import threading

import pytest
from pydantic import ValidationError

from labos.pilot import PilotApproval, PilotCancelled, PilotEngine, PilotPlan


def plan(**changes):
    values = {
        "sample_id": "CrSBr 1",
        "mode": "combined",
        "laser_current_a": 0.0218,
        "power_limit_w": 0.000001,
        "reference_hz": 77.77,
    }
    return PilotPlan(**(values | changes))


def approval(**changes):
    values = {
        "enabled": True,
        "sample_id": "CrSBr 1",
        "laser_current_max_a": 0.0218,
        "power_limit_max_w": 0.000001,
        "reference_hz": 77.77,
        "max_phase_s": 30,
        "max_run_s": 120,
    }
    return PilotApproval(**(values | changes))


class NoDeviceAccess:
    """An authorization rejection must never reach the device boundary."""

    def __getattr__(self, name):
        pytest.fail(f"unauthorized device access: {name}")


@pytest.mark.parametrize(
    "changes",
    [
        {"enabled": False},
        {"sample_id": "another sample"},
        {"reference_hz": 78},
        {"laser_current_max_a": None},
        {"power_limit_max_w": None},
        {"laser_current_max_a": 0.020},
        {"power_limit_max_w": 0.0000004},
        {"max_phase_s": 29},
        {"max_run_s": 119},
    ],
)
def test_local_approval_rejects_before_any_device_io(changes):
    result = PilotEngine(NoDeviceAccess()).run(plan(), approval(**changes))
    assert result["status"] == "FAILED"
    assert result["samples"] == []
    assert result["cleanup"] == []
    assert result["error"]
    assert result["acquisition_complete"] is False
    assert result["protection_verified"] is False


def test_commissioning_defaults_disabled_and_requires_physical_facts():
    local = PilotApproval(sample_id="CrSBr 1", reference_hz=77.77,
                          max_phase_s=30, max_run_s=120)
    assert local.enabled is False
    with pytest.raises(ValueError):
        local.validate_plan(plan())
    with pytest.raises(ValidationError):
        PilotApproval(sample_id="CrSBr 1")


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
@pytest.mark.parametrize(
    "field",
    ["laser_current_a", "power_limit_w", "reference_hz", "interval_s", "settle_s",
     "phase_timeout_s", "max_run_s", "excitation_v_rms"],
)
def test_nonfinite_plans_cannot_reach_hardware(field, value):
    with pytest.raises(ValidationError):
        plan(**{field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"sample_id": "  "},
        {"mode": "legacy_program"},
        {"laser_current_a": None},
        {"laser_current_a": 0},
        {"power_limit_w": None},
        {"power_limit_w": -1},
        {"reference_hz": 0},
        {"excitation_v_rms": 0.005},
        {"samples_per_phase": 0},
        {"samples_per_phase": 11},
        {"samples_per_phase": 1.5},
        {"interval_s": -1},
        {"interval_s": 11},
        {"settle_s": 31},
        {"phase_timeout_s": 4},
        {"phase_timeout_s": 91},
        {"max_run_s": 4},
        {"max_run_s": 301},
        {"arbitrary_scpi": "OUTP ON"},
    ],
)
def test_invalid_plan_rejected(changes):
    with pytest.raises(ValidationError):
        plan(**changes)


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
@pytest.mark.parametrize(
    "field",
    ["laser_current_max_a", "power_limit_max_w", "reference_hz", "max_phase_s",
     "max_run_s", "excitation_v_rms"],
)
def test_nonfinite_local_limits_are_rejected(field, value):
    with pytest.raises(ValidationError):
        approval(**{field: value})


def test_dark_hall_needs_no_light_approval_and_rejects_light_instructions():
    dark = plan(mode="dark_hall", laser_current_a=None, power_limit_w=None)
    local = approval(laser_current_max_a=None, power_limit_max_w=None)
    assert local.validate_plan(dark) is None
    with pytest.raises(ValidationError):
        plan(mode="dark_hall")


def test_constructed_invalid_models_are_revalidated_before_device_io():
    invalid = plan().model_copy(update={"reference_hz": math.nan})
    result = PilotEngine(NoDeviceAccess()).run(invalid, approval())
    assert result["status"] == "FAILED"
    assert result["cleanup"] == []


class SimulatedClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class SimulatedBench:
    """A physical state model at the injected I/O boundary, not a driver mock."""

    def __init__(self, clock=None, failures=None, durations=None):
        self.clock = clock or SimulatedClock()
        self.failures = failures or {}
        self.durations = durations or {}
        self.counts = {}
        self.history = []
        self.laser_enabled = False
        self.excitation_v_rms = 0.004
        self.opened = False
        self.phase = None

    def operation(self, method, **values):
        self.history.append({"operation": method, **values})
        self.counts[method] = self.counts.get(method, 0) + 1
        self.clock.now += self.durations.get((method, self.counts[method]),
                                             self.durations.get(method, 0))
        fault = self.failures.get((method, self.counts[method]))
        if isinstance(fault, BaseException):
            raise fault
        return fault

    def open(self):
        self.operation("open")
        self.opened = True

    def preflight(self):
        replacement = self.operation("preflight")
        if replacement is not None:
            return replacement
        return {"ready": True, "laser_enabled": self.laser_enabled,
                "identities": {"excitation": "SIMULATED SR830", "laser": "SIMULATED CLD"},
                "station_status": {"lease": "labos", "fault": False}}

    def configure(self, phase, pilot_plan):
        assert self.opened
        assert self.laser_enabled is False
        self.operation("configure", phase=phase, excitation_v_rms=pilot_plan.excitation_v_rms)
        self.phase = phase
        self.excitation_v_rms = pilot_plan.excitation_v_rms

    def laser_on(self, current_a):
        assert self.phase == "illuminated"
        self.operation("laser_on", current_a=current_a)
        self.laser_enabled = True

    def read_sample(self, phase):
        assert self.laser_enabled is (phase == "illuminated")
        replacement = self.operation("read_sample", phase=phase)
        if replacement is not None:
            return replacement
        sample = {"channels": {"xx": {"x_v": 1e-6, "y_v": -2e-7, "r_v": 1.02e-6,
                                        "phase_deg": -11.3, "harmonic": 1,
                                        "reference_hz": 77.77, "time_constant_s": 0.3,
                                        "status_flags": {"overload": False}},
                               "xy": {"x_v": 3e-8, "y_v": 1e-8},
                               "aux": {"x_v": 1e-9, "y_v": 0.0}}}
        if phase == "illuminated":
            sample.update(power_w=0.000000483, power_plane="PM pickoff")
        return sample

    def laser_off(self):
        replacement = self.operation("laser_off")
        result = replacement or {"laser_off_verified": True}
        if result.get("laser_off_verified") is True:
            self.laser_enabled = False
        return result

    def protect_excitation(self):
        replacement = self.operation("protect_excitation")
        result = replacement or {"minimum_excitation_verified": True, "actual_v_rms": 0.004}
        if result.get("minimum_excitation_verified") is True:
            self.excitation_v_rms = result.get("actual_v_rms")
        return result

    def close(self):
        self.operation("close")
        self.opened = False


def run_simulated(pilot_plan=None, bench=None, **kwargs):
    bench = bench or SimulatedBench()
    result = PilotEngine(bench, clock=bench.clock, sleep=bench.clock.sleep).run(
        pilot_plan or plan(), approval(), **kwargs)
    return result, bench


@pytest.mark.parametrize(
    "mode,phases",
    [("photoresponse", ["dark_baseline", "illuminated"]),
     ("combined", ["dark_baseline", "illuminated", "dark_hall_2f"]),
     ("dark_hall", ["dark_hall_2f"])],
)
def test_finite_phases_end_laser_off_and_at_terminal_minimum(mode, phases):
    changes = {"mode": mode, "samples_per_phase": 2, "interval_s": 0.2, "settle_s": 0.1}
    if mode == "dark_hall":
        changes.update(laser_current_a=None, power_limit_w=None)
    result, bench = run_simulated(plan(**changes))
    assert result["status"] == "COMPLETED"
    assert result["acquisition_complete"] is True
    assert result["protection_verified"] is True
    assert [sample["phase"] for sample in result["samples"]] == [p for p in phases for _ in (0, 1)]
    assert len(result["cleanup"]) == len(phases) + 1
    assert all(item["verified"] is True for item in result["cleanup"])
    assert bench.laser_enabled is False
    assert bench.excitation_v_rms == 0.004
    assert bench.opened is False
    assert [event["phase"] for event in bench.history if event["operation"] == "configure"] == phases
    assert [event["excitation_v_rms"] for event in bench.history
            if event["operation"] == "configure"] == [0.004] * len(phases)
    assert bench.counts.get("laser_on", 0) == (0 if mode == "dark_hall" else 1)
    for index, event in enumerate(bench.history):
        if event["operation"] == "configure" and index > 2:
            assert bench.history[index - 2]["operation"] == "laser_off"
            assert bench.history[index - 1]["operation"] == "protect_excitation"


def test_artifact_preserves_raw_channels_readbacks_and_approval_hashes():
    result, _ = run_simulated()
    assert result["sample_id"] == "CrSBr 1"
    assert result["preflight"]["identities"]["excitation"] == "SIMULATED SR830"
    assert result["samples"][1]["channels"]["xx"]["x_v"] == 1e-6
    assert result["samples"][1]["power_w"] == 0.000000483
    assert result["samples"][1]["power_plane"] == "PM pickoff"
    assert result["samples"][0]["timestamp_monotonic_s"] == 100.0
    assert result["samples"][0]["elapsed_s"] == 0.0
    assert result["samples"][0]["sample_index"] == 0
    assert result["cleanup"][-1]["protect_excitation"]["actual_v_rms"] == 0.004
    expected_plan_hash = hashlib.sha256(json.dumps(plan().model_dump(mode="json"),
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert result["plan_sha256"] == expected_plan_hash
    assert len(result["approval_sha256"]) == 64
    encoded = json.dumps(result, allow_nan=False)
    assert "sample_current" not in encoded
    assert "spectrum" not in encoded
    assert "excitation_off" not in encoded


@pytest.mark.parametrize("preflight", [
    {"ready": False, "laser_enabled": False},
    {"ready": True, "laser_enabled": True},
    {"ready": True},
    {"ready": "yes", "laser_enabled": False},
])
def test_preflight_refusal_does_not_take_over_or_disable_foreign_output(preflight):
    bench = SimulatedBench(failures={("preflight", 1): preflight})
    bench.laser_enabled = True
    result, bench = run_simulated(bench=bench)
    assert result["status"] == "FAILED"
    assert result["samples"] == []
    assert result["cleanup"] == []
    assert bench.laser_enabled is True
    assert [item["operation"] for item in bench.history] == ["open", "preflight", "close"]


def test_over_power_is_not_accepted_and_stops_before_later_phase():
    over_power = {"channels": {"xx": {"x_v": 1e-6}}, "power_w": 0.000002}
    bench = SimulatedBench(failures={("read_sample", 2): over_power})
    result, bench = run_simulated(bench=bench)
    assert result["status"] == "FAILED"
    assert [sample["phase"] for sample in result["samples"]] == ["dark_baseline"]
    assert "power" in result["error"].lower()
    assert result["protection_verified"] is True
    assert result["acquisition_complete"] is False
    assert bench.counts["configure"] == 2
    assert bench.laser_enabled is False
    assert bench.excitation_v_rms == 0.004
    rejected = result["rejected_samples"][0]
    assert rejected["phase"] == "illuminated"
    assert rejected["raw"]["power_w"] == 0.000002
    assert "power" in rejected["reason"].lower()


@pytest.mark.parametrize("sample", [
    {"channels": {"xx": {"x_v": math.nan}}, "power_w": 1e-7},
    {"channels": {"xx": {"x_v": 1e-6}}, "power_w": math.inf},
    {"channels": {"xx": {"x_v": 1e-6}}, "power_w": -1e-7},
    {"channels": {"xx": {"x_v": 1e-6}}},
    {"channels": {}},
    {"channels": {"xx": {}}},
    {"channels": {"xx": [1e-6]}},
    {"channels": {"xx": {"x_v": object()}}, "power_w": 1e-7},
    {"channels": {"xx": {"x_v": 1e-6}}, "power_w": True},
    {"channels": {"xx": {"x_v": 1e-6}}, "power_w": "1e-7"},
    [1, 2, 3],
])
def test_malformed_samples_keep_previous_data_and_clean_up(sample):
    result, bench = run_simulated(bench=SimulatedBench(failures={("read_sample", 2): sample}))
    assert result["status"] == "FAILED"
    assert len(result["samples"]) == 1
    assert result["protection_verified"] is True
    assert bench.laser_enabled is False
    assert bench.excitation_v_rms == 0.004
    assert len(result["rejected_samples"]) == 1
    assert result["rejected_samples"][0]["reason"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("method,occurrence,accepted", [
    ("configure", 1, 0), ("laser_on", 1, 1), ("read_sample", 2, 1),
])
def test_owned_backend_failures_preserve_data_and_independent_protection(method, occurrence, accepted):
    bench = SimulatedBench(failures={(method, occurrence): RuntimeError("simulated bus fault")})
    result, bench = run_simulated(bench=bench)
    assert result["status"] == "FAILED"
    assert "simulated bus fault" in result["error"]
    assert len(result["samples"]) == accepted
    assert result["protection_verified"] is True
    assert bench.laser_enabled is False
    assert bench.excitation_v_rms == 0.004
    assert bench.history[-3:] == [{"operation": "laser_off"},
                                  {"operation": "protect_excitation"},
                                  {"operation": "close"}]


@pytest.mark.parametrize("method,bad_result", [
    ("laser_off", {"laser_off_verified": False}),
    ("laser_off", RuntimeError("laser readback failed")),
    ("protect_excitation", {"minimum_excitation_verified": False, "actual_v_rms": 0.01}),
    ("protect_excitation", {"minimum_excitation_verified": True, "actual_v_rms": 0.01}),
    ("protect_excitation", {"minimum_excitation_verified": True}),
    ("protect_excitation", RuntimeError("source readback failed")),
])
def test_failed_phase_protection_is_unknown_and_never_starts_later_phase(method, bad_result):
    result, bench = run_simulated(bench=SimulatedBench(failures={(method, 1): bad_result}))
    assert result["status"] == "UNKNOWN"
    assert result["protection_verified"] is False
    assert result["acquisition_complete"] is False
    assert bench.counts["configure"] == 1
    assert bench.counts["laser_off"] == 2
    assert bench.counts["protect_excitation"] == 2
    assert result["cleanup"][0]["verified"] is False
    assert result["cleanup"][-1]["verified"] is True
    assert result["error"]


def test_two_failed_cleanup_actions_are_recorded_independently():
    bench = SimulatedBench(failures={
        ("laser_off", 1): RuntimeError("laser protection fault"),
        ("protect_excitation", 1): RuntimeError("excitation protection fault"),
    })
    result, _ = run_simulated(bench=bench)
    assert result["status"] == "UNKNOWN"
    first = result["cleanup"][0]
    assert "laser protection fault" in first["laser_off"]["error"]
    assert "excitation protection fault" in first["protect_excitation"]["error"]


def test_final_protection_failure_dominates_completed_acquisition():
    bench = SimulatedBench(failures={
        ("protect_excitation", 4): RuntimeError("final minimum readback failed"),
    })
    result, _ = run_simulated(bench=bench)
    assert result["status"] == "UNKNOWN"
    assert result["acquisition_complete"] is True
    assert result["protection_verified"] is False
    assert len(result["samples"]) == 3


def test_pre_cancelled_run_performs_no_device_io():
    token = threading.Event()
    token.set()
    result = PilotEngine(NoDeviceAccess()).run(plan(), approval(), cancel=token)
    assert result["status"] == "CANCELLED"
    assert result["samples"] == []


def test_cancellation_during_settling_cleans_up_before_any_sample():
    bench = SimulatedBench()
    result, bench = run_simulated(plan(settle_s=2), bench,
                                 cancel=lambda: bench.clock.now >= 100.5)
    assert result["status"] == "CANCELLED"
    assert result["samples"] == []
    assert result["protection_verified"] is True
    assert bench.clock.now < 101
    assert bench.laser_enabled is False


@pytest.mark.parametrize("method", ["configure", "laser_on", "read_sample"])
def test_phase_deadline_checked_after_blocking_device_calls(method):
    bench = SimulatedBench(durations={method: 6})
    result, bench = run_simulated(plan(phase_timeout_s=5), bench)
    assert result["status"] == "FAILED"
    assert "deadline" in result["error"].lower()
    assert result["protection_verified"] is True
    assert all(sample["phase"] == "dark_baseline" for sample in result["samples"])
    assert bench.laser_enabled is False
    if method == "read_sample":
        assert len(result["samples"]) == 0
        rejected = result["rejected_samples"][0]
        assert rejected["raw"]["channels"]["xx"]["x_v"] == 1e-6
        assert "deadline" in rejected["reason"].lower()


def test_total_deadline_includes_prior_phase_and_checks_before_next_phase():
    bench = SimulatedBench(durations={"read_sample": 3})
    result, bench = run_simulated(plan(max_run_s=5), bench)
    assert result["status"] == "FAILED"
    assert [sample["phase"] for sample in result["samples"]] == ["dark_baseline"]
    assert bench.counts["configure"] == 2
    assert bench.laser_enabled is False


def test_keyboard_interrupt_during_owned_io_still_protects_both_outputs_and_closes():
    bench = SimulatedBench(failures={("read_sample", 2): KeyboardInterrupt()})
    with pytest.raises(KeyboardInterrupt):
        run_simulated(bench=bench)
    assert bench.laser_enabled is False
    assert bench.excitation_v_rms == 0.004
    assert bench.opened is False
    assert bench.history[-3:] == [{"operation": "laser_off"},
                                  {"operation": "protect_excitation"},
                                  {"operation": "close"}]


def test_phase_deadline_includes_protection_and_prevents_next_phase():
    bench = SimulatedBench(durations={"laser_off": 3, "protect_excitation": 3})
    result, bench = run_simulated(plan(phase_timeout_s=5), bench)
    assert result["status"] == "FAILED"
    assert bench.counts["configure"] == 1
    assert result["protection_verified"] is True
    assert len(result["samples"]) == 1


@pytest.mark.parametrize("method", ["open", "preflight"])
def test_partial_initialization_closes_without_changing_unowned_outputs(method):
    bench = SimulatedBench(failures={(method, 1): RuntimeError("initialization failed")})
    bench.laser_enabled = True
    result, bench = run_simulated(bench=bench)
    assert result["status"] == "FAILED"
    assert result["cleanup"] == []
    assert bench.laser_enabled is True
    assert bench.counts["close"] == 1
    assert bench.counts.get("laser_off", 0) == 0
    assert bench.counts.get("protect_excitation", 0) == 0


def test_failed_close_is_recorded_as_unknown_after_both_protections():
    result, bench = run_simulated(bench=SimulatedBench(failures={
        ("close", 1): RuntimeError("connection release failed"),
    }))
    assert result["status"] == "UNKNOWN"
    assert result["acquisition_complete"] is True
    assert result["protection_verified"] is True
    assert "connection release failed" in result["close_error"]
    assert bench.laser_enabled is False
    assert bench.excitation_v_rms == 0.004


@pytest.mark.parametrize("method,readback", [
    ("laser_off", {"laser_off_verified": "true"}),
    ("laser_off", {"laser_off_verified": 1}),
    ("laser_off", [True]),
    ("protect_excitation", {"minimum_excitation_verified": True, "actual_v_rms": math.nan}),
    ("protect_excitation", {"minimum_excitation_verified": True, "actual_v_rms": "0.004"}),
])
def test_malformed_protection_proof_is_unknown(method, readback):
    result, bench = run_simulated(bench=SimulatedBench(failures={(method, 1): readback}))
    assert result["status"] == "UNKNOWN"
    assert result["protection_verified"] is False
    assert bench.counts["configure"] == 1
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("field", [
    "laser_current_a", "power_limit_w", "reference_hz", "interval_s", "settle_s",
    "phase_timeout_s", "max_run_s", "samples_per_phase",
])
def test_physical_numeric_fields_do_not_accept_boolean_configuration(field):
    with pytest.raises(ValidationError):
        plan(**{field: True})


@pytest.mark.parametrize("field", [
    "laser_current_max_a", "power_limit_max_w", "reference_hz", "max_phase_s", "max_run_s",
])
def test_local_physical_limits_do_not_accept_boolean_configuration(field):
    with pytest.raises(ValidationError):
        approval(**{field: True})


def test_unicode_plan_hash_uses_utf8_canonical_json():
    pilot_plan = plan(sample_id="CrSBr \u6837\u54c1 1")
    local = approval(sample_id="CrSBr \u6837\u54c1 1")
    bench = SimulatedBench()
    result = PilotEngine(bench, clock=bench.clock, sleep=bench.clock.sleep).run(pilot_plan, local)
    encoded = json.dumps(pilot_plan.model_dump(mode="json"), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    assert result["plan_sha256"] == hashlib.sha256(encoded).hexdigest()
    assert result["status"] == "COMPLETED"


def test_deadline_during_final_protection_keeps_completed_data_and_reports_failure():
    bench = SimulatedBench(durations={("laser_off", 4): 6})
    result, bench = run_simulated(plan(max_run_s=5), bench)
    assert result["status"] == "FAILED"
    assert "deadline" in result["error"].lower()
    assert result["acquisition_complete"] is True
    assert result["protection_verified"] is True
    assert bench.opened is False


def test_nonfinite_rejected_reading_keeps_a_finite_error_diagnostic():
    raw = {"channels": {"xx": {"x_v": math.nan}}, "power_w": 1e-7}
    result, _ = run_simulated(bench=SimulatedBench(failures={("read_sample", 2): raw}))
    rejected = result["rejected_samples"][0]
    assert rejected["raw"] is None
    assert "nonfinite" in rejected["raw_error"].lower()
    assert rejected["phase"] == "illuminated"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("raw_sample,finite", [
    ({"power_w": 0.000002, "power_overrange": True, "status": "PM overload"}, True),
    ({"power_w": math.nan, "power_overrange": True}, False),
    ({"power_w": object()}, False),
])
def test_adapter_read_exception_preserves_bounded_raw_evidence_and_protects_outputs(raw_sample, finite):
    class SimulatedReadFault(RuntimeError):
        def __init__(self, raw):
            super().__init__("simulated power/status readback fault")
            self.raw_sample = raw

    bench = SimulatedBench(failures={("read_sample", 2): SimulatedReadFault(raw_sample)})
    result, bench = run_simulated(bench=bench)
    assert result["status"] == "FAILED"
    assert result["protection_verified"] is True
    assert result["acquisition_complete"] is False
    assert [sample["phase"] for sample in result["samples"]] == ["dark_baseline"]
    assert len(result["rejected_samples"]) == 1
    rejected = result["rejected_samples"][0]
    assert rejected["phase"] == "illuminated"
    assert rejected["sample_index"] == 0
    assert "simulated power/status readback fault" in rejected["reason"]
    if finite:
        assert rejected["raw"] == {"power_w": 0.000002, "power_overrange": True,
                                   "status": "PM overload"}
    else:
        assert rejected["raw"] is None
        assert rejected["raw_error"]
    assert bench.counts["configure"] == 2
    assert bench.laser_enabled is False
    assert bench.excitation_v_rms == 0.004
    assert bench.opened is False
    json.dumps(result, allow_nan=False)


class SimulatedGuardedBench(SimulatedBench):
    """Budget individual inner queries, leaving independent protection available."""

    def __init__(self, *args, guarded_operation="read_sample", cancel_after_queries=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.guarded_operation = guarded_operation
        self.cancel_after_queries = cancel_after_queries
        self.guard_deadline = None
        self.guard_cancel = None
        self.guard_history = []
        self.inner_queries = 0

    def set_guard(self, deadline, cancel):
        self.guard_deadline = deadline
        self.guard_cancel = cancel
        self.guard_history.append(deadline)

    def inner_io(self):
        for _ in range(100):
            if self.guard_deadline is not None:
                if self.guard_cancel is not None:
                    cancelled = (self.guard_cancel() if callable(self.guard_cancel)
                                 else self.guard_cancel.is_set())
                    if cancelled:
                        raise PilotCancelled("simulated inner I/O cancellation")
                if self.clock() >= self.guard_deadline:
                    raise TimeoutError("simulated inner I/O deadline")
            self.inner_queries += 1
            self.clock.sleep(1)
            if self.cancel_after_queries == self.inner_queries:
                self.guard_cancel.set()

    def operation(self, method, **values):
        replacement = super().operation(method, **values)
        if method == self.guarded_operation:
            self.inner_io()
        return replacement


@pytest.mark.parametrize("guarded_operation", ["configure", "read_sample"])
def test_adapter_inner_io_stops_at_phase_budget_and_independent_cleanup_runs(guarded_operation):
    bench = SimulatedGuardedBench(guarded_operation=guarded_operation)
    result, bench = run_simulated(plan(phase_timeout_s=5), bench)
    assert result["status"] == "FAILED"
    assert "deadline" in result["error"]
    assert bench.inner_queries == 5
    assert result["protection_verified"] is True
    assert bench.counts["configure"] == 1
    assert bench.counts["laser_off"] == 2
    assert bench.counts["protect_excitation"] == 2
    assert bench.laser_enabled is False
    assert bench.opened is False


@pytest.mark.parametrize("guarded_operation", ["open", "preflight"])
def test_adapter_inner_initialization_io_uses_global_budget_without_taking_over(guarded_operation):
    bench = SimulatedGuardedBench(guarded_operation=guarded_operation)
    bench.laser_enabled = True
    result, bench = run_simulated(plan(max_run_s=5), bench)
    assert result["status"] == "FAILED"
    assert bench.inner_queries == 5
    assert result["cleanup"] == []
    assert bench.laser_enabled is True
    assert bench.counts.get("configure", 0) == 0
    assert bench.counts["close"] == 1


def test_adapter_inner_io_cancellation_is_classified_cancelled_and_protects_outputs():
    token = threading.Event()
    bench = SimulatedGuardedBench(cancel_after_queries=2)
    result, bench = run_simulated(bench=bench, cancel=token)
    assert result["status"] == "CANCELLED"
    assert "inner I/O cancellation" in result["error"]
    assert bench.inner_queries == 2
    assert result["protection_verified"] is True
    assert result["samples"] == []
    assert bench.counts["laser_off"] == 2
    assert bench.counts["protect_excitation"] == 2
    assert bench.laser_enabled is False
    assert bench.opened is False


def test_adapter_guard_resets_to_global_budget_between_phases():
    bench = SimulatedGuardedBench(guarded_operation=None)
    result, bench = run_simulated(plan(phase_timeout_s=5, settle_s=1), bench)
    assert result["status"] == "COMPLETED"
    # Global run deadline is restored before each new phase-specific deadline.
    assert bench.guard_history[:4] == [220.0, 220.0, 220.0, 105.0]
    assert (220.0, 106.0) in list(zip(bench.guard_history, bench.guard_history[1:]))
    assert (220.0, 107.0) in list(zip(bench.guard_history, bench.guard_history[1:]))
