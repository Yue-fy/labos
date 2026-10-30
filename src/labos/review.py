"""Deterministic evidence-to-action records; no unsupported physical attribution."""
from __future__ import annotations

import json

from .models import Plan
from .quality import UNASSESSED


def build_review(store, run_id) -> dict:
    # One committed database snapshot: no mixture of measurements from different moments.
    with store.transaction() as db:
        run = store.decode_run(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
        rows = db.execute("""SELECT m.id,m.body,m.sha,q.body AS quality FROM measurements m
            LEFT JOIN qualifications q ON m.id=q.measurement_id WHERE m.run_id=? ORDER BY m.point_index""",
                          (run_id,)).fetchall()
        commands = [store.decode_command(r) for r in db.execute(
            "SELECT * FROM commands WHERE run_id=? ORDER BY created DESC", (run_id,))]
        result_times = {}
        for row in db.execute("SELECT time,detail FROM events WHERE run_id=? AND category='COMMAND_RESULT'",
                              (run_id,)):
            result_times[json.loads(row["detail"])["command_id"]] = row["time"]
    counts = {"accepted": 0, "rejected": 0, "unassessed": 0, "total": len(rows)}
    accepted, assessments = [], []
    for row in rows:
        quality = json.loads(row["quality"]) if row["quality"] else UNASSESSED
        counts[quality["status"]] += 1
        assessments.append({"measurement_id": row["id"], "sha256": row["sha"], "quality": quality})
        if quality["status"] == "accepted":
            accepted.append(json.loads(row["body"]))
    closure = {"status": "unconfirmed", "devices": {}, "scope": "Historical software readbacks; no physical inspection"}
    terminal = run["status"] in {"COMPLETED", "FAILED", "ABORTED", "INTERRUPTED"}
    verified = []
    for role, instrument_id in run["setup"]["devices"].items():
        relevant = [c for c in commands if c["instrument_id"] == instrument_id and c["state"] != "CANCELLED"]
        last = relevant[0] if relevant else None
        ok = bool(terminal and last and last["op"] == "safe_shutdown" and last["state"] == "COMPLETED")
        if ok and role == "laser":
            ok = last["result"].get("shutter_open") is False and last["result"].get("power_percent") == 0
        closure["devices"][role] = {"verified": ok, "command_id": last["id"] if last else None,
            "result_recorded_at": result_times.get(last["id"]) if last else None,
            "readback": last["result"] if last and last["op"] == "safe_shutdown" else None}
        verified.append(ok)
    if all(verified):
        closure["status"] = "verified_by_software_readback"
    next_actions = []
    if closure["status"] == "unconfirmed":
        next_actions.append({"action": "Confirm local stop state and reconcile device ownership before another run.",
                             "requires_operator": True, "requires_start": True, "requires_new_preflight": True})
    if counts["rejected"]:
        plan = Plan.model_validate(run["plan"])
        proposed = plan.model_copy(update={"exposure_ms": max(0.001, plan.exposure_ms / 2)})
        next_actions.append({"action": "Inspect detector configuration; consider a shorter-exposure qualification pilot.",
            "reason": "Recovery would establish readability, not the cause of overload or a physical mechanism.",
            "requires_operator": True, "requires_new_preflight": True, "requires_start": True,
            "proposed_plan": proposed.model_dump()})
    elif counts["unassessed"]:
        next_actions.append({"action": "Review historical acquisition evidence; do not promote it as qualified data.",
                             "requires_operator": True})
    else:
        next_actions.append({"action": "Use repeats, dark/reference measurements and return controls to assess precision and drift.",
                             "requires_new_preflight": True, "requires_start": True})
    peaks = [max(m["counts"]) for m in accepted]
    return {"schema_version": 1, "method": "deterministic-optical-review-1", "run_id": run_id,
        "run_status": run["status"], "run_error": run["error"], "simulated": True,
        "provenance": run["preflight"].get("fingerprints", {}),
        "evidence_citations": run["preflight"].get("evidence", []),
        "data_quality": counts, "measurements": assessments,
        "accepted_measurement_ids": [m["measurement_id"] for m in accepted],
        "signal_summary": {"qualified_spectra": len(accepted), "peak_counts_min": min(peaks),
                           "peak_counts_max": max(peaks)} if accepted else None,
        "observations": [f"{counts['accepted']} spectra passed configured operational validity checks.",
                         f"{counts['rejected']} rejected and {counts['unassessed']} unassessed spectra are retained for audit."],
        "limitations": ["Simulation only; no physical instrument or sample validation.",
                        "Operational validity does not establish precision, drift, SNR, equilibrium or a physical cause.",
                        "Source-off software readbacks are not a physical emergency stop or proof of sample safety."],
        "closure": closure, "next_actions": next_actions}
