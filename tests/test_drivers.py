import asyncio

import pytest

from labos.drivers import SimulatedInstrument
from labos.models import InstrumentSpec


def test_simulator_limits_and_capability_allowlist():
    async def check():
        device = SimulatedInstrument(InstrumentSpec(id="rotator_01", kind="rotator"))
        result = await device.execute("set_angle", {"angle_deg": 45}, asyncio.Event())
        assert result["actual_angle_deg"] == 45
        with pytest.raises(ValueError):
            await device.execute("set_angle", {"angle_deg": 361}, asyncio.Event())
        with pytest.raises(ValueError):
            await device.execute("shell_command", {}, asyncio.Event())
    asyncio.run(check())


def test_cancellation_and_safe_shutdown():
    async def check():
        device = SimulatedInstrument(InstrumentSpec(id="laser_01", kind="laser"))
        await device.execute("set_power", {"percent": 10}, asyncio.Event())
        cancel = asyncio.Event()
        cancel.set()
        with pytest.raises(asyncio.CancelledError):
            await device.execute("set_wavelength", {"nm": 650}, cancel)
        await device.safe_shutdown()
        assert device.status()["power_percent"] == 0
        assert device.status()["shutter_open"] is False
    asyncio.run(check())
