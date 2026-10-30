from __future__ import annotations

import math
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")]
Finite = Annotated[float, Field(allow_inf_nan=False)]
CAPABILITIES = {
    "laser": ["get_status", "set_wavelength", "set_power", "open_shutter", "safe_shutdown"],
    "rotator": ["get_status", "set_angle", "safe_shutdown"],
    "spectrometer": ["get_status", "acquire_and_store", "safe_shutdown"],
}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def intersect_limits(limits: list[tuple[float, float]]) -> tuple[float, float]:
    if not limits or any(not math.isfinite(x) or not math.isfinite(y) or x > y
                         for x, y in limits):
        raise ValueError("invalid limit intersection")
    low, high = max(x for x, _ in limits), min(y for _, y in limits)
    if low > high:
        raise ValueError("empty limit intersection")
    return low, high


class InstrumentSpec(Model):
    id: Identifier
    kind: Literal["laser", "rotator", "spectrometer"]
    mode: Literal["simulated"] = "simulated"
    driver_version: str = "simulator-0.1.0"
    wavelength_min_nm: Finite = 450
    wavelength_max_nm: Finite = 800
    angle_min_deg: Finite = 0
    angle_max_deg: Finite = 180
    power_max_percent: Annotated[float, Field(ge=0, le=100)] = 10
    exposure_max_ms: Annotated[float, Field(gt=0, le=10000)] = 5000
    detector_max_counts: Annotated[float, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def check_ranges(self):
        if self.wavelength_min_nm > self.wavelength_max_nm:
            raise ValueError("reversed wavelength limits")
        if self.angle_min_deg > self.angle_max_deg:
            raise ValueError("reversed angle limits")
        return self

    @property
    def capabilities(self) -> list[str]:
        return CAPABILITIES[self.kind]


class SetupProfile(Model):
    id: Identifier = "optics_demo"
    devices: dict[Literal["laser", "rotator", "spectrometer"], Identifier] = Field(
        default_factory=lambda: {"laser": "superk_01", "rotator": "rotator_01",
                                 "spectrometer": "spectrometer_01"})
    physical_description: str = "SIMULATED optical setup; no physical hardware connected"
    calibration_notes: str = "Synthetic angle and wavelength readbacks; not a calibration"
    operator_confirmed: bool = True

    @model_validator(mode="after")
    def check_devices(self):
        if set(self.devices) != {"laser", "rotator", "spectrometer"}:
            raise ValueError("setup requires laser, rotator and spectrometer")
        if len(set(self.devices.values())) != 3:
            raise ValueError("setup roles require distinct instruments")
        return self


def grid(start: float, stop: float, step: float) -> list[float]:
    a, b, d = (Decimal(str(v)) for v in (start, stop, step))
    if d <= 0 or b < a:
        raise ValueError("invalid scan range")
    count = (b - a) / d
    if abs(count - count.to_integral_value()) > Decimal("0.00000001"):
        raise ValueError("stop must align with the inclusive grid")
    if count > 4999:
        raise ValueError("scan exceeds 5000 points")
    return [float(a + i * d) for i in range(int(count.to_integral_value()) + 1)]


class QualityPolicy(Model):
    max_counts: Annotated[float, Field(gt=0)] | None = None


class DetectorFlags(Model):
    overloaded: StrictBool


class Plan(Model):
    setup_id: Identifier = "optics_demo"
    sample_id: Identifier = "demo_sample"
    wavelength_start_nm: Annotated[float, Field(gt=0)] = 650
    wavelength_stop_nm: Annotated[float, Field(gt=0)] = 650
    wavelength_step_nm: Annotated[float, Field(gt=0)] = 10
    angle_start_deg: Finite = 0
    angle_stop_deg: Finite = 180
    angle_step_deg: Annotated[float, Field(gt=0)] = 10
    exposure_ms: Annotated[float, Field(ge=0.001, le=10000)] = 100
    power_percent: Annotated[float, Field(ge=0, le=100)] = 5
    sample_power_limit_percent: Annotated[float, Field(ge=0, le=100)] = 10
    quality: QualityPolicy = Field(default_factory=QualityPolicy)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def check_grid(self):
        if len(self.points()) > 5000:
            raise ValueError("scan exceeds 5000 points")
        if self.power_percent > self.sample_power_limit_percent:
            raise ValueError("power exceeds sample limit")
        return self

    def points(self) -> list[tuple[float, float]]:
        wavelengths = grid(self.wavelength_start_nm, self.wavelength_stop_nm,
                           self.wavelength_step_nm)
        angles = grid(self.angle_start_deg, self.angle_stop_deg, self.angle_step_deg)
        if len(wavelengths) * len(angles) > 5000:
            raise ValueError("scan exceeds 5000 points")
        return [(w, a) for w in wavelengths for a in angles]
