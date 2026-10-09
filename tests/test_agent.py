import asyncio
import hashlib
import json

import pytest
import httpx

from labos.agent import Agent
from labos.config import AgentConfig
from labos.models import InstrumentSpec


def test_local_capture_precedes_result_and_is_not_replayed(tmp_path):
    async def check():
        config = AgentConfig(agent_id="pc-b", token="B" * 40, server_url="http://127.0.0.1:8000",
                             data_dir=tmp_path, instruments=[InstrumentSpec(id="spectrometer_01", kind="spectrometer")])
        agent = Agent(config)
        cmd = {"id": "cmd_abc", "run_id": "exp_abc", "instrument_id": "spectrometer_01",
               "op": "acquire_and_store", "parameters": {
                   "point_index": 0, "sample_id": "s01", "wavelength_nm": 650,
                   "angle_deg": 30, "power_percent": 5, "exposure_ms": 1, "readbacks": {}}}
        result = await agent.execute(cmd)
        path = tmp_path / "cache" / "cmd_abc.json"
        assert path.exists() and json.loads(path.read_text())["simulated"]
        assert agent.journal.get(cmd["id"])["state"] == "COMPLETED"
        original = hashlib.sha256(path.read_bytes()).hexdigest()
        result2 = await agent.execute(cmd)
        assert result == result2
        assert hashlib.sha256(path.read_bytes()).hexdigest() == original
        await agent.close()
    asyncio.run(check())


def test_watchdog_cancels_action_and_closes_shutter(tmp_path):
    async def check():
        config = AgentConfig(agent_id="pc-a", token="A" * 40, server_url="http://localhost:8000",
                             data_dir=tmp_path, heartbeat_s=0.1, watchdog_s=1,
                             instruments=[InstrumentSpec(id="superk_01", kind="laser")])
        agent = Agent(config)
        device = agent.devices["superk_01"]
        await device.execute("set_power", {"percent": 5}, asyncio.Event())
        await device.execute("open_shutter", {}, asyncio.Event())
        agent.last_contact = 0
        await agent.watchdog_once()
        assert not device.status()["shutter_open"]
        assert agent.cancel.is_set()
        await agent.close()
    asyncio.run(check())


def test_untrusted_http_requires_opt_in():
    with pytest.raises(ValueError, match="HTTP"):
        AgentConfig(agent_id="pc-a", token="A" * 40, server_url="http://192.168.1.10:8000", instruments=[])


def test_watchdog_is_independent_of_blocked_heartbeat(tmp_path):
    async def check():
        async def blocked(request):
            await asyncio.sleep(3)
            return httpx.Response(200, json={"cancel_runs": []})
        config = AgentConfig(agent_id="pc-a", token="A" * 40, server_url="http://localhost:8000",
                             data_dir=tmp_path, heartbeat_s=0.1, watchdog_s=1,
                             instruments=[InstrumentSpec(id="superk_01", kind="laser")])
        agent = Agent(config, transport=httpx.MockTransport(blocked))
        await agent.devices["superk_01"].execute("open_shutter", {}, asyncio.Event())
        agent.registered = True
        tasks = [asyncio.create_task(agent.background()), asyncio.create_task(agent.watchdog_loop())]
        try:
            await asyncio.sleep(1.2)
            assert agent.watchdog_tripped
            assert not agent.devices["superk_01"].status()["shutter_open"]
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await agent.close()
    asyncio.run(check())
