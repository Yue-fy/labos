import asyncio

from labos.agent import Agent
from labos.config import AgentConfig
from labos.models import InstrumentSpec


def test_automatic_shutdown_preserves_fault_until_explicit_recovery(tmp_path):
    async def check():
        agent = Agent(AgentConfig(agent_id="pc-a", token="A"*40,
            server_url="http://localhost:8000", data_dir=tmp_path,
            instruments=[InstrumentSpec(id="superk_01", kind="laser")]))
        base = {"run_id": "run_test", "instrument_id": "superk_01"}
        try:
            await agent.execute({**base, "id": "cmd_power", "op": "set_power",
                                 "parameters": {"percent": 5}})
            agent.last_contact = 0
            await agent.watchdog_once()
            result = await agent.execute({**base, "id": "cmd_automatic", "op": "safe_shutdown",
                                          "parameters": {"preserve_fault": True}})
            assert result["state"] == "COMPLETED"
            assert result["result"].get("fault_latched") is True
            assert agent.statuses()["superk_01"]["fault_latched"]
            refused = await agent.execute({**base, "id": "cmd_refused", "op": "set_wavelength",
                                           "parameters": {"nm": 650}})
            assert refused["state"] == "FAILED"
            # Existing explicit recovery command remains compatible.
            recovered = await agent.execute({**base, "id": "cmd_manual", "op": "safe_shutdown",
                                             "parameters": {}})
            assert recovered["state"] == "COMPLETED"
            assert not recovered["result"]["fault_latched"]
            assert not agent.statuses()["superk_01"]["fault_latched"]
        finally:
            await agent.close()
    asyncio.run(check())
