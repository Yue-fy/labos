import asyncio
from pathlib import Path

import pytest

from labos.agent import Agent
from labos.config import AgentConfig
from labos.models import Plan
from labos.runtime import Runtime
from labos.store import Store


async def run_with_local_pump(config, tmp_path, plan, pause=False, stop=False, trip_watchdog=False,
                              drop_light=False):
    store = Store(config.data_dir)
    agents = {}
    for agent_id, enrollment in config.agents.items():
        store.enroll(agent_id, enrollment.instruments)
        agent = Agent(AgentConfig(agent_id=agent_id, token=enrollment.token,
                                 server_url="http://localhost:8000", instruments=enrollment.instruments,
                                 data_dir=tmp_path / agent_id))
        agents[agent_id] = agent
        store.register(agent_id, agent.boot_id)
        store.heartbeat(agent_id, agent.boot_id, agent.statuses())
    runtime = Runtime(config, store)
    run = runtime.start(plan)
    run_id = run["id"]
    paused_once = False
    tripped = False
    for _ in range(1000):
        for agent_id, agent in agents.items():
            store.heartbeat(agent_id, agent.boot_id, agent.statuses())
            cmd = store.claim(agent_id, agent.boot_id)
            if cmd:
                if agent_id == "pc-a" and cmd["op"] == "set_wavelength" and not tripped:
                    if trip_watchdog:
                        agent.last_contact = 0
                        await agent.watchdog_once()
                    if drop_light:
                        await agent.devices["superk_01"].safe_shutdown()
                    tripped = trip_watchdog or drop_light
                result = await agent.execute(cmd)
                for item in agent.journal.pending_artifacts():
                    store.accept_artifact(agent_id, Path(item["path"]).read_bytes(), item["sha"])
                    agent.journal.ack_artifact(item["id"])
                store.complete_command(agent_id, agent.boot_id, cmd["id"],
                                       result["state"], result["result"])
        current = store.run(run_id)
        if pause and not paused_once and current["points"] >= 1 and current["status"] == "RUNNING":
            runtime.control(run_id, "pause")
            paused_once = True
        if current["status"] == "PAUSED":
            count = current["points"]
            await asyncio.sleep(0.05)
            assert store.run(run_id)["points"] == count
            runtime.control(run_id, "resume")
        if stop and current["points"] >= 1 and current["status"] == "RUNNING":
            runtime.control(run_id, "stop")
        if current["status"] in {"COMPLETED", "ABORTED", "FAILED"}:
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("runtime did not terminate")
    await runtime.close()
    for agent in agents.values():
        assert not any(s["shutter_open"] for s in agent.statuses().values())
        await agent.close()
    return store, run_id


def test_cross_pc_scan_and_pause_resume(central_config, tmp_path):
    store, run_id = asyncio.run(run_with_local_pump(
        central_config, tmp_path, Plan(angle_stop_deg=20, exposure_ms=1), pause=True))
    assert store.run(run_id)["status"] == "COMPLETED"
    assert len(store.measurements(run_id)) == 3
    assert all(i["lock_run"] is None for i in store.registry()["instruments"])


def test_stop_keeps_partial_data(central_config, tmp_path):
    store, run_id = asyncio.run(run_with_local_pump(
        central_config, tmp_path, Plan(angle_stop_deg=180, exposure_ms=1), stop=True))
    assert store.run(run_id)["status"] == "ABORTED"
    assert 1 <= len(store.measurements(run_id)) < 19


def test_preflight_uses_enrolled_limits(central_config):
    store = Store(central_config.data_dir)
    for agent_id, enrollment in central_config.agents.items():
        store.enroll(agent_id, enrollment.instruments)
        store.register(agent_id, agent_id)
        statuses = {d.id: {"instrument_id": d.id, "mode": "simulated", "stable": True,
                           "kind": d.kind, "driver_version": d.driver_version} for d in enrollment.instruments}
        store.heartbeat(agent_id, agent_id, statuses)
    runtime = Runtime(central_config, store)
    with pytest.raises(ValueError, match="wavelength"):
        runtime.preflight(Plan(wavelength_start_nm=900, wavelength_stop_nm=900))


def test_dispatch_timeout_retains_resources_and_never_requeues(central_config):
    async def check():
        store = Store(central_config.data_dir)
        for agent_id, enrollment in central_config.agents.items():
            store.enroll(agent_id, enrollment.instruments)
            store.register(agent_id, agent_id)
            store.heartbeat(agent_id, agent_id, {
                d.id: {"instrument_id": d.id, "mode": "simulated", "stable": True,
                       "kind": d.kind, "driver_version": d.driver_version}
                for d in enrollment.instruments})
        central_config.command_timeout_s = 0.1
        runtime = Runtime(central_config, store)
        run = runtime.start(Plan(angle_stop_deg=0))
        await asyncio.sleep(0.02)
        dispatched = store.claim("pc-a", "pc-a")
        await runtime.tasks[run["id"]]
        assert store.command(dispatched["id"])["state"] == "UNKNOWN"
        assert store.run(run["id"])["status"] == "FAILED"
        assert all(i["lock_run"] == run["id"] for i in store.registry()["instruments"])
        assert store.measurements(run["id"]) == []
    asyncio.run(check())


def test_watchdog_cannot_silently_continue_dark_scan(central_config, tmp_path):
    store, run_id = asyncio.run(run_with_local_pump(
        central_config, tmp_path, Plan(angle_stop_deg=10, exposure_ms=1), trip_watchdog=True))
    assert store.run(run_id)["status"] == "FAILED"
    assert store.measurements(run_id) == []


def test_capture_requires_verified_power_and_open_shutter(central_config, tmp_path):
    store, run_id = asyncio.run(run_with_local_pump(
        central_config, tmp_path, Plan(angle_stop_deg=10, exposure_ms=1), drop_light=True))
    assert store.run(run_id)["status"] == "FAILED"
    assert store.measurements(run_id) == []
