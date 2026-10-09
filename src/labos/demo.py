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
from .models import Plan


def acceptance(directory: Path, full=False, source_root: Path | None = None):
    """Real TCP integration, three separate OS processes; no cloud/physical hardware."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    paths = provision(directory / "configuration", url, port=port)
    for name in ("pc-a", "pc-b"):
        settings = yaml.safe_load(paths[name].read_text())
        settings.update(poll_s=0.05, heartbeat_s=0.2, watchdog_s=3, request_timeout_s=1)
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
            preflight = client.post("/api/preflight", json=plan.model_dump())
            preflight.raise_for_status()
            response = client.post("/api/runs", json=plan.model_dump())
            response.raise_for_status()
            run_id = response.json()["id"]
            deadline = time.monotonic() + (240 if full else 45)
            while True:
                response = client.get(f"/api/runs/{run_id}")
                response.raise_for_status()
                run = response.json()
                if run["status"] in {"COMPLETED", "FAILED", "ABORTED"}:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("scan did not terminate within acceptance deadline")
                time.sleep(0.1)
            if run["status"] != "COMPLETED" or run["points"] != len(plan.points()):
                raise RuntimeError(f"scan failed: {run['status']} ({run.get('error')})")
            data = client.get(f"/api/runs/{run_id}/measurements").json()
            assert len(data) == len(plan.points())
            assert len({(m["wavelength_nm"], m["angle_deg"]) for m in data}) == len(data)
            assert all(m["simulated"] and m["agent_id"] == "pc-b" for m in data)
            export = client.get(f"/api/runs/{run_id}/export")
            export.raise_for_status()
            hdf5_path = directory / f"{run_id}.h5"
            hdf5_path.write_bytes(export.content)
            import h5py
            with h5py.File(hdf5_path) as h5:
                assert h5["raw/counts"].shape == (len(plan.points()), 128)
            registry = client.get("/api/status").json()
            assert all(i["lock_run"] is None for i in registry["instruments"])
            result = {"status": "PASS", "transport": "TCP HTTP over loopback",
                      "processes": 3, "agent_count": 2, "instrument_count": 3,
                      "points": len(data), "hdf5": str(hdf5_path), "run_id": run_id,
                      "simulated": True}
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
