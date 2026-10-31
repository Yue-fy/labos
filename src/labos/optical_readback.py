"""Derive a disabled, separate OFF/ON readback profile without any instrument I/O."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .cryostat_pilot import validate_adapter_config
from .pilot_worker import PilotWorkerConfig, load_pilot_worker_config


def prepare_config(source, output, *, start_after):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("Candidate exists; preserve it and its execution state")
    if output.parent != source.parent:
        raise ValueError("Keep the candidate in the existing installation directory")
    original = load_pilot_worker_config(source)
    approval = original.approval
    if (
        approval is None
        or approval.reference_hz != 8
        or approval.laser_current_max_a is None
        or approval.laser_current_max_a > 0.0218
        or approval.power_limit_max_w is None
        or approval.power_limit_max_w > 1e-6
    ):
        raise ValueError(
            "An existing commissioned8Hz optical profile with bounded limits is required"
        )
    state = source.parent / "data/optical-readback-pilot"
    if state.exists() or state == original.state_dir.resolve():
        raise ValueError("Readback state already exists; never reset an execution ledger")
    adapter = dict(original.adapter_config)
    adapter.update(experiment_scope="optical_readback", aux_enabled=False)
    adapter["resources"] = {k: adapter["resources"][k] for k in ("cld", "pm", "xx", "xy", "gate")}
    for key in list(adapter):
        if key.startswith("chopper_"):
            adapter.pop(key)
    station = Path(adapter["station_config"])
    if not station.is_absolute():
        adapter["station_config"] = str((source.parent / station).resolve())
    validate_adapter_config(adapter)
    values = original.model_dump(mode="json")
    values.update(state_dir=str(state), start_after=start_after, adapter_config=adapter)
    values["approval"].update(
        enabled=False,
        max_phase_s=min(60.0, approval.max_phase_s),
        max_run_s=min(180.0, approval.max_run_s),
    )
    candidate = PilotWorkerConfig.model_validate(values)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(candidate.model_dump(mode="json"), handle, sort_keys=False)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("pilot-worker.yaml"))
    parser.add_argument("--output", type=Path, default=Path("optical-readback-worker.yaml"))
    parser.add_argument("--start-after", type=int, required=True)
    args = parser.parse_args(argv)
    path = prepare_config(args.source, args.output, start_after=args.start_after)
    print(f"Disabled optical readback candidate written: {path}")
    print("No instrument access. Existing profiles, limits, acknowledgment and journals retained.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
