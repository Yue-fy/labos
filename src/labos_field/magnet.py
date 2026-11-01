"""Pinned low-level attoDRY reuse; no production workflow or rate programming."""

from __future__ import annotations

import ctypes
from collections import deque
from dataclasses import asdict
import hashlib
import importlib
import importlib.abc
import importlib.util
import math
from pathlib import Path
import struct
import sys
import time
import types
import uuid

from labos.cryostat_pilot import StationLease
from .models import TARGETS

SOURCE_SHA = {
    "attodry": "f801686ce60b9dfd516aa51ba11852dbfe7cb5619578cb9a80220841698bd5dd",
    "config": "d0f668ef7118723262206a5eab85703cd110fb3714b76083fc023b647514a6ca",
    "models": "c5ba82e95422ac01c12b16c0c07ccbc334a5240c5d76a31eabce659c69fc25cc",
    "safety": "6d9754c1618ae1dc9e6627c315efae359eae922b95251f1d45d351039bcdc8e9",
    "stability": "79164d16ed6be0ef68aa59f3c15ba61812dc303bc61df0af4fe1ef9833ea18a1",
    "field_segments": "a3946819e30b9a4649fa2506d2b4ae77b8f401847eb284f11cf2557e60a9efcf",
    "lockin_autorange": "8d72bda2384cef2857960931960104956973b58cd81158f68fd64398bf3a00e1",
    "scans": "e0c8567e804e058d0ffc4fec17b23dc0fe1d7a899f2c12b6382d8997aa0e5549",
    "sr830_settings": "35667567e49bdc42199bf6a69be59b366b773132c01edf41b5c6258d69a31f3b",
}
DLL_SHA = "4d71758c25c15328214f1a2c5823203e6aa4df42130decaaa0200bdb18625be2"
READS = {
    "begin",
    "Connect",
    "isDeviceInitialised",
    "getSampleTemperature",
    "getUserTemperature",
    "getVtiTemperature",
    "getMagneticFieldX",
    "getMagneticFieldZ",
    "getMagneticFieldSetPointX",
    "getMagneticFieldSetPointZ",
    "isControllingTemperature",
    "isControllingField",
    "getAttodryErrorStatus",
    "Disconnect",
    "end",
}
WRITES = {
    "setUserMagneticFieldX",
    "setUserMagneticFieldZ",
    "toggleMagneticFieldControl",
    "sweepFieldToZero",
}
TOL = max(0.0015, struct.unpack("f", struct.pack("f", 0.0015))[0])


def validate_state(state, config, target=None, require_control=None):
    for key in ("sample_temperature_k", "user_temperature_k", "vti_temperature_k"):
        if (
            type(state.get(key)) not in (int, float)
            or not math.isfinite(state[key])
            or state[key] <= 0
        ):
            raise ValueError("invalid temperature state")
    if (
        abs(state["sample_temperature_k"] - config.temperature_baseline_k)
        > config.temperature_drift_max_k
        or abs(state["user_temperature_k"] - config.temperature_setpoint_k) > 0.0001
        or state.get("temperature_control_enabled") is not True
    ):
        raise ValueError("temperature/setpoint/control differs from the preserved baseline")
    if type(state.get("error_code")) is not int or state["error_code"] != 0:
        raise ValueError("nonzero or unknown magnetic device fault")
    for key in ("field", "field_setpoint"):
        for axis in ("bx_t", "bz_t"):
            v = state[key][axis]
            if type(v) not in (float, int) or not math.isfinite(v):
                raise ValueError("invalid magnetic readback")
    actual, commanded = state["field"], state["field_setpoint"]
    if (
        abs(actual["bx_t"]) > TOL
        or abs(actual["bz_t"]) > 0.5 + TOL
        or abs(commanded["bx_t"]) > 0.0002
        or abs(commanded["bz_t"]) > 0.5002
    ):
        raise ValueError("magnetic field outside campaign envelope")
    if require_control is not None and state.get("field_control_enabled") is not require_control:
        raise ValueError("unexpected magnetic control mode")
    if target is not None and (
        abs(actual["bz_t"] - target) > TOL or abs(commanded["bz_t"] - target) > 0.0002
    ):
        raise ValueError("actual field or acknowledged setpoint is not at target")
    if target == 0 and math.hypot(actual["bx_t"], actual["bz_t"]) > TOL:
        raise ValueError("zero-field resultant exceeds tolerance")


def _argument(value):
    if hasattr(value, "_obj"):
        item = value._obj
        v = item.value
        if isinstance(v, float) and not math.isfinite(v):
            v = {"nonfinite": repr(v)}
        return {
            "value": v,
            "storage_hex": ctypes.string_at(ctypes.addressof(item), ctypes.sizeof(item)).hex(),
        }
    item = getattr(value, "value", value)
    return item.decode("ascii") if isinstance(item, bytes) else item


class _Function:
    def __init__(self, function, name, events, guard, counter=None):
        object.__setattr__(self, "function", function)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "guard", guard)
        object.__setattr__(self, "counter", counter if counter is not None else [0])

    def __getattr__(self, name):
        return getattr(self.function, name)

    def __setattr__(self, name, value):
        setattr(self.function, name, value)

    def __call__(self, *args):
        self.guard(self.name)
        self.counter[0] += 1
        record = {
            "event": "sdk_call",
            "call_id": uuid.uuid4().hex,
            "call_index": self.counter[0],
            "symbol": self.name,
            "started_monotonic_s": time.monotonic(),
            "arguments_before": [_argument(v) for v in args],
        }
        self.events({**record, "phase": "requested"})
        try:
            code = int(self.function(*args))
            record.update(return_code=code, arguments_after=[_argument(v) for v in args])
            return code
        except BaseException as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.events({**record, "phase": "returned", "ended_monotonic_s": time.monotonic()})
            self.guard(self.name)


class _DLL:
    def __init__(self, raw, events, guard):
        self.raw, self.events, self.guard = raw, events, guard
        self.functions = {}
        self.counter = [0]

    def __getattr__(self, name):
        if name not in self.functions:
            self.functions[name] = _Function(
                getattr(self.raw, name), name, self.events, self.guard, self.counter
            )
        return self.functions[name]


def load_reviewed_driver(config, events, guard=lambda name: None):
    source = Path(config.magnetic_source_dir).resolve()
    for name, expected in SOURCE_SHA.items():
        p = source / (name + ".py")
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError("reviewed source hash mismatch: " + name)
    dll_path = Path(config.dll_path)
    if (
        struct.calcsize("P") != 8
        or not dll_path.is_file()
        or hashlib.sha256(dll_path.read_bytes()).hexdigest() != DLL_SHA
    ):
        raise ValueError("reviewed 64-bit vendor DLL hash mismatch")
    namespace = "_labos_field_reviewed"
    if namespace in sys.modules:
        raise ValueError("reviewed driver namespace already loaded")

    class ReviewedSource(importlib.abc.Loader):
        def create_module(self, spec):
            return None

        def exec_module(self, loaded):
            short = loaded.__name__.rsplit(".", 1)[-1]
            path = source / (short + ".py")
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != SOURCE_SHA[short]:
                raise ImportError("reviewed source changed during import")
            loaded.__file__ = str(path)
            exec(compile(content, str(path), "exec"), loaded.__dict__)

    class Restricted(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.startswith(namespace + "."):
                if fullname.split(".")[-1] not in SOURCE_SHA:
                    raise ImportError("unreviewed production dependency")
                return importlib.util.spec_from_loader(fullname, ReviewedSource())
            return None

    package = types.ModuleType(namespace)
    package.__path__ = [str(source)]
    sys.modules[namespace] = package  # Deliberately never execute production __init__.
    sys.meta_path.insert(0, Restricted())
    module = importlib.import_module(namespace + ".attodry")
    for name, loaded in tuple(sys.modules.items()):
        if name.startswith(namespace + "."):
            short = name.rsplit(".", 1)[-1]
            if (
                short not in SOURCE_SHA
                or Path(loaded.__file__).resolve() != source / (short + ".py")
                or hashlib.sha256(Path(loaded.__file__).read_bytes()).hexdigest()
                != SOURCE_SHA[short]
            ):
                raise ValueError("imported module differs from reviewed source")
    safety = sys.modules[namespace + ".safety"]
    cfg = sys.modules[namespace + ".config"]
    stability = sys.modules[namespace + ".stability"]
    raw = module.load_attodry_dll(dll_path)
    wrapped = _DLL(raw, events, guard)
    limits = safety.MagnetLimits(3.0, 9.0, 3.0)
    field = cfg.StabilityConfig(stability.StabilityCriteria(0.0015, 0.0005, 10.0), 1.0, 900.0)
    temp = cfg.StabilityConfig(stability.StabilityCriteria(0.05, 0.05, 30.0), 1.5, 1800.0)
    driver = module.AttoDryDriver(
        dll=wrapped,
        com_port="COM5",
        device_type=1,
        connection_timeout_s=60.0,
        temperature_min_k=1.6,
        temperature_max_k=300.0,
        limits=limits,
        field_stability=field,
        temperature_stability=temp,
        connection_authorized=True,
        writes_authorized=False,
        readback_tolerance_t=0.0015,
        setpoint_ack_tolerance_t=0.0002,
    )
    driver.field_readback_policy = safety.FieldReadbackPolicy.from_targets(
        [module.VectorField(0.0, z) for z in TARGETS], limits, 0.0015, command_scoped=True
    )
    return driver, module.VectorField


class MagnetSession:
    def __init__(
        self, config, events, *, driver=None, vector=None, clock=time.monotonic, sleep=time.sleep
    ):
        self.config, self.events, self.driver, self.vector = config, events, driver, vector
        self.clock, self.sleep = clock, sleep
        self.deadline = math.inf
        self.writes = False
        self.initial_control = None
        self.leases = []
        self.closed = False
        self.close_error = None
        self.control_started = False
        self.recent_sdk_calls = deque(maxlen=10)
        self.last_observation = None
        self.qualification_buffer = None

    def audit_event(self, event):
        if event.get("event") == "sdk_call" and event.get("phase") == "returned":
            self.recent_sdk_calls.append(event)
        self.events(event)

    def guard(self, symbol=None):
        name = symbol.removeprefix("AttoDRY_Interface_") if symbol else None
        if name and (name not in READS | WRITES or (name in WRITES and not self.writes)):
            raise ValueError("SDK command outside approved scope")
        if name not in {"Disconnect", "end"} and self.clock() >= self.deadline:
            raise TimeoutError("magnetic stage deadline exceeded")

    def sample(self, state, elapsed=0.0, phase="read", waypoint=None):
        raw = asdict(state)
        ids = [e["call_id"] for e in self.recent_sdk_calls]
        if (
            len(ids) == 10
            and self.last_observation
            and self.last_observation["sdk_call_ids"] == ids
        ):
            observation = self.last_observation
        else:
            observation = {
                "state": raw,
                "state_id": uuid.uuid4().hex,
                "observed_monotonic_s": self.clock(),
                "sdk_call_ids": ids,
                "device_acquisition_timestamp": None,
            }
        self.last_observation = observation
        self.events(
            {
                **observation,
                "event": "magnetic_state",
                "elapsed_s": elapsed,
                "phase": phase,
                "waypoint_index": waypoint,
                "monotonic_s": self.clock(),
                "device_acquisition_timestamp": None,
            }
        )
        if self.qualification_buffer is not None and phase == "field_stability":
            self.qualification_buffer.append({**observation, "qualification_elapsed_s": elapsed})
        validate_state(raw, self.config)
        self.guard()
        return raw

    def kwargs(self):
        return {"monotonic": self.clock, "sleeper": self.pause, "on_sample": self.sample}

    def pause(self, seconds):
        self.guard()
        self.sleep(min(seconds, max(0.0, self.deadline - self.clock())))
        self.guard()

    def open(self, writes=False):
        self.writes = writes
        for p in sorted(self.config.magnetic_lease_profiles, key=str):
            lease = StationLease(p)
            lease.open()
            self.leases.append(lease)
        if self.driver is None:
            self.driver, self.vector = load_reviewed_driver(
                self.config, self.audit_event, self.guard
            )
        self.driver.connect(monotonic=self.clock, sleeper=self.pause)
        state = self.read()["state"]
        validate_state(state, self.config, target=0.0)
        self.initial_control = state["field_control_enabled"]
        self.driver.writes_authorized = writes
        return {
            "connected": True,
            "initial_state": state,
            "initial_observation": self.last_observation,
            "writes_authorized": writes,
            "ramp_rate": "unknown_preserved_by_native_controller",
            "source_hashes": SOURCE_SHA,
            "dll_sha256": DLL_SHA,
        }

    def read(self):
        self.guard()
        self.sample(self.driver.read_state())
        return {
            **self.last_observation,
            "freshness": "SDK server-cached values; no device acquisition timestamp",
        }

    def move(self, z):
        if not self.writes or type(z) not in (float, int) or z not in TARGETS:
            raise ValueError("magnetic target lacks campaign authority")
        before = self.read()["state"]
        if self.control_started:
            validate_state(before, self.config, require_control=True)
        if abs(before["field_setpoint"]["bz_t"] - z) > 0.5000001:
            raise ValueError("field setpoint change exceeds0.5T campaign bound")
        self.driver.ensure_field_control(True, **self.kwargs(), on_command=self.events)
        self.control_started = True
        target = self.vector(0.0, float(z))
        self.driver.set_vector_field(
            target,
            max_step_t=0.5,
            transition_policy="direct",
            **self.kwargs(),
            on_command=self.events,
        )
        self.qualification_buffer = []
        try:
            confirmed = self.driver.wait_for_field(target, **self.kwargs())
            observations = self.qualification_window(self.qualification_buffer)
        finally:
            self.qualification_buffer = None
        state = asdict(confirmed)
        validate_state(state, self.config, target=z, require_control=True)
        return {
            "qualified": True,
            "target_z_t": z,
            "state": state,
            "state_id": observations[-1]["state_id"],
            "qualification_observations": observations,
        }

    @staticmethod
    def qualification_window(observations):
        values = list(observations)
        if not values:
            raise ValueError("missing field qualification observations")
        cutoff = values[-1]["qualification_elapsed_s"] - 10.0
        while len(values) > 1 and values[1]["qualification_elapsed_s"] < cutoff:
            values.pop(0)
        return values

    def observe_zero(self, control):
        states = []
        while True:
            observation = self.read()
            s = observation["state"]
            validate_state(s, self.config, target=0.0, require_control=control)
            states.append(observation)
            for axis in ("bx_t", "bz_t"):
                values = [x["state"]["field"][axis] for x in states]
                if max(values) - min(values) > 0.0005:
                    raise ValueError("zero-field observation is not stable")
            if (
                states[-1]["observed_monotonic_s"] - states[0]["observed_monotonic_s"] >= 10.0
                and len(states) >= 3
            ):
                return states
            self.pause(1.0)

    def zero(self):
        if not self.writes or self.initial_control is None:
            raise ValueError("zero return lacks owned write session")
        before = self.read()["state"]
        if self.control_started and before["field_control_enabled"] is not True:
            raise ValueError("field control changed unexpectedly; no blind control/zero write")
        if before["field_control_enabled"] is True:
            self.qualification_buffer = []
            try:
                confirmed = self.driver.request_zero_field(**self.kwargs(), on_command=self.events)
                controlled = self.qualification_window(self.qualification_buffer)
            finally:
                self.qualification_buffer = None
            validate_state(asdict(confirmed), self.config, target=0.0, require_control=True)
            self.driver.ensure_field_control(
                self.initial_control, **self.kwargs(), on_command=self.events
            )
        else:
            validate_state(before, self.config, target=0.0, require_control=self.initial_control)
            controlled = []
        states = self.observe_zero(self.initial_control)
        return {
            "zero_verified": True,
            "initial_control_restored": True,
            "state": states[-1]["state"],
            "post_restore_zero_observations": states,
            "controlled_zero_qualification": controlled,
        }

    def close(self):
        if self.closed:
            if self.close_error:
                raise RuntimeError(self.close_error)
            return {"closed": True}
        errors = []
        try:
            if self.driver is not None and self.driver.connected:
                self.driver.close()
        except BaseException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            for lease in reversed(self.leases):
                try:
                    lease.close()
                except BaseException as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
            self.closed = True
        self.events({"event": "magnetic_close", "errors": errors})
        if errors:
            self.close_error = "; ".join(errors)
            raise RuntimeError(self.close_error)
        return {"closed": True}
