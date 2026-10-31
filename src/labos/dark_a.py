"""Prepare an isolated disabled dark-voltage profile without any instrument I/O."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from .cryostat_pilot import validate_adapter_config
from .pilot_worker import PilotWorkerConfig, load_pilot_worker_config


def prepare_config(source, output, *, start_after):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("Candidate exists; preserve and review it instead of overwriting")
    if output.parent != source.parent:
        raise ValueError("Keep the candidate in the existing installation directory")
    original = load_pilot_worker_config(source)
    if original.approval is None or original.approval.reference_hz != 8:
        raise ValueError("An existing locally approved8Hz profile is required")
    state = source.parent / "data/dark-a-pilot"
    if state.exists() or state == original.state_dir.resolve():
        raise ValueError("Dark a-axis state already exists; never reset an execution ledger")
    adapter = dict(original.adapter_config)
    adapter.update(experiment_scope="dark_a", aux_enabled=False)
    adapter["resources"] = {k: adapter["resources"][k] for k in ("cld", "xx", "gate")}
    for key in list(adapter):
        if key.startswith("chopper_"):
            adapter.pop(key)
    # Resolve the exact same station lease, never infer a different config file.
    station = Path(adapter["station_config"])
    if not station.is_absolute():
        adapter["station_config"] = str((source.parent / station).resolve())
    validate_adapter_config(adapter)
    values = original.model_dump(mode="json")
    values.update(state_dir=str(state), start_after=start_after, adapter_config=adapter)
    values["approval"].update(enabled=False, laser_current_max_a=None,
                              power_limit_max_w=None, max_phase_s=30.0, max_run_s=90.0)
    candidate = PilotWorkerConfig.model_validate(values)
    # Exclusive create intentionally refuses an existing local configuration.
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(candidate.model_dump(mode="json"), handle, sort_keys=False)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("pilot-worker.yaml"))
    parser.add_argument("--output", type=Path, default=Path("dark-a-worker.yaml"))
    parser.add_argument("--start-after", type=int, required=True)
    args = parser.parse_args(argv)
    path = prepare_config(args.source, args.output, start_after=args.start_after)
    print(f"Disabled dark a-axis candidate written: {path}")
    print("Original approval, configuration and journals preserved. No instrument access performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
