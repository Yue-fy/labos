"""Rehearse the finite engine offline; all readings and approvals are synthetic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from labos import __version__
from labos.pilot import PilotApproval, PilotEngine, PilotPlan


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class SyntheticBench:
    """Stateful device boundary with deterministic delays and injected faults.

    This adapter has no native device factory, driver imports or network client.
    Its successful readbacks are invented values, never instrument observations.
    """

    def __init__(self, scenario):
        self.scenario = scenario
        self.clock = FakeClock()
        self.counts = {}
        self.opened = False
        self.laser_enabled = False
        self.excitation_v_rms = 0.004

    def record(self, name):
        self.counts[name] = self.counts.get(name, 0) + 1

    def open(self):
        self.record("open")
        self.opened = True
        if self.scenario == "slow_initialization":
            self.clock.sleep(7)

    def preflight(self):
        self.record("preflight")
        return {"ready": True, "laser_enabled": self.laser_enabled,
                "synthetic": True, "identity": "SYNTHETIC DEVICE BOUNDARY"}

    def configure(self, phase, plan):
        assert self.opened and not self.laser_enabled
        self.record("configure")
        self.excitation_v_rms = plan.excitation_v_rms

    def laser_on(self, current_a):
        self.record("laser_on")
        self.laser_enabled = True

    def read_sample(self, phase):
        assert self.opened
        self.record("read_sample")
        self.clock.sleep(2 if self.scenario == "slow_initialization" else 0.1)
        if self.scenario == "partial_io_fault" and self.counts["read_sample"] == 2:
            raise OSError("Synthetic sample I/O fault")
        return {"synthetic": True, "channels": {"XX": {"x_v": 1e-6, "y_v": 2e-7}},
                "power_w": 4e-7 if self.laser_enabled else 0.0}

    def laser_off(self):
        self.record("laser_off")
        self.laser_enabled = False
        return {"laser_off_verified": True}

    def protect_excitation(self):
        self.record("protect_excitation")
        self.excitation_v_rms = 0.004
        return {"minimum_excitation_verified": self.scenario != "cleanup_unknown",
                "actual_v_rms": self.excitation_v_rms}

    def close(self):
        self.record("close")
        self.opened = False


def rehearse(output_dir):
    """Write one versioned synthetic report, refusing every existing directory."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    plan = PilotPlan(sample_id="SYNTHETIC ONLY", mode="combined", laser_current_a=0.0218,
                     power_limit_w=5e-7, reference_hz=137.0, max_run_s=10.0)
    approval = PilotApproval(enabled=True, sample_id="SYNTHETIC ONLY",
                             laser_current_max_a=0.0218, power_limit_max_w=5e-7,
                             reference_hz=137.0, max_phase_s=30.0, max_run_s=10.0)
    scenarios = {}
    for name in ("finite_success", "slow_initialization", "partial_io_fault", "cleanup_unknown"):
        bench = SyntheticBench(name)
        result = PilotEngine(bench, clock=bench.clock, sleep=bench.clock.sleep).run(plan, approval)
        scenarios[name] = {"result": result, "operations": bench.counts}
    report = {
        "schema": "labos-synthetic-commissioning-v1", "synthetic": True,
        "source_version": __version__, "engine": "labos.pilot.PilotEngine",
        "limitations": [
            "Invented readings and local synthetic approval; no instrument or network access.",
            "No wiring, identity, calibration, native timing or physical protection acceptance.",
            "Observed baseline admission is an estimate, not a future read-duration guarantee.",
            "UNKNOWN blocks future execution in the worker integration test; this CLI runs no worker.",
        ],
        "scenarios": scenarios,
    }
    destination = output_dir / "synthetic-commissioning-v1.json"
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="New directory only; existing directories are refused")
    args = parser.parse_args(argv)
    try:
        destination = rehearse(args.output_dir)
    except FileExistsError:
        parser.error("Output directory already exists; choose a new evidence directory")
    print(f"SYNTHETIC ONLY: {destination}")


if __name__ == "__main__":
    main()
