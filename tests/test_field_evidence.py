"""Complete synthetic wire evidence, with individually removable SDK records."""

import copy
import struct

import pytest

from labos_field.engine import validate_campaign
from labos_field.magnet import SOURCE_SHA, DLL_SHA
from test_field_engine import run

GETTERS = [
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
]


def complete_evidence(task=None):
    result, _, _ = run(task=task)
    events = []
    sequence = [0]
    moment = [0.0]

    def call(name, args=None, output=None):
        sequence[0] += 1
        ident = "call-" + str(sequence[0])
        row = {
            "event": "sdk_call",
            "call_id": ident,
            "call_index": sequence[0],
            "symbol": "AttoDRY_Interface_" + name,
            "started_monotonic_s": moment[0],
            "arguments_before": args or [],
        }
        events.append({**row, "phase": "requested"})
        events.append(
            {
                **row,
                "phase": "returned",
                "return_code": 0,
                "ended_monotonic_s": moment[0] + 0.0001,
                "arguments_after": output or args or [],
            }
        )
        return ident

    def observe(state, phase="read"):
        ids = []
        for symbol, path, fmt in GETTERS:
            value = state
            for key in path:
                value = value[key]
            if fmt != "f":
                value = int(value)
            output = {"value": value, "storage_hex": struct.pack("<" + fmt, value).hex()}
            ids.append(
                call(symbol, [{"value": 0, "storage_hex": ("00" * struct.calcsize(fmt))}], [output])
            )
        item = {
            "state_id": "state-" + str(sequence[0]),
            "state": copy.deepcopy(state),
            "observed_monotonic_s": moment[0],
            "sdk_call_ids": ids,
        }
        events.append({"event": "magnetic_state", **item, "phase": phase})
        moment[0] += 0.1
        return item

    def dwell(state):
        values = []
        for i in range(12):
            values.append(observe(state, "field_stability"))
            moment[0] += 0.9
        return values

    call("begin", [1])
    call("Connect", ["COM5"])
    call("isDeviceInitialised", [], [{"value": 1, "storage_hex": "01000000"}])
    initial = result["magnetic_initial"]["initial_state"]
    result["magnetic_initial"].update(
        source_hashes=SOURCE_SHA, dll_sha256=DLL_SHA, initial_observation=observe(initial)
    )
    call("toggleMagneticFieldControl")
    for point in result["points"]:
        z = point["target_z_t"]
        call("setUserMagneticFieldZ", [z])
        point["field"]["qualification_observations"] = dwell(point["field"]["state"])
        point["field"]["state_id"] = point["field"]["qualification_observations"][-1]["state_id"]
        for sample in point["optical"]["samples"]:
            sample["magnetic_before"] = observe(point["field"]["state"])
            moment[0] += 0.2
            sample["magnetic_after"] = observe(point["field"]["state"])
    call("sweepFieldToZero")
    controlled = copy.deepcopy(result["zero"]["state"])
    controlled["field_control_enabled"] = True
    result["zero"]["controlled_zero_qualification"] = dwell(controlled)
    call("toggleMagneticFieldControl")
    result["zero"]["post_restore_zero_observations"] = dwell(result["zero"]["state"])
    call("Disconnect")
    call("end")
    result["magnetic_events"] = events
    return result


def test_complete_raw_evidence_has_a_positive_acceptance_case():
    assert validate_campaign(complete_evidence(), require_raw=True)["accepted"] is True


@pytest.mark.parametrize(
    "damage", ["getter_pair", "dwell_events", "qualification", "mode_transition", "pointer_value"]
)
def test_complete_record_deletions_and_contradictions_are_rejected(damage):
    result = complete_evidence()
    events = result["magnetic_events"]
    if damage == "getter_pair":
        ident = next(
            e["call_id"] for e in events if e.get("symbol", "").endswith("getSampleTemperature")
        )
        result["magnetic_events"] = [e for e in events if e.get("call_id") != ident]
    elif damage == "dwell_events":
        result["magnetic_events"] = [e for e in events if e.get("phase") != "field_stability"]
    elif damage == "qualification":
        result["points"][1]["field"]["qualification_observations"] = []
    elif damage == "mode_transition":
        ident = [
            e["call_id"]
            for e in events
            if e.get("phase") == "requested"
            and e.get("symbol", "").endswith("toggleMagneticFieldControl")
        ][-1]
        result["magnetic_events"] = [e for e in events if e.get("call_id") != ident]
    else:
        row = next(
            e
            for e in events
            if e.get("phase") == "returned" and e.get("symbol", "").endswith("getMagneticFieldZ")
        )
        row["arguments_after"][0] = {"value": 0.2, "storage_hex": struct.pack("<f", 0.2).hex()}
    with pytest.raises(ValueError):
        validate_campaign(result, require_raw=True)
