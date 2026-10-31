"""LabOS-owned, fixed-command cryostat adapter. No legacy application is imported.

Commands are derived from the operator-supplied driver excerpts retained in the
private source evidence. Opening a session does not reset or enable any output.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from pydantic import Field, StrictBool, ValidationError, model_validator

from .files import atomic_write, json_bytes
from .models import Model

Positive = Annotated[float, Field(gt=0)]
SERIALS = {
    "cld": "M01058596",
    "pm": "P0024060",
    "xx": "52633",
    "xy": "54406",
    "aux": "005038",
    "gate": "4414633",
}
MODELS = {
    "cld": "CLD1010LP",
    "pm": "PM100D",
    "xx": "SR830",
    "xy": "SR830",
    "aux": "SR865A",
    "gate": "2400",
}


class ReadingFault(ValueError):
    def __init__(self, message, raw_sample):
        super().__init__(message)
        self.raw_sample = raw_sample


class CryostatConfig(Model):
    commissioned: StrictBool = False
    manual_route_confirmed: StrictBool = False
    aux_enabled: StrictBool = True
    station_config: Path
    resources: dict[str, str]
    temperature_c: float
    temperature_tolerance_c: Annotated[float, Field(gt=0, le=0.5)]
    max_laser_current_a: Positive
    current_readback_tolerance_a: Annotated[float, Field(gt=0, le=0.0001)] = 0.0001
    max_laser_voltage_v: Positive
    power_limit_w: Positive
    reference_hz: Positive
    chopper_port: str = Field(min_length=1, max_length=80)
    chopper_expected: dict[str, int]
    chopper_refout_hz: Positive
    chopper_input_hz: Positive
    chopper_phase_lock_manually_confirmed: StrictBool = False
    chopper_phase_lock_confirmation_note: str = Field(default="", max_length=1000)
    cld_acknowledged_connection_diagnostics: tuple[int, int, int] | None = None
    cld_acknowledgement_note: str = ""
    io_timeout_ms: int = Field(default=1000, ge=100, le=5000)
    power_read_timeout_ms: int = Field(default=7000, ge=100, le=10000)
    max_time_constant_s: Annotated[float, Field(gt=0, le=1)] = 1.0
    minimum_settle_time_constants: Annotated[float, Field(ge=5, le=30)] = 15.0
    pm_average_count: int = Field(default=15000, ge=1, le=1000000)

    @model_validator(mode="after")
    def explicit_bindings(self):
        required_roles = set(SERIALS)
        if not self.aux_enabled:
            required_roles.remove("aux")
        if set(self.resources) != required_roles or len(set(self.resources.values())) != len(
            required_roles
        ):
            raise ValueError(
                "Supply distinct explicit VISA bindings matching the locally enabled instrument set"
            )
        for role, address in self.resources.items():
            if "\n" in address or "\r" in address or not address.upper().endswith("::INSTR"):
                raise ValueError("Only explicit VISA INSTR resource addresses are supported")
            if role in {"cld", "pm"} and (
                not address.upper().startswith("USB") or SERIALS[role] not in address
            ):
                raise ValueError("USB resource must match the commissioned controller serial")
            if role not in {"cld", "pm"} and not address.upper().startswith("GPIB"):
                raise ValueError(
                    "The commissioned electrical instruments require explicit GPIB bindings"
                )
        required = {"blade", "ref", "nharmonic", "dharmonic", "output"}
        if set(self.chopper_expected) != required:
            raise ValueError("Supply the five current commissioned chopper settings")
        if (
            self.cld_acknowledged_connection_diagnostics is not None
            and not self.cld_acknowledgement_note.strip()
        ):
            raise ValueError(
                "A copied CLD diagnostic acknowledgment requires its original explanation"
            )
        return self

    @property
    def readout_roles(self):
        return ("xx", "xy", "aux") if self.aux_enabled else ("xx", "xy")


def validate_adapter_config(settings):
    config = CryostatConfig.model_validate(settings)
    if not config.commissioned or not config.manual_route_confirmed:
        raise ValueError("Cryostat bindings and optical route are not commissioned locally")
    return config


class StationLease:
    """Use the exact legacy station lock path, without importing that application."""

    def __init__(self, station):
        self.path = Path(station).resolve().with_suffix(".hardware-owner.lock")
        self.handle = None

    def open(self):
        self.handle = self.path.open("a+b")
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.close()
            raise ValueError("Another process owns the commissioned station") from None

    def close(self):
        if self.handle is not None:
            self.handle.close()
            self.handle = None


class ChopperReadback:
    """Fixed readback commands only; no motor/settings writes or automatic takeover."""

    def __init__(self, port, timeout_s):
        import serial

        self.serial = serial.Serial(
            port=port,
            baudrate=115200,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=timeout_s,
            write_timeout=timeout_s,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        self.timeout = timeout_s
        self.guard = lambda: math.inf
        try:
            pending = self.serial.read(self.serial.in_waiting)
            if pending.strip() not in {b"", b">"}:
                raise ValueError("Unidentified chopper startup bytes")
        except BaseException:
            self.serial.close()
            raise

    def query(self, key):
        remaining = self.guard()
        command = key + "?"
        pending = self.serial.read(self.serial.in_waiting)
        if pending.strip():
            raise ValueError("Unsolicited chopper data; no query sent")
        deadline = time.monotonic() + min(self.timeout, remaining)
        payload = (command + "\r").encode("ascii")
        if self.serial.write(payload) != len(payload):
            raise ValueError("Partial chopper query")
        data = bytearray()
        while time.monotonic() < deadline and len(data) < 4096:
            self.guard()
            self.serial.timeout = max(0.001, deadline - time.monotonic())
            part = self.serial.read(1)
            if not part:
                raise TimeoutError("Chopper readback incomplete")
            data.extend(part)
            if part == b">":
                break
        if not data.endswith(b">"):
            raise TimeoutError("Chopper prompt missing")
        lines = [
            s.strip()
            for s in data[:-1].decode("ascii").replace("\r", "\n").split("\n")
            if s.strip()
        ]
        if lines and lines[0] == command:
            lines.pop(0)
        if len(lines) != 1:
            raise ValueError("Ambiguous chopper response")
        return lines[0]

    def set_guard(self, guard):
        self.guard = guard

    def snapshot(self):
        identity = self.query("id")
        if "MC2000B" not in identity:
            raise ValueError("Chopper model mismatch")
        if int(self.query("verbose")) != 0:
            raise ValueError("Chopper verbose mode must already be zero")
        values = {
            key: int(self.query(key))
            for key in ("blade", "ref", "nharmonic", "dharmonic", "output", "enable")
        }
        values.update(
            identity=identity,
            input_hz=float(self.query("input")),
            refout_frequency_hz=float(self.query("refoutfreq")),
            phase_lock_verified_by_query=False,
        )
        return values

    def close(self):
        self.serial.close()


class CryostatAdapter:
    def __init__(self, settings, manager_factory=None, chopper_factory=None):
        self.config = CryostatConfig.model_validate(settings)
        self.manager_factory = manager_factory
        self.chopper_factory = chopper_factory or ChopperReadback
        self.resources = {}
        self.manager = None
        self.chopper = None
        self.lease = None
        self.owned = False
        self.phase = None
        self.identities = {}
        self.time_constants = {}
        self.configured_harmonics = {}
        self.deadline = None
        self.cancel = None
        self.protecting = False
        self.active_sample = None
        self.last_io = None
        self.effective_power_limit_w = self.config.power_limit_w

    def set_guard(self, deadline, cancel):
        self.deadline, self.cancel = deadline, cancel
        if self.chopper is not None and hasattr(self.chopper, "set_guard"):
            self.chopper.set_guard(self.guard)

    def guard(self):
        if self.protecting:
            return math.inf
        if self.cancel is not None:
            cancelled = self.cancel() if callable(self.cancel) else self.cancel.is_set()
            if cancelled:
                from .pilot import PilotCancelled

                raise PilotCancelled(
                    "Physical pilot cancellation requested between device transactions"
                )
        remaining = math.inf if self.deadline is None else self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Physical pilot shared device-I/O deadline exceeded")
        return remaining

    @contextmanager
    def protection_guard(self):
        old = self.protecting
        self.protecting = True
        try:
            yield
        finally:
            self.protecting = old

    def transaction(self, role, command, query):
        remaining = self.guard()
        resource = self.resources[role]
        original = resource.timeout
        resource.timeout = (
            min(original, max(1, math.ceil(1000 * remaining)))
            if math.isfinite(remaining)
            else original
        )
        self.last_io = {"role": role, "command": command, "state": "requested"}
        try:
            value = resource.query(command) if query else resource.write(command)
            self.last_io = {
                "role": role,
                "command": command,
                "response": value if query else "write returned",
            }
            self.guard()
            return value
        finally:
            resource.timeout = original

    def w(self, role, command):
        return self.transaction(role, command, False)

    def open(self):
        c = validate_adapter_config(self.config.model_dump())
        if not c.station_config.is_file():
            raise ValueError("Existing station config path is unavailable")
        self.lease = StationLease(c.station_config)
        self.lease.open()
        try:
            factory = self.manager_factory
            if factory is None:
                import pyvisa

                factory = pyvisa.ResourceManager
            self.manager = factory()
            for role, address in c.resources.items():
                resource = self.manager.open_resource(
                    address, access_mode=1, open_timeout=c.io_timeout_ms
                )
                self.resources[role] = resource
                resource.timeout = c.io_timeout_ms
                resource.read_termination = resource.write_termination = "\n"
            self.chopper = self.chopper_factory(c.chopper_port, c.io_timeout_ms / 1000)
            if hasattr(self.chopper, "set_guard"):
                self.chopper.set_guard(self.guard)
        except BaseException:
            self.close()
            raise

    def q(self, role, command):
        value = self.transaction(role, command, True)
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError("Invalid instrument response")
        return value.strip()

    def number(self, role, command):
        value = float(self.q(role, command))
        if not math.isfinite(value) or abs(value) >= 9e37:
            raise ValueError("Invalid/overflow instrument number")
        return value

    def integer(self, role, command):
        text = self.q(role, command)
        return int(text)

    def flag(self, role, command):
        value = self.q(role, command).upper()
        if value not in {"0", "+0", "OFF", "1", "+1", "ON"}:
            raise ValueError("Invalid instrument boolean")
        return value in {"1", "+1", "ON"}

    def cld_state(self, *, startup=False):
        c = self.config
        booleans = {
            name: self.flag("cld", command)
            for name, command in {
                "laser_enabled": "OUTP1:STAT?",
                "tec_enabled": "OUTP2:STAT?",
                "auto_on": "OUTP1:PON:STAT?",
                "interlock": "OUTP1:PROT:INTL:TRIP?",
                "temperature_trip": "OUTP1:PROT:TEMP:TRIP?",
                "tec_transducer": "OUTP2:PROT:TRAN:TRIP?",
                "tec_overtemp": "OUTP2:PROT:OTEM:TRIP?",
                "tec_voltage": "OUTP2:PROT:COMP:TRIP?",
            }.items()
        }
        if any(
            booleans[k]
            for k in (
                "auto_on",
                "interlock",
                "temperature_trip",
                "tec_transducer",
                "tec_overtemp",
                "tec_voltage",
            )
        ):
            raise ValueError("CLD interlock/protection prevents operation; no reset is issued")
        if not booleans["tec_enabled"]:
            raise ValueError("Existing TEC must already be enabled and stable")
        enums = {
            "SOUR1:FUNC:MODE?": {"CURR", "CURRENT"},
            "SOUR2:FUNC:MODE?": {"TEMP", "TEMPERATURE"},
            "UNIT:TEMP?": {"C", "CEL", "CELSIUS"},
            "OUTP1:PROT:TEMP:MODE?": {"ENAB", "ENABLE", "PROT", "PROTECTION"},
        }
        for command, allowed in enums.items():
            if self.q("cld", command).upper() not in allowed:
                raise ValueError("Uncommissioned CLD operating/protection mode")
        target = self.number("cld", "SOUR2:TEMP:SPO?")
        temperature = self.number("cld", "SENS2:TEMP:DATA?")
        if (
            abs(target - c.temperature_c) > 0.001
            or abs(temperature - target) > c.temperature_tolerance_c
        ):
            raise ValueError("CLD diode temperature is not at the preserved commissioned setpoint")
        current = self.number("cld", "SENS3:CURR:DC:DATA?")
        voltage = self.number("cld", "SENS4:VOLT:DC:DATA?")
        if (
            current < 0
            or current > c.max_laser_current_a + c.current_readback_tolerance_a
            or not (-0.0004 if startup else 0) <= voltage <= c.max_laser_voltage_v
        ):
            raise ValueError("CLD electrical readback exceeds local guard")
        diagnostics = tuple(
            self.integer("cld", cmd)
            for cmd in ("OUTP1:PROT:CONN:TRIP?", "OUTP2:PROT:CONN:TRIP?", "STAT:MEAS:COND?")
        )
        if (
            diagnostics[0] not in (0, 1)
            or diagnostics[1] not in (0, 1)
            or not 0 <= diagnostics[2] <= 65535
        ):
            raise ValueError("Invalid CLD connection diagnostic")
        if (
            diagnostics[0] or diagnostics[1] or diagnostics[2] & 8192
        ) and diagnostics != c.cld_acknowledged_connection_diagnostics:
            raise ValueError("Unresolved CLD connection indication; no automatic acknowledgment")
        return {
            **booleans,
            "temperature_c": temperature,
            "temperature_setpoint_c": target,
            "laser_current_a": current,
            "laser_voltage_v": voltage,
            "diagnostics": list(diagnostics),
        }

    def pm_state(self):
        sensor = next(csv.reader([self.q("pm", "SYST:SENS:IDN?")]))
        if (
            len(sensor) != 6
            or sensor[0] != "S120C"
            or sensor[1] != "240429505"
            or not int(sensor[5]) & 1
            or not int(sensor[5]) & 32
        ):
            raise ValueError("Power sensor identity/capability mismatch")
        if (
            self.q("pm", "CONF?").strip('"').upper() not in {"POW", "POWER", "POW:DC", "POWER:DC"}
            or self.q("pm", "SENS:POW:UNIT?").upper() != "W"
        ):
            raise ValueError("Power meter must already use absolute power in W")
        if (
            self.flag("pm", "SENS:POW:REF:STAT?")
            or self.number("pm", "SENS:CORR:LOSS:INP:MAGN?") != 0
        ):
            raise ValueError("Relative/user loss correction is not commissioned")
        if self.number("pm", "SENS:CORR:WAV?") != 730 or self.integer("pm", "STAT:QUES:COND?") != 0:
            raise ValueError("Power wavelength correction/questionable condition mismatch")
        scale = self.number("pm", "SENS:POW:RANG?")
        if scale <= 0 or self.integer("pm", "SENS:AVER:COUN?") != self.config.pm_average_count:
            raise ValueError("Power range/averaging is not commissioned")
        return {
            "sensor_model": sensor[0],
            "sensor_serial": sensor[1],
            "range_w": scale,
            "wavelength_nm": 730,
        }

    def chopper_state(self):
        self.guard()
        if not self.config.chopper_phase_lock_manually_confirmed:
            raise ValueError("Current manual chopper phase-lock confirmation is required")
        state = self.chopper.snapshot()
        self.guard()
        c = self.config
        if state.get("enable") != 1 or any(
            state.get(k) != v for k, v in c.chopper_expected.items()
        ):
            raise ValueError(
                "Chopper must already run with the commissioned blade/reference settings"
            )
        for field, expected in [
            ("input_hz", c.chopper_input_hz),
            ("refout_frequency_hz", c.chopper_refout_hz),
        ]:
            value = state.get(field)
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or abs(value - expected) > 0.1
            ):
                raise ValueError("Chopper frequency is not at the commissioned reference")
        return {
            **state,
            "phase_lock_manually_confirmed": c.chopper_phase_lock_manually_confirmed,
            "manual_confirmation_note": c.chopper_phase_lock_confirmation_note,
        }

    def lockin_settings(self, role):
        c = self.config
        code = self.integer(role, "OFLT?")
        base = 1e-6 if role == "aux" else 1e-5
        if not 0 <= code <= (21 if role == "aux" else 19):
            raise ValueError("Invalid lock-in time constant code")
        tau = (1 if code % 2 == 0 else 3) * base * 10 ** (code // 2)
        if tau > c.max_time_constant_s + 1e-12:
            raise ValueError("Existing lock-in time constant exceeds pilot budget")
        if role == "aux":
            if self.integer(role, "RSRC?") != 1 or self.integer(role, "IVMD?") != 0:
                raise ValueError("AUX requires existing external reference and voltage input")
            frequency = self.number(role, "FREQEXT?")
        else:
            if self.integer(role, "FMOD?") != (1 if role == "xx" else 0):
                raise ValueError("Transport reference topology differs from commissioned profile")
            if role == "xy" and self.integer(role, "RSLP?") != 1:
                raise ValueError("XY requires existing rising-edge TTL reference")
            if self.integer(role, "ISRC?") not in (0, 1):
                raise ValueError("SR830 requires voltage input")
            frequency = self.number(role, "FREQ?")
        if abs(frequency - c.reference_hz) > 0.1:
            raise ValueError("Lock-in fundamental frequency differs from pilot profile")
        return {"time_constant_s": tau, "reference_hz": frequency}

    def preflight(self):
        for role in self.resources:
            identity = self.q(role, "*IDN?")
            fields = [x.strip() for x in identity.split(",")]
            if (
                len(fields) != 4
                or MODELS[role] not in fields[1]
                or fields[2].removeprefix("s/n") != SERIALS[role]
            ):
                raise ValueError("Instrument identity/serial mismatch: " + role)
            manufacturer = fields[0].upper()
            expected = (
                "THORLABS"
                if role in {"cld", "pm"}
                else "KEITHLEY"
                if role == "gate"
                else "STANFORD_RESEARCH_SYSTEMS"
            )
            if not manufacturer.startswith(expected):
                raise ValueError("Instrument manufacturer mismatch: " + role)
            self.identities[role] = identity
        cld = self.cld_state()
        if cld["laser_enabled"]:
            raise ValueError("Laser is already enabled; no takeover")
        if self.flag("gate", "OUTP?"):
            raise ValueError("Gate output is active; pilot must not alter it")
        pm = self.pm_state()
        chopper = self.chopper_state()
        for role in self.config.readout_roles:
            self.time_constants[role] = self.lockin_settings(role)
        self.owned = True
        return {
            "ready": True,
            "readout_roles": list(self.config.readout_roles),
            "excluded_readout_roles": [] if self.config.aux_enabled else ["aux"],
            "laser_enabled": False,
            "identities": self.identities,
            "cld": cld,
            "pm": pm,
            "chopper": chopper,
            "gate_output_enabled": False,
            "gate_voltage_zero_verified": False,
            "lockin_settings": self.time_constants,
            "contact_mapping": "unverified raw "
            + "/".join(role.upper() for role in self.config.readout_roles),
            "measurement_plane": "PM pickoff before sample",
            "sample_current_calibrated": False,
            "simulated": False,
            "sine_v_rms": self.number("xx", "SLVL?"),
        }

    def require_owned(self):
        if not self.owned:
            raise ValueError("This adapter does not own a preflighted station")

    def protect_excitation(self):
        self.require_owned()
        with self.protection_guard():
            self.w("xx", "SLVL 0.004")
            actual = self.number("xx", "SLVL?")
        return {
            "minimum_excitation_verified": math.isclose(actual, 0.004, abs_tol=1e-12, rel_tol=0),
            "actual_v_rms": actual,
        }

    def laser_off(self):
        self.require_owned()
        errors = []
        off = False
        zero = False
        try:
            with self.protection_guard():
                self.w("cld", "OUTP1:STAT 0")
                off = not self.flag("cld", "OUTP1:STAT?")
        except BaseException as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
        try:
            with self.protection_guard():
                self.w("cld", "SOUR1:CURR:LEV:IMM:AMPL 0")
                zero = self.number("cld", "SOUR1:CURR:LEV:IMM:AMPL?") == 0
        except BaseException as exc:
            errors.append(type(exc).__name__ + ": " + str(exc))
        return {
            "laser_off_verified": off and zero,
            "emission_off_readback": off,
            "zero_current_setpoint_verified": zero,
            "errors": errors,
        }

    def configure(self, phase, plan):
        self.require_owned()
        if (
            plan.reference_hz != self.config.reference_hz
            or plan.settle_s
            < self.config.minimum_settle_time_constants
            * max(v["time_constant_s"] for v in self.time_constants.values())
        ):
            raise ValueError("Pilot reference/settling is outside commissioned bounds")
        if (
            plan.laser_current_a is not None
            and plan.laser_current_a > self.config.max_laser_current_a
        ):
            raise ValueError("Laser current exceeds adapter limit")
        if plan.power_limit_w is not None and plan.power_limit_w > self.config.power_limit_w:
            raise ValueError("Power guard exceeds adapter limit")
        self.effective_power_limit_w = min(
            self.config.power_limit_w, plan.power_limit_w or self.config.power_limit_w
        )
        if (
            not self.laser_off()["laser_off_verified"]
            or not self.protect_excitation()["minimum_excitation_verified"]
        ):
            raise ValueError("Cannot configure an unprotected phase")
        for role in self.config.readout_roles:
            harmonic = 2 if role == "xy" and phase == "dark_hall_2f" else 1
            self.w(role, "HARM " + str(harmonic))
            if self.integer(role, "HARM?") != harmonic:
                raise ValueError("Harmonic readback mismatch")
            self.configured_harmonics[role] = harmonic
        self.phase = phase

    def laser_on(self, current_a):
        self.require_owned()
        c = self.config
        if self.phase != "illuminated" or not 0 < current_a <= c.max_laser_current_a:
            raise ValueError("Laser enable outside finite optical phase")
        before = self.cld_state()
        if before["laser_enabled"]:
            raise ValueError("Laser unexpectedly enabled before emission")
        self.cld_no_error()
        for command, value in [
            ("SOUR1:CURR:LIM:AMPL", c.max_laser_current_a),
            ("SOUR1:CURR:LEV:IMM:AMPL", current_a),
        ]:
            self.w("cld", command + " " + format(value, ".12g"))
            self.cld_no_error()
            if not math.isclose(
                self.number("cld", command + "?"), value, abs_tol=1e-7, rel_tol=1e-6
            ):
                raise ValueError("CLD current setting readback mismatch")
        self.w("cld", "OUTP1:STAT 1")
        self.cld_no_error()
        if not self.cld_state(startup=True)["laser_enabled"]:
            raise ValueError("Laser enable readback mismatch")

    def cld_no_error(self):
        reply = self.q("cld", "SYST:ERR?")
        if int(reply.split(",", 1)[0]) != 0:
            raise ValueError("CLD error queue is not clear: " + reply)

    def read_sample(self, phase):
        self.active_sample = {"channels": {}, "simulated": False}
        try:
            return self._read_sample(phase)
        except BaseException as exc:
            if not hasattr(exc, "raw_sample"):
                exc.raw_sample = {**self.active_sample, "last_io": self.last_io}
            raise
        finally:
            self.active_sample = None

    def _read_sample(self, phase):
        self.require_owned()
        cld = self.cld_state()
        if cld["laser_enabled"] != (phase == "illuminated"):
            raise ValueError("Laser phase state mismatch")
        if self.number("xx", "SLVL?") != 0.004:
            raise ValueError("Excitation changed from commissioned minimum")
        if self.flag("gate", "OUTP?"):
            raise ValueError("Gate output state changed")
        pm_before = self.pm_state()
        resource = self.resources["pm"]
        old_timeout = resource.timeout
        try:
            resource.timeout = self.config.power_read_timeout_ms
            power = self.number("pm", "READ?")
        finally:
            resource.timeout = old_timeout
        power_evidence = {
            "power_w": power,
            "measurement_plane": "PM pickoff before sample",
            "channels": {"pm": {"raw_power_w": power}},
            "simulated": False,
        }
        self.active_sample.update(power_w=power, measurement_plane="PM pickoff before sample")
        if phase == "illuminated" and power > self.effective_power_limit_w:
            raise ReadingFault(
                "Optical power guard exceeded; stop before further acquisition", power_evidence
            )
        pm_after = self.pm_state()
        if power < 0 or power >= min(pm_before["range_w"], pm_after["range_w"]):
            raise ReadingFault("Power acquisition is invalid/saturated", power_evidence)
        channels = self.active_sample["channels"]
        for role in self.config.readout_roles:
            settings = self.lockin_settings(role)
            harmonic = self.integer(role, "HARM?")
            if harmonic != self.configured_harmonics[role]:
                raise ValueError("Harmonic changed during acquisition")
            raw = self.q(role, "SNAP? X,Y" if role == "aux" else "SNAP? 1,2,3,4,9").split(",")
            values = [float(v) for v in raw]
            if len(values) != (2 if role == "aux" else 5) or not all(
                math.isfinite(v) for v in values
            ):
                raise ValueError("Invalid lock-in sample")
            lias = self.integer(role, "LIAS?")
            errors = self.integer(role, "ERRS?")
            # Conservative pilot: retain raw latches; no undocumented masks or automatic clears.
            x, y = values[:2]
            channels[role] = {
                "x_v": x,
                "y_v": y,
                "r_v": math.hypot(x, y),
                "phase_deg": math.degrees(math.atan2(y, x)),
                "harmonic": harmonic,
                **settings,
                "lia_status_raw": lias,
                "error_status_raw": errors,
                "current_overload_status_verified": False,
            }
            detection = self.number(role, "FREQDET?") if role == "aux" else values[4] * harmonic
            channels[role]["detection_frequency_hz"] = detection
            if abs(detection / harmonic - settings["reference_hz"]) > 0.1:
                raise ReadingFault(
                    "Detection/snapshot reference frequency mismatch: " + role,
                    {**power_evidence, "channels": channels},
                )
            if lias != 0 or errors != 0:
                raise ReadingFault(
                    "Lock-in status window is not clean: " + role,
                    {**power_evidence, "channels": channels},
                )
        chopper = self.chopper_state()
        after = self.cld_state()
        if after["laser_enabled"] != (phase == "illuminated"):
            raise ValueError("Laser changed while acquiring")
        return {
            "channels": channels,
            "excluded_readout_roles": [] if self.config.aux_enabled else ["aux"],
            "power_w": power,
            "measurement_plane": "PM pickoff before sample",
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "laser_enabled": after["laser_enabled"],
            "laser_current_a": after["laser_current_a"],
            "excitation_v_rms": 0.004,
            "excitation_definition": "voltage drive; no external series resistor; sample current uncalibrated",
            "chopper_phase_lock_verified_by_query": False,
            "chopper_refout_hz": chopper["refout_frequency_hz"],
            "nominal_wavelength_nm": 730,
            "wavelength_basis": "operator-declared diode wavelength",
            "simulated": False,
        }

    def close(self):
        errors = []
        for item in [self.chopper, *reversed(list(self.resources.values())), self.manager]:
            if item is not None:
                try:
                    item.close()
                except BaseException as exc:
                    errors.append(type(exc).__name__)
        self.resources = {}
        self.chopper = self.manager = None
        self.owned = False
        if self.lease is not None:
            self.lease.close()
            self.lease = None
        if errors:
            raise RuntimeError(
                "Instrument closure requires local reconciliation: " + ",".join(errors)
            )


def create_adapter(settings):
    return CryostatAdapter(validate_adapter_config(settings).model_dump())


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Output-preserving cryostat pilot preflight; does not run a measurement"
    )
    parser.add_argument("action", choices=["preflight"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    adapter = None
    result = {
        "document_type": "labos_physical_preflight",
        "status": "FAILED",
        "executable": False,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "device_observation": None,
        "output_enable_performed": False,
        "source": "LabOS-owned SCPI adapter",
        "error": None,
        "close_error": None,
    }
    try:
        from .pilot_worker import load_pilot_worker_config

        config = load_pilot_worker_config(args.config)
        adapter = create_adapter(config.adapter_config)
        adapter.open()
        adapter.set_guard(time.monotonic() + 60, None)
        result["device_observation"] = adapter.preflight()
        result["status"] = "PASSED"
    except Exception as exc:
        # Validation errors may echo arbitrary configuration input; keep those private.
        detail = (
            "Invalid commissioning configuration"
            if isinstance(exc, ValidationError)
            else str(exc)[:1000]
        )
        result["error"] = type(exc).__name__ + ": " + detail
    finally:
        if adapter is not None:
            result["last_device_io"] = adapter.last_io
            result["identities"] = adapter.identities
            try:
                adapter.close()
            except Exception as exc:
                result["close_error"] = type(exc).__name__ + ": " + str(exc)[:1000]
                result["status"] = "FAILED"
    atomic_write(args.output, json_bytes(result))
    print(
        f"Output-preserving preflight {result['status']}; evidence saved. No output enable command was sent."
    )
    return 0 if result["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
