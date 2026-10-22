import asyncio
import json
from pathlib import Path

import h5py
import pytest
from fastapi.testclient import TestClient

from labos.agent import Agent
from labos.central import create_app
from labos.config import AgentConfig
from labos.models import Plan, SimulationResponse
from labos.runtime import Runtime
from labos.store import Store


def plan(budget=200):
    return Plan(wavelength_start_nm=500, wavelength_stop_nm=800, wavelength_step_nm=20,
                angle_stop_deg=0, exposure_ms=1,
                adaptive={"simulation_approved": True, "max_total_points": budget})


async def exercise(config, tmp_path, *, peak=635, budget=200, stop_after=None,
                   watchdog_after=None, offline_at_fine=False, pause_after=None,
                   watchdog_at_dark=False, override_signal=None):
    store, agents = Store(config.data_dir), {}
    for agent_id, enrollment in config.agents.items():
        for spec in enrollment.instruments:
            if spec.kind == "spectrometer" and peak is not None:
                spec.simulation_response = SimulationResponse(peak_nm=peak, seed=7)
        store.enroll(agent_id, enrollment.instruments)
        agent = Agent(AgentConfig(agent_id=agent_id, token=enrollment.token,
            server_url="http://localhost:8000", instruments=enrollment.instruments,
            data_dir=tmp_path / agent_id))
        if override_signal is not None and agent_id == "pc-b":
            driver = agent.devices["spectrometer_01"]
            original_acquire = driver.execute
            async def acquire(op, parameters, cancel):
                result = await original_acquire(op, parameters, cancel)
                if op == "acquire_and_store":
                    result["counts"] = [2.0] * len(result["counts"])
                    result["counts"][64] += override_signal.get(parameters["wavelength_nm"], 1)
                return result
            driver.execute = acquire
        agents[agent_id] = agent
        store.register(agent_id, agent.boot_id)
        store.heartbeat(agent_id, agent.boot_id, agent.statuses())
    runtime = Runtime(config, store)
    if offline_at_fine:
        original = runtime.preflight
        def recheck(scan, **kwargs):
            if scan.wavelength_step_nm == 5:
                store.disconnect("pc-b", agents["pc-b"].boot_id)
            return original(scan, **kwargs)
        runtime.preflight = recheck
    run_id = runtime.start(plan(budget))["id"]
    tripped, paused = False, False
    try:
        async with asyncio.timeout(20):
            while not runtime.tasks[run_id].done():
                for agent_id, agent in agents.items():
                    store.heartbeat(agent_id, agent.boot_id, agent.statuses())
                    command = store.claim(agent_id, agent.boot_id)
                    if command:
                        if paused and store.run(run_id)["status"] == "PAUSING":
                            assert command["op"] not in {"set_power", "open_shutter"}, (
                                "next round must not reopen light while pause is pending")
                        if (watchdog_after is not None and not tripped and agent_id == "pc-a"
                                and store.run(run_id)["points"] >= watchdog_after
                                and command["op"] == "set_wavelength"):
                            agent.last_contact = 0
                            await agent.watchdog_once()
                            tripped = True
                        if (watchdog_at_dark and not tripped and agent_id == "pc-a"
                                and store.run(run_id)["points"] == 16
                                and command["op"] == "safe_shutdown"):
                            agent.last_contact = 0
                            await agent.watchdog_once()
                            tripped = True
                        result = await agent.execute(command)
                        for item in agent.journal.pending_artifacts():
                            store.accept_artifact(agent_id, Path(item["path"]).read_bytes(), item["sha"])
                            agent.journal.ack_artifact(item["id"])
                        store.complete_command(agent_id, agent.boot_id, command["id"],
                                               result["state"], result["result"])
                current = store.run(run_id)
                if (pause_after is not None and not paused and current["points"] >= pause_after
                        and current["status"] == "RUNNING"):
                    runtime.control(run_id, "pause")
                    paused = True
                if current["status"] == "PAUSED":
                    assert agents["pc-a"].devices["superk_01"].shutter is False
                    runtime.control(run_id, "resume")
                if (stop_after is not None and current["points"] >= stop_after
                        and current["status"] == "RUNNING"):
                    runtime.control(run_id, "stop")
                await asyncio.sleep(0.001)
            await runtime.tasks[run_id]
        assert all(not s["shutter_open"] and s["power_percent"] == 0
                   for a in agents.values() for s in a.statuses().values())
        if watchdog_at_dark:
            assert agents["pc-a"].statuses()["superk_01"]["fault_latched"]
            with pytest.raises(ValueError, match="watchdog"):
                runtime.start(plan())
    finally:
        await runtime.close()
        for agent in agents.values():
            await agent.close()
    return store, run_id


def test_pause_between_rounds_does_not_reopen_light_before_resume(central_config, tmp_path):
    store, run_id = asyncio.run(exercise(central_config, tmp_path, pause_after=16))
    assert store.run(run_id)["status"] == "COMPLETED"
    assert store.run(run_id)["points"] == 54


def test_watchdog_between_rounds_requires_manual_reconciliation(central_config, tmp_path):
    store, run_id = asyncio.run(exercise(central_config, tmp_path, watchdog_at_dark=True))
    assert store.run(run_id)["status"] == "FAILED"
    assert store.run(run_id)["points"] == 16


@pytest.mark.parametrize("signals", [
    [1, 1, 1, 1, 1, 1, 1, 100, 1, 1, 1, 1, 1, 1, 1, 100],
    [1, 1, 1, 1, 1, 1, 1, 100, 1, 1, 1, 100, 100, 1, 1, 1],
])
def test_ambiguous_competitor_stops_before_any_fine_round(central_config, tmp_path, signals):
    store, run_id = asyncio.run(exercise(central_config, tmp_path,
        override_signal=dict(zip(range(500, 801, 20), signals))))
    assert store.run(run_id)["status"] == "FAILED"
    assert store.run(run_id)["points"] == 16
    assert "ambiguous" in store.run(run_id)["error"]
    history = store.adaptive_history(run_id)
    assert not any(e["category"] == "ADAPTIVE_NEXT_SCAN" for e in history)
    assert len([e for e in history if e["category"] == "ADAPTIVE_ROUND_STARTED"]) == 1


@pytest.mark.parametrize("peak", [635, 707])
def test_full_adaptive_run_has_measured_decisions_and_hdf5(central_config, tmp_path, peak):
    store, run_id = asyncio.run(exercise(central_config, tmp_path, peak=peak))
    run, data = store.run(run_id), store.measurements(run_id)
    assert run["status"] == "COMPLETED", run["error"]
    assert run["points"] == 54, "adaptive execution must add both data-selected refinement rounds"
    assert [m["point_index"] for m in data] == list(range(54))
    assert all(i["lock_run"] is None for i in store.registry()["instruments"])
    history = store.adaptive_history(run_id)
    completed = [e["detail"] for e in history if e["category"] == "ADAPTIVE_ROUND_COMPLETED"]
    assert [e["plan"]["wavelength_step_nm"] for e in completed] == [20, 5, 1]
    assert abs(completed[-1]["analysis"]["peak_nm"] - peak) <= 0.5
    assert len([e for e in history if e["category"] == "ADAPTIVE_NEXT_SCAN"]) == 2
    with h5py.File(store.root / "exports" / f"{run_id}.h5") as h5:
        assert h5.attrs["simulated"]
        assert h5["raw/counts"].shape == (54, 128)
        assert list(h5["raw/round_index"][:]) == [0]*16 + [1]*17 + [2]*21
        assert json.loads(h5["adaptive/events_json"][()].decode()) == history
        assert history[0]["category"] == "ADAPTIVE_APPROVED"
        assert json.loads(h5["metadata/plan"][()].decode())["adaptive"]["simulation_approved"]


@pytest.mark.parametrize("options,point_count,expected_status", [
    ({"peak": None}, 16, "FAILED"), ({"budget": 16}, 16, "FAILED"),
    ({"stop_after": 16}, 16, "ABORTED"), ({"watchdog_after": 1}, 1, "FAILED"),
    ({"offline_at_fine": True}, 16, "FAILED"),
])
def test_failed_or_stopped_loop_preserves_data_and_never_refines(
        central_config, tmp_path, options, point_count, expected_status):
    store, run_id = asyncio.run(exercise(central_config, tmp_path, **options))
    run = store.run(run_id)
    assert run["status"] == expected_status
    assert run["points"] == point_count
    assert all(m["wavelength_nm"] in range(500, 801, 20) for m in store.measurements(run_id))
    assert store.adaptive_history(run_id)[0]["category"] == "ADAPTIVE_APPROVED"
    with h5py.File(store.root / "exports" / f"{run_id}.h5") as h5:
        assert h5["raw/counts"].shape[0] == point_count


def test_adaptive_api_rejects_unapproved_and_agent_submissions(central_config):
    with TestClient(create_app(central_config)) as client:
        body = plan().model_dump()
        body["adaptive"].pop("simulation_approved")
        assert client.post("/api/runs", json=body,
            headers={"Authorization": "Bearer " + "O"*40}).status_code == 422
        assert client.post("/api/runs", json=plan().model_dump(),
            headers={"Authorization": "Bearer " + "A"*40}).status_code == 403
        assert client.get("/api/runs/nonexistent/adaptive").status_code == 401
