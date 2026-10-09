from __future__ import annotations

import asyncio
import math
from abc import ABC, abstractmethod

from .models import InstrumentSpec


class InstrumentDriver(ABC):
    """Reviewed adapters implement this interface; this release enables simulators only."""

    @abstractmethod
    async def execute(self, command: str, parameters: dict, cancel: asyncio.Event) -> dict: ...

    @abstractmethod
    async def safe_shutdown(self) -> None: ...

    @abstractmethod
    def status(self) -> dict: ...


class SimulatedInstrument(InstrumentDriver):
    def __init__(self, spec: InstrumentSpec):
        self.spec = spec
        self.wavelength = min(max(650, spec.wavelength_min_nm), spec.wavelength_max_nm)
        self.angle = spec.angle_min_deg
        self.power = 0.0
        self.shutter = False

    def status(self) -> dict:
        return {"instrument_id": self.spec.id, "kind": self.spec.kind, "mode": "simulated",
                "driver_version": self.spec.driver_version, "stable": True,
                "wavelength_nm": self.wavelength, "angle_deg": self.angle,
                "actual_wavelength_nm": self.wavelength, "actual_angle_deg": self.angle,
                "power_percent": self.power, "shutter_open": self.shutter}

    @staticmethod
    async def wait(seconds: float, cancel: asyncio.Event):
        if cancel.is_set():
            raise asyncio.CancelledError
        try:
            await asyncio.wait_for(cancel.wait(), timeout=seconds)
        except TimeoutError:
            return
        raise asyncio.CancelledError

    def number(self, parameters, name, low, high):
        value = parameters.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be numeric")
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name} outside local limits [{low}, {high}]")
        return float(value)

    async def execute(self, command, parameters, cancel):
        if command not in self.spec.capabilities:
            raise ValueError("capability not approved")
        if command == "safe_shutdown":
            await self.safe_shutdown()
            return self.status()
        await self.wait(0.01, cancel)
        if command == "set_wavelength":
            self.wavelength = self.number(parameters, "nm", self.spec.wavelength_min_nm,
                                          self.spec.wavelength_max_nm)
        elif command == "set_angle":
            self.angle = self.number(parameters, "angle_deg", self.spec.angle_min_deg,
                                     self.spec.angle_max_deg)
        elif command == "set_power":
            self.power = self.number(parameters, "percent", 0, self.spec.power_max_percent)
        elif command == "open_shutter":
            self.shutter = True
        elif command == "acquire_and_store":
            exposure = self.number(parameters, "exposure_ms", 0.001, self.spec.exposure_max_ms)
            wavelength = self.number(parameters, "wavelength_nm", 1, 100000)
            angle = self.number(parameters, "angle_deg", -10000, 10000)
            await self.wait(exposure / 1000, cancel)
            axis = [450 + 3 * i for i in range(128)]
            contrast = 0.2 + 0.8 * math.cos(math.radians(angle)) ** 2
            counts = [round(exposure * contrast * math.exp(-((x-wavelength) / 25) ** 2)
                            + 2, 6) for x in axis]
            return {"spectrum_axis_nm": axis, "counts": counts,
                    "exposure_ms": exposure, "simulated": True}
        return self.status()

    async def safe_shutdown(self):
        self.power = 0.0
        self.shutter = False
