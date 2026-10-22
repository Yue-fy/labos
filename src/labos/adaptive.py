"""Bounded deterministic analysis; no driver, network, cloud or simulator truth access."""
from __future__ import annotations

import math
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from .models import Plan

POLICY_VERSION = "single-resonance-0.1.0"


def analyze_peak(plan: Plan, measurements: list[dict], min_contrast: float) -> dict:
    """Find an unambiguous interior maximum in a complete fixed-angle scan.

    Signal is integrated counts above each spectrum's minimum, normalized by
    exposure and power. Peak uncertainty is the sampling half-step, not a fit.
    """
    points = plan.points()
    if (len(measurements) != len(points) or len(points) < 3
            or plan.angle_start_deg != plan.angle_stop_deg):
        raise ValueError("peak analysis requires a complete fixed-polarization scan")
    if not math.isfinite(min_contrast) or not 0 < min_contrast <= 1:
        raise ValueError("invalid peak contrast threshold")
    signals, reference_axis = [], None
    for row, (wavelength, angle) in zip(measurements, points):
        if (row.get("simulated") is not True or row.get("wavelength_nm") != wavelength
                or row.get("angle_deg") != angle):
            raise ValueError("non-simulated, missing, duplicate or out-of-order measurement")
        axis, counts = row.get("spectrum_axis_nm", []), row.get("counts", [])
        if (len(axis) != len(counts) or len(counts) < 3
                or any(isinstance(x, bool) or not isinstance(x, (int, float))
                       or not math.isfinite(x) for x in [*axis, *counts])
                or any(x < 0 for x in counts)
                or any(a >= b for a, b in zip(axis, axis[1:]))):
            raise ValueError("invalid spectrum for peak analysis")
        if reference_axis is not None and axis != reference_axis:
            raise ValueError("spectral axis changed within round")
        reference_axis = axis
        exposure, power = row.get("exposure_ms"), row.get("power_percent")
        if exposure != plan.exposure_ms or power != plan.power_percent or min(exposure, power) <= 0:
            raise ValueError("invalid or changing acquisition normalization")
        signal = math.fsum(x - min(counts) for x in counts) / exposure / power
        if not math.isfinite(signal):
            raise ValueError("nonfinite integrated signal")
        signals.append(signal)
    index = max(range(len(signals)), key=signals.__getitem__)
    maximum, minimum = signals[index], min(signals)
    contrast = (maximum-minimum) / maximum if maximum > 0 else 0
    if contrast < min_contrast:
        raise ValueError("no peak with sufficient contrast; refinement refused")
    if index in {0, len(signals)-1}:
        raise ValueError("peak is at scan boundary; refinement refused")
    # Count competing peak regions, including terminal peaks and plateaus.
    # Strict interior extrema alone silently discard those alternatives.
    candidates, left = [], 0
    while left < len(signals):
        right = left
        while right+1 < len(signals) and signals[right+1] == signals[left]:
            right += 1
        if (signals[left] >= 0.95 * maximum
                and (left == 0 or signals[left] > signals[left-1])
                and (right == len(signals)-1 or signals[right] > signals[right+1])):
            candidates.append((left, right))
        left = right+1
    if candidates != [(index, index)]:
        raise ValueError("ambiguous or plateau peak; refinement refused")
    return {"peak_nm": points[index][0], "sampling_half_step_nm": plan.wavelength_step_nm / 2,
            "contrast": contrast, "signal": signals, "point_count": len(points),
            "signal_definition": "sum(counts-min(counts))/exposure_ms/power_percent",
            "policy_version": POLICY_VERSION}


def refine_plan(plan: Plan, peak_nm: float, step_nm: float) -> Plan:
    """Select a narrower inclusive grid inside the previous approved envelope."""
    if (not math.isfinite(peak_nm) or not math.isfinite(step_nm)
            or not plan.wavelength_start_nm < peak_nm < plan.wavelength_stop_nm):
        raise ValueError("peak must be inside the approved scan interval")
    if not 0 < step_nm < plan.wavelength_step_nm:
        raise ValueError("refinement step must strictly decrease")
    start, stop, previous_step, peak, step = map(Decimal, map(str, (
        plan.wavelength_start_nm, plan.wavelength_stop_nm,
        plan.wavelength_step_nm, peak_nm, step_nm)))
    lower, upper = max(start, peak-2*previous_step), min(stop, peak+2*previous_step)
    lower = start + ((lower-start)/step).to_integral_value(rounding=ROUND_CEILING)*step
    upper = start + ((upper-start)/step).to_integral_value(rounding=ROUND_FLOOR)*step
    if upper-lower >= stop-start or upper-lower < 2*step or not lower < peak < upper:
        raise ValueError("no narrower safe interval with an interior peak and at least 3 points")
    return Plan.model_validate({**plan.model_dump(), "adaptive": None,
        "wavelength_start_nm": float(lower), "wavelength_stop_nm": float(upper),
        "wavelength_step_nm": float(step)})
