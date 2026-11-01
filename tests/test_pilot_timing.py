"""Engine evidence and admission checks at a simulated device boundary."""

import json

import pytest

from labos.pilot import PilotEngine
from test_pilot import SimulatedBench, approval, plan, run_simulated


def stage(result, name, phase=None):
    return next(record for record in result["timing"]["stages"]
                if record["stage"] == name and record["phase"] == phase)


def test_startup_timing_accounts_for_delayed_open_and_preflight():
    result, bench = run_simulated(bench=SimulatedBench(durations={"open": 2, "preflight": 3}))
    assert result["status"] == "COMPLETED"
    assert stage(result, "open") == {
        "stage": "open", "phase": None, "started_elapsed_s": 0,
        "duration_s": 2, "outcome": "completed"}
    assert stage(result, "preflight")["started_elapsed_s"] == 2
    assert stage(result, "preflight")["duration_s"] == 3
    assert result["timing"]["total_elapsed_s"] == bench.clock() - 100 == 5
    assert result["failure"] is None


@pytest.mark.parametrize("method,occurrence,phase,accepted", [
    ("open", 1, None, 0), ("preflight", 1, None, 0),
    ("configure", 1, "dark_baseline", 0), ("laser_on", 1, "illuminated", 1),
])
def test_first_fault_stage_survives_cleanup_and_preserves_ownership(
        method, occurrence, phase, accepted):
    bench = SimulatedBench(failures={(method, occurrence): RuntimeError("original fault"),
                                     ("close", 1): ValueError("close fault")})
    result, bench = run_simulated(bench=bench)
    assert result["failure"]["stage"] == method
    assert result["failure"]["phase"] == phase
    assert result["failure"]["exception_type"] == "RuntimeError"
    assert stage(result, method, phase)["outcome"] == "failed"
    assert "original fault" in result["error"]
    assert result["status"] == "UNKNOWN"
    assert len(result["samples"]) == accepted
    assert bool(result["cleanup"]) is (phase is not None)
    assert bench.counts["close"] == 1


@pytest.mark.parametrize("changes,durations,scope", [
    ({"max_run_s": 5}, {"open": 6}, "run"),
    ({"phase_timeout_s": 5}, {"configure": 6}, "phase"),
    ({"phase_timeout_s": 5, "max_run_s": 5}, {"configure": 6}, "run_and_phase"),
])
def test_deadline_snapshot_uses_fault_time_before_cleanup(changes, durations, scope):
    bench = SimulatedBench(durations=durations | {"laser_off": 40, "close": 40})
    result, _ = run_simulated(plan(**changes), bench)
    assert result["failure"]["exception_type"] == "TimeoutError"
    assert result["failure"]["deadline"]["scope"] == scope
    assert result["failure"]["elapsed_s"] == 6
    assert result["timing"]["total_elapsed_s"] > 40
    assert result["status"] == "FAILED"


def test_native_timeout_with_time_left_is_not_deadline_exhaustion():
    bench = SimulatedBench(failures={("configure", 1): TimeoutError("vendor timeout")})
    result, _ = run_simulated(bench=bench)
    assert result["failure"]["deadline"]["scope"] is None
    assert result["failure"]["exception_type"] == "TimeoutError"
    assert result["error"] == "TimeoutError: vendor timeout"


def test_ready_preflight_expiring_run_preserves_existing_ownership_cleanup():
    result, bench = run_simulated(plan(max_run_s=5),
                                  SimulatedBench(durations={"preflight": 6}))
    assert result["status"] == "FAILED"
    assert result["failure"]["stage"] == "preflight"
    assert result["protection_verified"] is True
    assert [item["scope"] for item in result["cleanup"]] == ["final"]
    assert bench.counts.get("configure", 0) == 0


def test_pre_cancelled_run_does_not_probe_optional_diagnostics():
    class UnopenedBench(SimulatedBench):
        def __init__(self):
            super().__init__()
            self.diagnostic_probes = 0

        @property
        def diagnostics(self):
            self.diagnostic_probes += 1
            raise RuntimeError("device boundary must remain untouched")

    bench = UnopenedBench()
    result, _ = run_simulated(bench=bench, cancel=lambda: True)
    assert result["status"] == "CANCELLED"
    assert bench.diagnostic_probes == 0
    assert bench.history == []


@pytest.mark.parametrize("method", ["laser_off", "protect_excitation", "close"])
def test_cleanup_failure_stage_is_evident_without_skipping_other_protection(method):
    result, bench = run_simulated(bench=SimulatedBench(
        failures={(method, 1): RuntimeError("release fault")}))
    assert result["status"] == "UNKNOWN"
    assert result["failure"]["stage"] == method
    assert stage(result, method, None if method == "close" else "dark_baseline")[
        "outcome"] == "failed"
    assert bench.counts["laser_off"] >= 2
    assert bench.counts["protect_excitation"] >= 2
    assert bench.counts["close"] == 1


def test_unverified_final_readback_has_failure_metadata_after_complete_acquisition():
    result, bench = run_simulated(bench=SimulatedBench(failures={
        ("laser_off", 4): {"laser_off_verified": False},
    }))
    assert result["status"] == "UNKNOWN"
    assert result["acquisition_complete"] is True
    assert result["failure"]["stage"] == "final_protection"
    assert result["failure"]["phase"] == "final"
    assert result["failure"]["exception_type"] == "_ProtectionFailure"
    assert bench.counts["protect_excitation"] == 4
    assert bench.opened is False


@pytest.mark.parametrize("observer_error", [RuntimeError("observer"), KeyboardInterrupt()])
def test_observer_receives_copies_and_cannot_interrupt_protection(observer_error):
    events = []

    def observer(record):
        events.append(dict(record))
        record["stage"] = "tampered"
        raise observer_error

    bench = SimulatedBench()
    result = PilotEngine(bench, clock=bench.clock, sleep=bench.clock.sleep,
                         observer=observer).run(plan(), approval())
    assert result["status"] == "COMPLETED"
    assert result["protection_verified"] is True
    assert bench.opened is False
    assert [event for event in events if event["outcome"] != "started"] == result[
        "timing"]["stages"]
    assert stage(result, "close")["outcome"] == "completed"


def test_stage_evidence_is_bounded_with_explicit_dropped_count():
    from labos.pilot_diagnostics import RunEvidence

    bench = SimulatedBench()
    result = {"failure": None}
    events = []
    evidence = RunEvidence(result, bench.clock, bench.clock(), observer=events.append)
    for _ in range(300):
        with evidence.stage("sample", "dark_baseline"):
            bench.clock.sleep(0.01)
    assert len(result["timing"]["stages"]) == 256
    assert result["timing"]["dropped_count"] == 44
    assert len(events) == 600
    assert all(len(record) == 5 for record in events)
    json.dumps(result, allow_nan=False)


def test_observer_announces_blocking_stages_before_device_calls():
    bench = SimulatedBench()
    starts = []

    def observer(record):
        if record["outcome"] == "started" and record["stage"] in {
                "open", "preflight", "configure", "sample"}:
            operation = "read_sample" if record["stage"] == "sample" else record["stage"]
            starts.append((operation, bench.counts.get(operation, 0)))

    result = PilotEngine(bench, clock=bench.clock, sleep=bench.clock.sleep,
                         observer=observer).run(plan(), approval())
    assert result["status"] == "COMPLETED"
    assert starts == [("open", 0), ("preflight", 0), ("configure", 0), ("read_sample", 0),
                      ("configure", 1), ("read_sample", 1),
                      ("configure", 2), ("read_sample", 2)]


@pytest.mark.parametrize("method", ["open", "preflight", "configure"])
def test_observer_cannot_dispatch_acquisition_after_consuming_run_budget(method):
    bench = SimulatedBench()

    def observer(record):
        if record["stage"] == method and record["outcome"] == "started":
            bench.clock.sleep(6)

    result = PilotEngine(bench, clock=bench.clock, sleep=bench.clock.sleep,
                         observer=observer).run(plan(max_run_s=5), approval())
    assert result["status"] == "FAILED"
    assert bench.counts.get(method, 0) == 0
    assert result["failure"]["stage"] == method
    assert bool(result["cleanup"]) is (method == "configure")
    assert bench.opened is False


@pytest.mark.parametrize("changes,durations,required,remaining", [
    ({"max_run_s": 10, "samples_per_phase": 2, "settle_s": 1, "interval_s": 1},
     {("read_sample", 1): 1, ("read_sample", 2): 3}, 8, 4),
    ({"phase_timeout_s": 5, "settle_s": 1, "interval_s": 1,
      "samples_per_phase": 2}, {"read_sample": 1, ("configure", 2): 3}, 4, 2),
    ({"max_run_s": 6}, {"read_sample": 3}, 3, 3),
])
def test_insufficient_illumination_budget_preserves_baseline_and_never_enables(
        changes, durations, required, remaining):
    result, bench = run_simulated(plan(**changes), SimulatedBench(durations=durations))
    assert bench.counts.get("laser_on", 0) == 0
    assert result["status"] == "FAILED"
    assert result["protection_verified"] is True
    assert len(result["samples"]) == changes.get("samples_per_phase", 1)
    assert all(sample["phase"] == "dark_baseline" for sample in result["samples"])
    check = result["budget_checks"][0]
    assert check["provenance"] == "observed_baseline_estimate"
    assert check["required_s"] == required
    assert check["remaining_effective_s"] == remaining
    if "max_run_s" in changes:
        assert check["remaining_phase_s"] == 30
        assert check["remaining_run_s"] == remaining
    assert check["admitted"] is False
    assert result["failure"]["stage"] == "illumination_budget"


@pytest.mark.parametrize("duration", [0, 0.5])
def test_affordable_and_zero_duration_samples_remain_valid(duration):
    result, bench = run_simulated(plan(samples_per_phase=2, settle_s=0.1, interval_s=0.1),
                                  SimulatedBench(durations={"read_sample": duration}))
    assert result["status"] == "COMPLETED"
    assert len(result["samples"]) == 6
    assert bench.counts["laser_on"] == 1
    assert result["budget_checks"][0]["admitted"] is True
    assert result["budget_checks"][0]["baseline_max_read_s"] == duration


def test_observer_time_before_enable_is_included_in_final_admission():
    bench = SimulatedBench(durations={"read_sample": 1})

    def observer(record):
        if record["stage"] == "laser_on" and record["outcome"] == "started":
            bench.clock.sleep(8.5)

    result = PilotEngine(bench, clock=bench.clock, sleep=bench.clock.sleep,
                         observer=observer).run(plan(max_run_s=10), approval())
    assert result["status"] == "FAILED"
    assert result["protection_verified"] is True
    assert bench.counts.get("laser_on", 0) == 0
    assert result["budget_checks"][-1]["remaining_effective_s"] == 0.5
    assert result["budget_checks"][-1]["admitted"] is False


def test_optional_diagnostics_capture_original_fault_and_post_cleanup_copies():
    class DiagnosticBench(SimulatedBench):
        def diagnostics(self):
            return {"last_operation": self.history[-1]["operation"]}

    bench = DiagnosticBench(failures={("configure", 1): RuntimeError("original")})
    result, _ = run_simulated(bench=bench)
    assert result["device_diagnostics"]["before_cleanup"] == {"last_operation": "configure"}
    assert result["device_diagnostics"]["after_cleanup"] == {"last_operation": "close"}
    assert result["failure"]["stage"] == "configure"


@pytest.mark.parametrize("diagnostic", [RuntimeError("diagnostics"), {"bad": object()},
                                        {"too_large": "x" * 70000}])
def test_invalid_optional_diagnostics_cannot_replace_failure_or_skip_cleanup(diagnostic):
    class DiagnosticBench(SimulatedBench):
        def diagnostics(self):
            if isinstance(diagnostic, BaseException):
                raise diagnostic
            return diagnostic

    result, bench = run_simulated(bench=DiagnosticBench(
        failures={("configure", 1): RuntimeError("original")}))
    assert result["error"] == "RuntimeError: original"
    assert result["failure"]["stage"] == "configure"
    assert result["protection_verified"] is True
    assert bench.opened is False
    assert result["device_diagnostics"]["before_cleanup"] is None
    json.dumps(result, allow_nan=False)
