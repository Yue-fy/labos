"""Operational acquisition validity, separate from scientific precision or interpretation."""
from __future__ import annotations

from .models import QualityPolicy

UNASSESSED = {"version": "optical-validity-1", "status": "unassessed",
              "reasons": ["historical_or_missing_detector_evidence"], "limits": {}}


def assess(measurement, policy: QualityPolicy, detector_ceiling: float | None) -> dict:
    reasons = []
    if measurement.detector_flags and measurement.detector_flags.overloaded:
        reasons.append("detector_overload")
    limits = {"operator_max_counts": policy.max_counts, "detector_max_counts": detector_ceiling}
    for name, ceiling in limits.items():
        if ceiling is not None and max(measurement.counts) >= ceiling:
            reasons.append(name)
    status = "rejected" if reasons else "accepted"
    if not reasons and (measurement.detector_flags is None or not measurement.provenance):
        return {**UNASSESSED, "limits": limits}
    return {"version": "optical-validity-1", "status": status, "reasons": reasons,
            "limits": limits,
            "scope": "Operational validity only; precision, drift and physical cause are unqualified."}
