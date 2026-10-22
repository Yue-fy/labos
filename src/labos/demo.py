from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml

from .cli import provision, save_private
from .config import CentralConfig, load_config
from .models import Plan, SimulationResponse


def acceptance(directory: Path, full=False, source_root: Path | None = None, *,
               adaptive=False, resonance_nm=635, seed=0):
    """Real TCP integration, three separate OS processes; no cloud/physical hardware."""
    response_profile = (SimulationResponse(peak_nm=resonance_nm, seed=seed, relative_noise=0.00001)
                        if adaptive else None)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    paths = provision(directory / "configuration", url, port=port)
    if response_profile is not None:
        central_settings = yaml.safe_load(paths["central"].read_text())
        pc_settings = yaml.safe_load(paths["pc-b"].read_text())
        for specs in (central_settings["agents"]["pc-b"]["instruments"], pc_settings["instruments"]):
            for spec in specs:
                if spec["kind"] == "spectrometer":
                    spec["simulation_response"] = response_profile.model_dump()
        save_private(paths["central"], yaml.safe_dump(central_settings).encode())
        save_private(paths["pc-b"], yaml.safe_dump(pc_settings).encode())
    for name in ("pc-a", "pc-b"):
        settings = yaml.safe_load(paths[name].read_text())
        # Poll quickly, but retain the normal request/watchdog deadlines so a
        # busy development machine does not turn a demo into a fault injection.
        settings.update(poll_s=0.05, heartbeat_s=0.2)
        save_private(paths[name], yaml.safe_dump(settings).encode())
    config = load_config(paths["central"], CentralConfig)
    environment = os.environ.copy()
    if source_root:
        environment["PYTHONPATH"] = str(source_root / "src")
    processes, handles = [], []
    try:
        for role in ("central", "pc-a", "pc-b"):
            handle = (directory / f"{role}.log").open("w", encoding="utf-8")
            handles.append(handle)
            process = subprocess.Popen(
                [sys.executable, "-m", "labos", "central" if role == "central" else "agent",
                 "--config", str(paths[role])], cwd=source_root or directory,
                stdout=handle, stderr=subprocess.STDOUT, env=environment)
            processes.append(process)
        with httpx.Client(base_url=url, headers={"Authorization": f"Bearer {config.admin_token}"},
                          timeout=5, trust_env=False) as client:
            deadline = time.monotonic() + 30
            while True:
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError(f"demo subprocess exited; inspect logs in {directory}")
                try:
                    status = client.get("/api/status")
                    if status.status_code == 200 and all(i["online"] for i in status.json()["instruments"]):
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("agents did not become ready within 30 seconds")
                time.sleep(0.1)
            plan = Plan(wavelength_start_nm=500, wavelength_stop_nm=700, exposure_ms=1) if full else Plan(
                wavelength_start_nm=640, wavelength_stop_nm=660, angle_stop_deg=20, exposure_ms=1)
            if adaptive:
                plan = Plan(wavelength_start_nm=500, wavelength_stop_nm=800, wavelength_step_nm=20,
                            angle_stop_deg=0, exposure_ms=1,
                            adaptive={"simulation_approved": True})
            preflight = client.post("/api/preflight", json=plan.model_dump())
            preflight.raise_for_status()
            response = client.post("/api/runs", json=plan.model_dump())
            response.raise_for_status()
            run_id = response.json()["id"]
            deadline = time.monotonic() + (240 if full or adaptive else 45)
            while True:
                if any(p.poll() is not None for p in processes):
                    raise RuntimeError(f"demo subprocess exited; inspect logs in {directory}")
                response = client.get(f"/api/runs/{run_id}")
                response.raise_for_status()
                run = response.json()
                if run["status"] in {"COMPLETED", "FAILED", "ABORTED", "INTERRUPTED"}:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("scan did not terminate within acceptance deadline")
                time.sleep(0.1)
            if run["status"] != "COMPLETED" or (not adaptive and run["points"] != len(plan.points())):
                raise RuntimeError(f"scan failed: {run['status']} ({run.get('error')})")
            response = client.get(f"/api/runs/{run_id}/measurements")
            response.raise_for_status()
            data = response.json()
            assert len(data) == run["points"]
            assert [m["point_index"] for m in data] == list(range(len(data)))
            if not adaptive:
                assert len({(m["wavelength_nm"], m["angle_deg"]) for m in data}) == len(data)
            assert all(m["simulated"] and m["agent_id"] == "pc-b" for m in data)
            history, rounds = [], []
            if adaptive:
                response = client.get(f"/api/runs/{run_id}/adaptive")
                response.raise_for_status()
                history = response.json()["history"]
                rounds = [e["detail"] for e in history if e["category"] == "ADAPTIVE_ROUND_COMPLETED"]
                assert len(rounds) == 3
                assert [r["plan"]["wavelength_step_nm"] for r in rounds] == [20, 5, 1]
                assert abs(rounds[-1]["analysis"]["peak_nm"] - resonance_nm) <= 0.5
                from .adaptive import analyze_peak, refine_plan
                for index, current in enumerate(rounds):
                    scan = Plan.model_validate(current["plan"])
                    offset, count = current["point_offset"], current["point_count"]
                    observed = data[offset:offset+count]
                    assert [(m["wavelength_nm"], m["angle_deg"]) for m in observed] == scan.points()
                    assert current["analysis"] == analyze_peak(scan, observed, plan.adaptive.min_contrast)
                    if index < len(rounds)-1:
                        expected = refine_plan(scan, current["analysis"]["peak_nm"],
                                               plan.adaptive.refinement_steps_nm[index])
                        assert rounds[index+1]["plan"] == expected.model_dump()
                assert sum(r["point_count"] for r in rounds) == len(data) <= plan.adaptive.max_total_points
            export = client.get(f"/api/runs/{run_id}/export")
            export.raise_for_status()
            hdf5_path = directory / f"{run_id}.h5"
            hdf5_path.write_bytes(export.content)
            import h5py
            with h5py.File(hdf5_path) as h5:
                assert h5["raw/counts"].shape == (len(data), 128)
                assert h5.attrs["simulated"]
                if adaptive:
                    assert json.loads(h5["adaptive/events_json"][()].decode()) == history
                    assert list(h5["raw/round_index"][:]) == [
                        i for i, r in enumerate(rounds) for _ in range(r["point_count"])]
            registry = client.get("/api/status").json()
            assert all(i["lock_run"] is None for i in registry["instruments"])
            if adaptive:
                deadline = time.monotonic() + 5
                while not all(i["status"].get("power_percent") == 0
                              and i["status"].get("shutter_open") is False
                              for i in registry["instruments"]):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("final safe state did not synchronize")
                    time.sleep(0.1)
                    registry = client.get("/api/status").json()
                cached = list((paths["pc-b"].parent / "data" / "cache").glob("*.json"))
                assert len(cached) == len(data)
            result = {"status": "PASS", "transport": "TCP HTTP over loopback",
                      "processes": 3, "agent_count": 2, "instrument_count": 3,
                      "points": len(data), "hdf5": str(hdf5_path), "run_id": run_id,
                      "simulated": True}
            if adaptive:
                result.update(rounds=rounds, detected_peak_nm=rounds[-1]["analysis"]["peak_nm"],
                              simulator_truth_nm=resonance_nm, seed=seed,
                              automatic_decisions=2, approval="explicit simulation command",
                              safe_shutdown_verified=True, local_cache_verified=True)
            (directory / "acceptance.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            return result
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for handle in handles:
            handle.close()
