"""Correlate field qualification and optical context with complete SDK returns."""

from __future__ import annotations

import math
import struct
from .magnet import validate_state

GETTERS = (
    ("getSampleTemperature", ("sample_temperature_k",), "f"),
    ("getUserTemperature", ("user_temperature_k",), "f"),
    ("getVtiTemperature", ("vti_temperature_k",), "f"),
    ("getMagneticFieldX", ("field", "bx_t"), "f"),
    ("getMagneticFieldZ", ("field", "bz_t"), "f"),
    ("getMagneticFieldSetPointX", ("field_setpoint", "bx_t"), "f"),
    ("getMagneticFieldSetPointZ", ("field_setpoint", "bz_t"), "f"),
    ("isControllingTemperature", ("temperature_control_enabled",), "i"),
    ("isControllingField", ("field_control_enabled",), "i"),
    ("getAttodryErrorStatus", ("error_code",), "b"),
)


def validate_raw_evidence(result, config):
    events = result["magnetic_events"]
    req = {
        e["call_id"]: e
        for e in events
        if e.get("event") == "sdk_call" and e.get("phase") == "requested"
    }
    ret = {
        e["call_id"]: e
        for e in events
        if e.get("event") == "sdk_call" and e.get("phase") == "returned"
    }
    indices = [e.get("call_index") for e in req.values()]
    if indices != list(range(1, len(req) + 1)) or any(
        ret[k].get("call_index") != v["call_index"] for k, v in req.items()
    ):
        raise ValueError("raw SDK sequence is incomplete or reordered")
    states = {}
    phases = {}
    for e in events:
        if e.get("event") == "magnetic_state":
            ident = e.get("state_id")
            if not ident:
                raise ValueError("raw magnetic state lacks an identity")
            old = states.get(ident)
            if old and any(
                old[k] != e[k] for k in ("state", "sdk_call_ids", "observed_monotonic_s")
            ):
                raise ValueError("one state identity has conflicting raw evidence")
            states[ident] = e
            phases.setdefault((ident, e.get("phase")), []).append(e)
        if e.get("event") in {
            "magnetic_exception",
            "child_final_close_error",
            "parent_connection_lost",
        }:
            raise ValueError("completed campaign contains SDK failure evidence")

    def proof(observation, target=None, control=None):
        ident = observation.get("state_id")
        e = states.get(ident)
        if e is None or any(
            observation.get(k) != e[k] for k in ("state", "sdk_call_ids", "observed_monotonic_s")
        ):
            raise ValueError("observation has no matching raw magnetic state")
        calls = e["sdk_call_ids"]
        if len(calls) != 10 or len(set(calls)) != 10 or any(k not in ret for k in calls):
            raise ValueError("raw state requires ten complete getter returns")
        order = [ret[k]["call_index"] for k in calls]
        if order != list(range(order[0], order[0] + 10)):
            raise ValueError("raw state getters are not contiguous")
        for ident, (name, path, fmt) in zip(calls, GETTERS):
            call = ret[ident]
            if call["symbol"] != "AttoDRY_Interface_" + name:
                raise ValueError("raw state getter identity/order differs")
            value = e["state"]
            for key in path:
                value = value[key]
            output = call["arguments_after"][0]
            try:
                decoded = struct.unpack("<" + fmt, bytes.fromhex(output["storage_hex"]))[0]
            except (ValueError, KeyError, struct.error) as exc:
                raise ValueError("raw getter pointer bytes are invalid") from exc
            if decoded != output.get("value") or decoded != value:
                raise ValueError("state contradicts raw SDK output pointer")
        timestamp = e["observed_monotonic_s"]
        if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
            raise ValueError("invalid host state timestamp")
        validate_state(e["state"], config, target=target, require_control=control)
        return e, order[0], order[-1]

    def dwell(observations, z, control, final_phase=False):
        if len(observations) < 3 or len({o.get("state_id") for o in observations}) != len(
            observations
        ):
            raise ValueError("qualification lacks distinct full-state observations")
        times = []
        orders = []
        for o in observations:
            _, first, last = proof(o, z, control)
            if not final_phase and not phases.get((o["state_id"], "field_stability")):
                raise ValueError("qualification lacks raw field-stability events")
            elapsed = o.get("qualification_elapsed_s")
            if elapsed is not None:
                if not any(
                    e.get("elapsed_s") == elapsed
                    for e in phases.get((o["state_id"], "field_stability"), [])
                ):
                    raise ValueError("qualification time differs from driver callback")
            times.append(o["observed_monotonic_s"] if elapsed is None else elapsed)
            orders.append((first, last))
        if any(b <= a for a, b in zip(times, times[1:])) or times[-1] - times[0] < 10.0:
            raise ValueError("qualification does not cover a continuous ten-second dwell")
        if any(b[0] <= a[1] for a, b in zip(orders, orders[1:])):
            raise ValueError("qualification reuses or reorders getter observations")
        for axis in ("bx_t", "bz_t"):
            values = [o["state"]["field"][axis] for o in observations]
            if max(values) - min(values) > 0.0005:
                raise ValueError("qualification peak-to-peak range is unstable")
        return orders[0][0], orders[-1][1]

    initial = result["magnetic_initial"]
    mode = initial["initial_state"]["field_control_enabled"]
    initial_observation = initial.get("initial_observation", {})
    proof(initial_observation, 0.0, mode)
    if initial_observation["state"] != initial["initial_state"]:
        raise ValueError("initial mode/state differs from raw initialization evidence")
    setters = [
        e["call_index"] for e in req.values() if e["symbol"].endswith("setUserMagneticFieldZ")
    ]
    zero_index = next(
        e["call_index"] for e in req.values() if e["symbol"].endswith("sweepFieldToZero")
    )
    toggles = [
        e["call_index"] for e in req.values() if e["symbol"].endswith("toggleMagneticFieldControl")
    ]
    if len(toggles) != (0 if mode else 2) or (
        not mode and not (toggles[0] < setters[0] and toggles[1] > zero_index)
    ):
        raise ValueError("raw field-control enable/restore transition differs")
    for index, point in enumerate(result["points"]):
        observations = point["field"].get("qualification_observations", [])
        first, last = dwell(observations, point["target_z_t"], True)
        if (
            first <= setters[index]
            or point["field"].get("state_id") != observations[-1]["state_id"]
            or point["field"]["state"] != observations[-1]["state"]
        ):
            raise ValueError("point field summary differs from raw final qualification")
        next_write = setters[index + 1] if index + 1 < len(setters) else zero_index
        for sample in point["optical"]["samples"]:
            _, before, _ = proof(sample["magnetic_before"], point["target_z_t"], True)
            _, after, end = proof(sample["magnetic_after"], point["target_z_t"], True)
            if not last < before < after <= end < next_write:
                raise ValueError("optical sample is outside its qualified field-hold interval")
    zero = result["zero"]
    first, last = dwell(zero.get("controlled_zero_qualification", []), 0.0, True)
    if first <= zero_index or (not mode and last >= toggles[-1]):
        raise ValueError("controlled zero and mode restoration are out of order")
    first, _ = dwell(zero["post_restore_zero_observations"], 0.0, mode, final_phase=True)
    if first <= last or (not mode and first <= toggles[-1]):
        raise ValueError("post-restore zero observation precedes controlled zero/mode restoration")
