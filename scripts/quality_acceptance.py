"""Real TCP: reject overload, retain evidence, verify shutdown, then start a new pilot."""
import io
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import h5py
import httpx
import yaml

from labos.cli import provision, save_private
from labos.config import CentralConfig, load_config
from labos.models import Plan

ROOT = Path(__file__).resolve().parents[1]
directory = ROOT / "runtime" / ("quality-" + str(time.time_ns()))
directory.mkdir(parents=True)
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
url = f"http://127.0.0.1:{port}"
paths = provision(directory / "config", url, port=port)
for name in ("central", "pc-a", "pc-b"):
    values = yaml.safe_load(paths[name].read_text())
    instruments = values["agents"]["pc-b"]["instruments"] if name == "central" else values["instruments"]
    for spec in instruments:
        if spec["kind"] == "spectrometer":
            spec["detector_max_counts"] = 10
    if name != "central":
        values.update(heartbeat_s=0.2, poll_s=0.05, watchdog_s=3, request_timeout_s=1)
    save_private(paths[name], yaml.safe_dump(values).encode())
config = load_config(paths["central"], CentralConfig)
processes, handles = [], []


def wait_until(check, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    raise RuntimeError(f"quality acceptance timed out; logs in {directory}")


try:
    for name in ("central", "pc-a", "pc-b"):
        handle = (directory / f"{name}.log").open("w")
        handles.append(handle)
        processes.append(subprocess.Popen([sys.executable, "-m", "labos",
            "central" if name == "central" else "agent", "--config", str(paths[name])],
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, stdout=handle, stderr=subprocess.STDOUT))
    with httpx.Client(base_url=url, headers={"Authorization": f"Bearer {config.admin_token}"},
                      timeout=5, trust_env=False) as client:
        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def post(path, body):
            response = client.post(path, json=body)
            response.raise_for_status()
            return response.json()

        wait_until(lambda: all(i["online"] for i in get("/api/status")["instruments"]))
        doc = post("/api/evidence", {"title": "Prior spectrum test", "source": "lab:test_spectrum.py",
            "category": "code", "content": "# spectrum acquisition: verify detector overload before use", "reviewed": True})
        hits = get("/api/evidence?q=spectrum")
        assert hits[0]["id"] == doc["id"]
        plan = Plan(angle_stop_deg=20, exposure_ms=10, evidence_ids=[doc["id"]])
        assert post("/api/preflight", plan.model_dump())["evidence"][0]["id"] == doc["id"]
        bad_id = post("/api/runs", plan.model_dump())["id"]
        wait_until(lambda: get(f"/api/runs/{bad_id}")["status"] == "FAILED")
        failed = get(f"/api/runs/{bad_id}")
        assert failed["points"] == 0
        review = wait_until(lambda: get(f"/api/runs/{bad_id}/review"))["body"]
        assert review["data_quality"]["rejected"] == 1 and review["signal_summary"] is None
        assert review["closure"]["status"] == "verified_by_software_readback"
        assert review["evidence_citations"][0]["sha256"] == doc["sha256"]
        artifact = get(f"/api/runs/{bad_id}/measurements")[0]
        assert artifact["detector_flags"]["overloaded"]
        assert get(f"/api/runs/{bad_id}/measurements?qualified_only=true") == []
        response = client.get(f"/api/runs/{bad_id}/export")
        response.raise_for_status()
        (directory / "rejected-run.h5").write_bytes(response.content)
        with h5py.File(io.BytesIO(response.content)) as h5:
            assert h5["raw/counts"].shape == (0, 128)
            assert len(h5["audit/measurements_json"]) == 1
        # A proposal is still only data: a new preflight and explicit POST start are required.
        assert len(get("/api/status")["runs"]) == 1
        pilot = review["next_actions"][0]["proposed_plan"]
        assert pilot["exposure_ms"] == 5
        post("/api/preflight", pilot)
        good_id = post("/api/runs", pilot)["id"]
        wait_until(lambda: get(f"/api/runs/{good_id}")["status"] in {"COMPLETED", "FAILED"})
        assert get(f"/api/runs/{good_id}")["status"] == "COMPLETED"
        assert get(f"/api/runs/{good_id}")["points"] == 3
        good_review = wait_until(lambda: get(f"/api/runs/{good_id}/review"))["body"]
        assert good_review["data_quality"]["accepted"] == 3
        assert good_review["closure"]["status"] == "verified_by_software_readback"
        assert all(i["lock_run"] is None for i in get("/api/status")["instruments"])
        report = {"status": "PASS", "transport": "real loopback TCP", "processes": 3,
            "evidence_version": doc["version"], "rejected_run": bad_id,
            "rejected_raw_retained": True, "shutdown_readback_verified": True,
            "followup_required_explicit_start": True, "pilot_run": good_id,
            "pilot_qualified_points": 3, "simulated": True, "directory": str(directory)}
        (directory / "quality-acceptance.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
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
