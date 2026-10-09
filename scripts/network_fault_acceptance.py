"""Exercise real TCP disconnect, local fault latch, central restart and explicit recovery."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml

from labos.cli import provision, save_private
from labos.config import CentralConfig, load_config
from labos.models import Plan

ROOT = Path(__file__).resolve().parents[1]
directory = ROOT / "runtime" / ("network-fault-" + str(int(time.time())))
directory.mkdir(parents=True)
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
url = f"http://127.0.0.1:{port}"
paths = provision(directory / "config", url, port=port)
for name in ("pc-a", "pc-b"):
    settings = yaml.safe_load(paths[name].read_text())
    settings.update(heartbeat_s=0.2, poll_s=0.05, watchdog_s=1, request_timeout_s=0.3)
    save_private(paths[name], yaml.safe_dump(settings).encode())
config = load_config(paths["central"], CentralConfig)
processes, handles = [], []
environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}


def spawn(name):
    handle = (directory / f"{name}-{len(handles)}.log").open("w")
    handles.append(handle)
    process = subprocess.Popen([sys.executable, "-m", "labos",
                                "central" if name == "central" else "agent", "--config", str(paths[name])],
                               env=environment, stdout=handle, stderr=subprocess.STDOUT)
    processes.append(process)
    return process


def wait_until(check, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"acceptance condition timed out; logs in {directory}")


try:
    central = spawn("central")
    spawn("pc-a")
    spawn("pc-b")
    with httpx.Client(base_url=url, headers={"Authorization": f"Bearer {config.admin_token}"},
                      timeout=2, trust_env=False) as client:
        def status():
            response = client.get("/api/status")
            response.raise_for_status()
            return response.json()
        wait_until(lambda: all(i["online"] for i in status()["instruments"]))
        response = client.post("/api/runs", json=Plan(exposure_ms=300).model_dump())
        response.raise_for_status()
        run_id = response.json()["id"]
        wait_until(lambda: client.get(f"/api/runs/{run_id}").json()["points"] >= 1)
        central.terminate()
        central.wait(timeout=5)
        time.sleep(2)
        with sqlite3.connect(paths["pc-a"].parent / "data/journal.sqlite") as db:
            assert db.execute("SELECT COUNT(*) FROM devices WHERE fault IS NOT NULL").fetchone()[0] >= 1
        central = spawn("central")
        wait_until(lambda: all(i["online"] for i in status()["instruments"]))
        old = client.get(f"/api/runs/{run_id}").json()
        assert old["status"] == "INTERRUPTED"
        assert old["points"] >= 1
        assert any(i["status"].get("fault_latched") for i in status()["instruments"])
        response = client.post(f"/api/runs/{run_id}/reconcile")
        response.raise_for_status()
        wait_until(lambda: client.get(f"/api/runs/{run_id}").json()["status"] == "ABORTED")
        wait_until(lambda: all(not i["status"].get("fault_latched") for i in status()["instruments"]))
        response = client.post("/api/runs", json=Plan(angle_stop_deg=10, exposure_ms=1).model_dump())
        response.raise_for_status()
        new_id = response.json()["id"]
        wait_until(lambda: client.get(f"/api/runs/{new_id}").json()["status"] == "COMPLETED")
        new = client.get(f"/api/runs/{new_id}").json()
        assert new["points"] == 2
        result = {"status": "PASS", "transport": "real loopback TCP", "old_run": run_id,
                  "old_run_data_preserved": True, "watchdog_fault_persisted": True,
                  "explicit_reconciliation": True, "new_run_points": 2}
        (directory / "network-fault-acceptance.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
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
