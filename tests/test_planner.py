import asyncio
from types import SimpleNamespace

import pytest

from labos.models import Plan
from labos.planner import draft_plan


def test_planner_returns_draft_and_does_not_execute(central_config):
    async def check():
        captured = {}
        async def parse(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_parsed=Plan(angle_stop_deg=20))
        client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
        result = await draft_plan("measure 0 to 20 degrees", central_config, client=client,
                                  model="configured-model")
        assert result["requires_start"] is True
        assert result["point_count"] == 3
        assert captured["store"] is False
        assert central_config.admin_token not in str(captured)
        assert "tools" not in captured
    asyncio.run(check())


def test_planner_refusal_cannot_become_an_experiment(central_config):
    async def check():
        async def parse(**kwargs):
            return SimpleNamespace(output_parsed=None)
        client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
        with pytest.raises(ValueError, match="valid plan"):
            await draft_plan("invent hardware", central_config, client=client, model="configured-model")
    asyncio.run(check())
