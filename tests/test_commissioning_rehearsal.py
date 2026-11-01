"""Offline engine rehearsal and real worker no-replay integration; never hardware."""

import builtins
import json
from pathlib import Path
import runpy
import socket

import pytest

from labos import __version__

ROOT = Path(__file__).resolve().parents[1]


def rehearsal():
    path = ROOT / "scripts/rehearse_commissioning.py"
    assert path.is_file(), "Canonical offline commissioning rehearsal is missing"
    return runpy.run_path(str(path))


def test_rehearsal_runs_real_engine_without_network_or_vendor_imports(tmp_path, monkeypatch):
    imported = builtins.__import__

    def checked_import(name, *args, **kwargs):
        assert name.split('.')[0] not in {"pyvisa", "serial"}
        assert name not in {"labos.cryostat_pilot", "labos.pilot_worker"}
        return imported(name, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("Offline rehearsal attempted a network connection")

    monkeypatch.setattr(builtins, "__import__", checked_import)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    api = rehearsal()
    destination = tmp_path / "new-evidence"
    report_path = api["rehearse"](destination)
    report = json.loads(report_path.read_text())
    assert report["schema"] == "labos-synthetic-commissioning-v1"
    assert report["synthetic"] is True
    assert report["source_version"] == __version__
    assert report["limitations"]
    scenarios = report["scenarios"]
    assert set(scenarios) == {"finite_success", "slow_initialization", "partial_io_fault",
                              "cleanup_unknown"}
    success = scenarios["finite_success"]
    assert success["result"]["status"] == "COMPLETED"
    assert len(success["result"]["samples"]) == 3
    slow = scenarios["slow_initialization"]
    assert slow["result"]["status"] == "FAILED"
    assert slow["result"]["failure"]["stage"] == "illumination_budget"
    assert slow["operations"].get("laser_on", 0) == 0
    assert slow["result"]["budget_checks"][-1]["admitted"] is False
    partial = scenarios["partial_io_fault"]["result"]
    assert partial["status"] == "FAILED"
    assert len(partial["samples"]) == 1
    assert partial["failure"]["stage"] == "sample"
    unknown = scenarios["cleanup_unknown"]
    assert unknown["result"]["status"] == "UNKNOWN"
    assert unknown["result"]["protection_verified"] is False
    for item in scenarios.values():
        assert item["operations"]["close"] == 1
        assert item["operations"]["laser_off"] >= 1
        assert item["operations"]["protect_excitation"] >= 1
        assert len(item["result"]["timing"]["stages"]) <= 256
        assert len(item["result"]["samples"]) <= 30
    assert report_path.stat().st_size < 100_000


def test_rehearsal_refuses_existing_directory_and_preserves_evidence(tmp_path):
    api = rehearsal()
    destination = tmp_path / "evidence"
    report = api["rehearse"](destination)
    original = report.read_bytes()
    with pytest.raises(FileExistsError):
        api["rehearse"](destination)
    assert report.read_bytes() == original
    with pytest.raises(FileExistsError):
        api["rehearse"](tmp_path)


def test_real_engine_cleanup_unknown_blocks_distinct_future_task_after_restart(
        tmp_path, central_config, monkeypatch):
    from fastapi.testclient import TestClient
    from labos.central import create_app
    from labos.pilot import PilotEngine
    from test_pilot_worker import (
        approval, artifact, commission_profile, configuration, messages, module, send, task,
        transport,
    )

    bench = rehearsal()["SyntheticBench"]("cleanup_unknown")
    monkeypatch.setattr(module(), "PilotEngine", lambda adapter, **kwargs: PilotEngine(
        adapter, clock=bench.clock, sleep=bench.clock.sleep, **kwargs))
    config = configuration(tmp_path, approval=approval())
    factories = []

    def factory(settings):
        factories.append(settings)
        return bench

    with TestClient(create_app(central_config)) as api:
        commission_profile(api, config)
        send(api, "synthetic-first", task())
        worker = module().PilotWorker(config, transport(api), factory)
        worker.tick()
        body = messages(api)[-1]["body"]
        assert artifact(worker, body)["report"]["status"] == "UNKNOWN"
        assert worker.status()["physical_blocked"] is True
        send(api, "synthetic-second", task("pilot_2"))
        restarted = module().PilotWorker(config, transport(api), factory)
        restarted.tick()
        assert restarted.status()["physical_blocked"] is True
        assert len(factories) == 1
        assert bench.counts["open"] == 1
        assert messages(api)[-1]["body"]["answer"]["status"] == "needs_input"
