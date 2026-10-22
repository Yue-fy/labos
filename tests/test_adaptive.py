import asyncio
import importlib
import math

import pytest

from labos import models
from labos.drivers import SimulatedInstrument
from labos.models import InstrumentSpec, Plan


def adaptive_plan(**changes):
    return Plan(wavelength_start_nm=changes.pop("wavelength_start_nm", 500),
                wavelength_stop_nm=changes.pop("wavelength_stop_nm", 800),
                wavelength_step_nm=changes.pop("wavelength_step_nm", 20),
                angle_stop_deg=0, exposure_ms=1,
                adaptive=changes.pop("adaptive", {"simulation_approved": True}), **changes)


def spectra(plan, center=635, width=18):
    return [{"wavelength_nm": w, "angle_deg": a, "exposure_ms": plan.exposure_ms,
             "power_percent": plan.power_percent, "simulated": True,
             "spectrum_axis_nm": [600, 650, 700],
             "counts": [2, 2 + 100 * math.exp(-0.5 * ((w-center)/width)**2), 2]}
            for w, a in plan.points()]


def policy():
    return importlib.import_module("labos.adaptive")


def test_adaptive_requires_explicit_simulation_approval():
    assert hasattr(models, "AdaptiveScan"), "adaptive approval schema is missing"
    for approval in ({}, {"simulation_approved": False}, {"simulation_approved": "true"}):
        with pytest.raises(ValueError):
            adaptive_plan(adaptive=approval)
    assert adaptive_plan().adaptive.simulation_approved is True


@pytest.mark.parametrize("settings", [
    {"refinement_steps_nm": []}, {"refinement_steps_nm": [5, 5]},
    {"refinement_steps_nm": [25, 1]}, {"refinement_steps_nm": [1, 5]},
    {"refinement_steps_nm": [5, float("nan")]},
    {"refinement_steps_nm": [5, 4, 3, 2, 1]},
    {"max_total_points": 15}, {"max_total_points": 5001},
    {"min_contrast": 0}, {"min_contrast": float("inf")},
])
def test_adaptive_rejects_invalid_limits(settings):
    with pytest.raises(ValueError):
        adaptive_plan(adaptive={"simulation_approved": True, **settings})


def test_adaptive_requires_fixed_polarization_and_positive_power():
    base = adaptive_plan().model_dump()
    with pytest.raises(ValueError, match="polarization"):
        Plan.model_validate({**base, "angle_stop_deg": 10})
    with pytest.raises(ValueError, match="power"):
        Plan.model_validate({**base, "power_percent": 0})


@pytest.mark.parametrize("center", [635, 707])
def test_policy_follows_measured_peak_through_two_refinements(center):
    plan = adaptive_plan()
    for step in [5, 1]:
        peak = policy().analyze_peak(plan, spectra(plan, center), 0.1)
        assert abs(peak["peak_nm"] - center) <= plan.wavelength_step_nm / 2
        next_plan = policy().refine_plan(plan, peak["peak_nm"], step)
        assert plan.wavelength_start_nm <= next_plan.wavelength_start_nm
        assert next_plan.wavelength_stop_nm <= plan.wavelength_stop_nm
        assert next_plan.wavelength_step_nm == step
        assert next_plan.adaptive is None
        plan = next_plan
    assert abs(policy().analyze_peak(plan, spectra(plan, center), 0.1)["peak_nm"] - center) <= 0.5


def test_refinement_clips_and_aligns_to_approved_interval():
    plan = adaptive_plan(wavelength_start_nm=501, wavelength_stop_nm=801)
    refined = policy().refine_plan(plan, 521, 5)
    assert (refined.wavelength_start_nm, refined.wavelength_stop_nm) == (501, 561)
    assert all(501 <= w <= 801 for w, _ in refined.points())
    with pytest.raises(ValueError, match="peak"):
        policy().refine_plan(plan, 900, 5)


@pytest.mark.parametrize("failure", ["flat", "edge", "ambiguous", "nan", "negative",
                                      "missing", "duplicate", "real", "axis"])
def test_policy_rejects_untrustworthy_data(failure):
    plan = adaptive_plan()
    rows = spectra(plan)
    if failure == "flat":
        for row in rows:
            row["counts"] = [2, 3, 2]
    elif failure == "edge":
        rows = spectra(plan, center=500)
    elif failure == "ambiguous":
        for row in rows:
            w = row["wavelength_nm"]
            row["counts"][1] = 2 + 100 * (math.exp(-((w-580)/10)**2)
                                         + math.exp(-((w-720)/10)**2))
    elif failure == "nan":
        rows[0]["counts"][1] = float("nan")
    elif failure == "negative":
        rows[0]["counts"][1] = -1
    elif failure == "missing":
        rows.pop()
    elif failure == "duplicate":
        rows[-1] = dict(rows[-2])
    elif failure == "real":
        rows[0]["simulated"] = False
    else:
        rows[0]["spectrum_axis_nm"] = [600, 600, 700]
    with pytest.raises(ValueError):
        policy().analyze_peak(plan, rows, 0.1)


def test_seeded_simulator_has_hidden_excitation_resonance():
    async def check():
        spec = InstrumentSpec(id="spectrometer_01", kind="spectrometer",
                              simulation_response={"peak_nm": 635, "seed": 42,
                                                   "relative_noise": 0.001})
        device = SimulatedInstrument(spec)
        async def acquire(w):
            return await device.execute("acquire_and_store", {"exposure_ms": 1,
                "wavelength_nm": w, "angle_deg": 0}, asyncio.Event())
        peak = await acquire(635)
        assert peak == await acquire(635)
        assert sum(peak["counts"]) > 5 * sum((await acquire(750))["counts"])
        assert peak["simulated"] is True
        with pytest.raises(ValueError):
            InstrumentSpec(id="laser_01", kind="laser", simulation_response={"peak_nm": 635})
    asyncio.run(check())


@pytest.mark.parametrize("signals", [
    [1, 1, 1, 1, 1, 1, 1, 100, 1, 1, 1, 1, 1, 1, 1, 100],
    [1, 1, 1, 1, 1, 1, 1, 100, 1, 1, 1, 100, 100, 1, 1, 1],
])
def test_equal_boundary_or_plateau_competitor_is_ambiguous(signals):
    scan = adaptive_plan()
    rows = spectra(scan)
    for row, signal in zip(rows, signals):
        row["counts"] = [2, 2+signal, 2]
    with pytest.raises(ValueError, match="ambiguous"):
        policy().analyze_peak(scan, rows, 0.1)
