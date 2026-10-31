"""Exercise the LabOS SCPI adapter against stateful vendor-I/O replay resources."""

import pytest

from labos.pilot import PilotPlan


def settings(tmp_path):
    station = tmp_path / "station.toml"
    station.write_text("# external station lease identity only\n")
    return dict(
        commissioned=True,
        manual_route_confirmed=True,
        station_config=str(station),
        resources={
            "cld": "USB0::1::M01058596::INSTR",
            "pm": "USB0::2::P0024060::INSTR",
            "xx": "GPIB1::8::INSTR",
            "xy": "GPIB1::9::INSTR",
            "aux": "GPIB1::10::INSTR",
            "gate": "GPIB1::22::INSTR",
        },
        temperature_c=26,
        temperature_tolerance_c=0.05,
        max_laser_current_a=0.0218,
        max_laser_voltage_v=2.1,
        power_limit_w=1e-6,
        chopper_port="COM10",
        chopper_expected={"blade": 1, "ref": 1, "nharmonic": 1, "dharmonic": 1, "output": 1},
        chopper_refout_hz=8,
        chopper_input_hz=8,
        chopper_phase_lock_manually_confirmed=True,
        reference_hz=8,
    )


class Resource:
    def __init__(self, role):
        self.role = role
        self.writes = []
        self.queries = []
        self.closed = False
        identities = {
            "cld": "Thorlabs,CLD1010LP,M01058596,2.3.0",
            "pm": "Thorlabs,PM100D,P0024060,2.6.0",
            "xx": "Stanford_Research_Systems,SR830,s/n52633,ver1.07",
            "xy": "Stanford_Research_Systems,SR830,s/n54406,ver1.07",
            "aux": "Stanford_Research_Systems,SR865A,005038,V1.51",
            "gate": "KEITHLEY INSTRUMENTS INC.,MODEL 2400,4414633,C",
        }
        self.values = {
            "*IDN?": identities[role],
            "SYST:ERR?": "0,No error",
            "OUTP?": "0",
            "OUTP1:STAT?": "0",
            "OUTP2:STAT?": "1",
            "OUTP1:PON:STAT?": "0",
            "SOUR1:FUNC:MODE?": "CURR",
            "SOUR2:FUNC:MODE?": "TEMP",
            "UNIT:TEMP?": "C",
            "OUTP1:PROT:TEMP:MODE?": "ENAB",
            "SOUR1:CURR:LEV:IMM:AMPL?": "0",
            "SOUR1:CURR:LIM:AMPL?": "0.03",
            "SOUR2:TEMP:SPO?": "26",
            "SENS2:TEMP:DATA?": "26",
            "SENS3:CURR:DC:DATA?": "0",
            "SENS4:VOLT:DC:DATA?": "1.96",
            "SENS2:TEMP:PROT:WIND:AMPL?": "2",
            "OUTP1:PROT:INTL:TRIP?": "0",
            "OUTP1:PROT:TEMP:TRIP?": "0",
            "OUTP2:PROT:TRAN:TRIP?": "0",
            "OUTP2:PROT:OTEM:TRIP?": "0",
            "OUTP2:PROT:COMP:TRIP?": "0",
            "OUTP1:PROT:CONN:TRIP?": "0",
            "OUTP2:PROT:CONN:TRIP?": "0",
            "STAT:MEAS:COND?": "0",
            "SYST:SENS:IDN?": "S120C,240429505,29-APR-2024,1,18,289",
            "CONF?": "POW",
            "SENS:POW:UNIT?": "W",
            "SENS:CORR:WAV?": "730",
            "SENS:POW:REF:STAT?": "0",
            "SENS:CORR:LOSS:INP:MAGN?": "0",
            "STAT:QUES:COND?": "0",
            "SENS:POW:RANG?": "0.001",
            "SENS:AVER:COUN?": "15000",
            "READ?": "4.8e-7",
            "SLVL?": "0.004",
            "FMOD?": "1" if role == "xx" else "0",
            "RSLP?": "1",
            "RSRC?": "1",
            "FREQ?": "8",
            "FREQEXT?": "8",
            "FREQDET?": "8",
            "HARM?": "1",
            "OFLT?": "12" if role == "aux" else "10",
            "LIAS?": "0",
            "ERRS?": "0",
            "*ESR?": "0",
            "ISRC?": "0",
            "IVMD?": "0",
            "SNAP? 1,2,3,4,9": "1e-8,2e-9,1.0198039027e-8,11.3099,8",
            "SNAP? X,Y": "1e-8,2e-9",
        }

    def query(self, command):
        self.queries.append(command)
        return self.values[command]

    def write(self, command):
        self.writes.append(command)
        key, value = command.rsplit(" ", 1)
        self.values[key + "?"] = value
        if key == "OUTP1:STAT":
            self.values["SENS3:CURR:DC:DATA?"] = (
                self.values["SOUR1:CURR:LEV:IMM:AMPL?"] if value == "1" else "0"
            )
        if key == "HARM" and self.role == "aux":
            self.values["FREQDET?"] = str(8 * int(value))

    def close(self):
        self.closed = True


class Manager:
    def __init__(self, cfg):
        self.devices = {address: Resource(role) for role, address in cfg["resources"].items()}
        self.closed = False

    def open_resource(self, address, **kwargs):
        assert kwargs["access_mode"] == 1
        return self.devices[address]

    def close(self):
        self.closed = True


class Chopper:
    def __init__(self, *args, **kwargs):
        self.closed = False

    def snapshot(self):
        return {
            "identity": "Thorlabs MC2000B",
            "enable": 1,
            "blade": 1,
            "ref": 1,
            "nharmonic": 1,
            "dharmonic": 1,
            "output": 1,
            "input_hz": 8.0,
            "refout_frequency_hz": 8.0,
            "phase_lock_verified_by_query": False,
        }

    def close(self):
        self.closed = True


def adapter(tmp_path):
    from labos.cryostat_pilot import CryostatAdapter

    config = settings(tmp_path)
    manager = Manager(config)
    return CryostatAdapter(
        config, manager_factory=lambda: manager, chopper_factory=Chopper
    ), manager


def test_preflight_preserves_outputs_and_identity_checks_precede_writes(tmp_path):
    station, manager = adapter(tmp_path)
    station.open()
    observed = station.preflight()
    assert observed["ready"] is True and observed["laser_enabled"] is False
    assert all(not resource.writes for resource in manager.devices.values())
    station.close()
    assert manager.closed and all(r.closed for r in manager.devices.values())


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_serial",
        "laser_already_on",
        "gate_on",
        "interlock",
        "temperature",
        "diagnostics",
        "power_unit",
        "sensor",
    ],
)
def test_preflight_refuses_without_taking_over_outputs(tmp_path, fault):
    station, manager = adapter(tmp_path)
    station.open()
    cld = station.resources["cld"]
    pm = station.resources["pm"]
    if fault == "wrong_serial":
        cld.values["*IDN?"] = "Thorlabs,CLD1010LP,OTHER,1"
    elif fault == "laser_already_on":
        cld.values["OUTP1:STAT?"] = "1"
    elif fault == "gate_on":
        station.resources["gate"].values["OUTP?"] = "1"
    elif fault == "interlock":
        cld.values["OUTP1:PROT:INTL:TRIP?"] = "1"
    elif fault == "temperature":
        cld.values["SENS2:TEMP:DATA?"] = "30"
    elif fault == "diagnostics":
        cld.values["STAT:MEAS:COND?"] = "8192"
    elif fault == "power_unit":
        pm.values["SENS:POW:UNIT?"] = "DBM"
    elif fault == "sensor":
        pm.values["SYST:SENS:IDN?"] = "S120C,OTHER,date,1,18,289"
    with pytest.raises(ValueError):
        station.preflight()
    assert all(not r.writes for r in manager.devices.values())
    station.close()


def test_photoresponse_and_dark_h2_use_labos_commands_and_real_units(tmp_path):
    station, manager = adapter(tmp_path)
    station.open()
    station.preflight()
    plan = PilotPlan(
        sample_id="CrSBr 1",
        mode="combined",
        reference_hz=8,
        laser_current_a=0.0218,
        power_limit_w=1e-6,
        settle_s=15,
    )
    station.configure("illuminated", plan)
    station.laser_on(0.0218)
    sample = station.read_sample("illuminated")
    assert sample["power_w"] == 4.8e-7 and sample["measurement_plane"] == "PM pickoff before sample"
    assert sample["channels"]["aux"]["x_v"] == 1e-8
    assert "sample_current_a" not in sample
    assert station.laser_off()["laser_off_verified"] is True
    assert station.protect_excitation() == {
        "minimum_excitation_verified": True,
        "actual_v_rms": 0.004,
    }
    station.configure("dark_hall_2f", plan)
    assert station.read_sample("dark_hall_2f")["channels"]["xy"]["harmonic"] == 2
    assert station.resources["xx"].values["SLVL?"] == "0.004"
    assert all(
        not any(c.startswith(("SOUR2", "OUTP2", "*RST", "*CLS")) for c in r.writes)
        for r in manager.devices.values()
    )
    station.close()


def test_emergency_laser_cleanup_attempts_zero_current_when_off_write_fails(tmp_path):
    station, _ = adapter(tmp_path)
    station.open()
    station.preflight()
    cld = station.resources["cld"]
    original = cld.write

    def write(command):
        if command == "OUTP1:STAT 0":
            raise OSError("disconnected")
        original(command)

    cld.write = write
    result = station.laser_off()
    assert result["laser_off_verified"] is False
    assert "SOUR1:CURR:LEV:IMM:AMPL 0" in cld.writes
    station.close()


def test_uncommissioned_profile_never_imports_or_opens_visa(tmp_path):
    from labos.cryostat_pilot import CryostatAdapter

    config = settings(tmp_path)
    config["commissioned"] = False
    with pytest.raises(ValueError):
        CryostatAdapter(config, manager_factory=lambda: pytest.fail("opened")).open()


def test_overpower_stops_before_later_lockin_io_and_retains_raw_power(tmp_path):
    station, _ = adapter(tmp_path)
    station.open()
    station.preflight()
    plan = PilotPlan(
        sample_id="CrSBr 1",
        mode="combined",
        reference_hz=8,
        laser_current_a=0.0218,
        power_limit_w=1e-6,
        settle_s=15,
    )
    station.configure("illuminated", plan)
    station.laser_on(0.0218)
    station.resources["pm"].values["READ?"] = "2e-6"
    for role in ("xx", "xy", "aux"):
        station.resources[role].queries.clear()
    with pytest.raises(ValueError) as error:
        station.read_sample("illuminated")
    assert error.value.raw_sample["power_w"] == 2e-6
    assert all(
        not any(q.startswith("SNAP?") for q in station.resources[r].queries)
        for r in ("xx", "xy", "aux")
    )
    station.laser_off()
    station.close()


def test_missing_current_chopper_lock_confirmation_refuses_before_output_writes(tmp_path):
    from labos.cryostat_pilot import CryostatAdapter

    config = settings(tmp_path)
    config["chopper_phase_lock_manually_confirmed"] = False
    manager = Manager(config)
    station = CryostatAdapter(config, manager_factory=lambda: manager, chopper_factory=Chopper)
    station.open()
    with pytest.raises(ValueError):
        station.preflight()
    assert all(not r.writes for r in manager.devices.values())
    station.close()


@pytest.mark.parametrize(
    "role,command,value",
    [("aux", "FREQDET?", "16"), ("xx", "SNAP? 1,2,3,4,9", "1e-8,2e-9,1e-8,0,80")],
)
def test_changed_detection_frequency_is_not_accepted_as_a_valid_sample(
    tmp_path, role, command, value
):
    station, _ = adapter(tmp_path)
    station.open()
    station.preflight()
    plan = PilotPlan(
        sample_id="CrSBr 1",
        mode="combined",
        reference_hz=8,
        laser_current_a=0.0218,
        power_limit_w=1e-6,
        settle_s=15,
    )
    station.configure("dark_baseline", plan)
    station.resources[role].values[command] = value
    with pytest.raises(ValueError):
        station.read_sample("dark_baseline")
    station.close()


def test_later_channel_failure_retains_earlier_power_and_lockin_values(tmp_path):
    station, _ = adapter(tmp_path)
    station.open()
    station.preflight()
    plan = PilotPlan(
        sample_id="CrSBr 1",
        mode="combined",
        reference_hz=8,
        laser_current_a=0.0218,
        power_limit_w=1e-6,
        settle_s=15,
    )
    station.configure("dark_baseline", plan)
    resource = station.resources["xy"]
    original = resource.query

    def query(command):
        if command.startswith("SNAP?"):
            raise OSError("read lost")
        return original(command)

    resource.query = query
    with pytest.raises(OSError) as error:
        station.read_sample("dark_baseline")
    assert error.value.raw_sample["power_w"] == 4.8e-7
    assert error.value.raw_sample["channels"]["xx"]["x_v"] == 1e-8
    station.close()


def test_plan_power_guard_precedes_post_read_settings_queries(tmp_path):
    station, _ = adapter(tmp_path)
    station.open()
    station.preflight()
    plan = PilotPlan(
        sample_id="CrSBr 1",
        mode="combined",
        reference_hz=8,
        laser_current_a=0.0218,
        power_limit_w=5e-7,
        settle_s=15,
    )
    station.configure("illuminated", plan)
    station.laser_on(0.0218)
    meter = station.resources["pm"]
    original = meter.query
    observed = []

    def query(command):
        observed.append(command)
        if command == "READ?":
            return "8e-7"
        return original(command)

    meter.query = query
    with pytest.raises(ValueError) as error:
        station.read_sample("illuminated")
    assert error.value.raw_sample["power_w"] == 8e-7
    assert observed[-1] == "READ?"
    station.laser_off()
    station.close()


def test_shared_io_deadline_stops_successful_slow_queries_and_allows_protection(
    tmp_path, monkeypatch
):
    station, _ = adapter(tmp_path)
    station.open()
    station.preflight()
    plan = PilotPlan(
        sample_id="CrSBr 1",
        mode="combined",
        reference_hz=8,
        laser_current_a=0.0218,
        power_limit_w=1e-6,
        settle_s=15,
    )
    station.configure("illuminated", plan)
    station.laser_on(0.0218)
    now = [0.0]
    monkeypatch.setattr("labos.cryostat_pilot.time.monotonic", lambda: now[0])
    for resource in station.resources.values():
        original = resource.query

        def delayed(command, original=original):
            now[0] += 0.4
            return original(command)

        resource.query = delayed
    station.set_guard(1.0, None)
    with pytest.raises(TimeoutError):
        station.read_sample("illuminated")
    assert now[0] <= 1.21
    assert station.laser_off()["laser_off_verified"] is True
    assert station.protect_excitation()["minimum_excitation_verified"] is True
    station.close()


def test_full_engine_uses_replayed_vendor_commands_for_all_three_phases(tmp_path, monkeypatch):
    from labos.pilot import PilotApproval, PilotEngine

    station, manager = adapter(tmp_path)
    now = [0.0]
    monkeypatch.setattr("labos.cryostat_pilot.time.monotonic", lambda: now[0])

    def sleep(seconds):
        now[0] += seconds

    plan = PilotPlan(
        sample_id="CrSBr 1",
        mode="combined",
        reference_hz=8,
        laser_current_a=0.0218,
        power_limit_w=1e-6,
        settle_s=15,
        samples_per_phase=3,
        phase_timeout_s=60,
        max_run_s=180,
    )
    approval = PilotApproval(
        enabled=True,
        sample_id="CrSBr 1",
        reference_hz=8,
        laser_current_max_a=0.0218,
        power_limit_max_w=1e-6,
        max_phase_s=60,
        max_run_s=180,
    )
    result = PilotEngine(station, clock=lambda: now[0], sleep=sleep).run(plan, approval)
    assert result["status"] == "COMPLETED", result["error"]
    assert len(result["samples"]) == 9
    assert all(s["channels"]["xy"]["harmonic"] == 2 for s in result["samples"][-3:])
    assert result["protection_verified"] is True
    cld = manager.devices[station.config.resources["cld"]]
    xx = manager.devices[station.config.resources["xx"]]
    assert cld.writes.count("OUTP1:STAT 1") == 1
    assert cld.values["OUTP1:STAT?"] == "0"
    assert cld.values["SOUR1:CURR:LEV:IMM:AMPL?"] == "0"
    assert xx.values["SLVL?"] == "0.004"
    assert manager.closed


@pytest.mark.parametrize("fault", ["identity", "close"])
def test_preflight_cli_retains_failure_evidence_even_when_close_fails(tmp_path, monkeypatch, fault):
    import json
    from types import SimpleNamespace
    from labos import cryostat_pilot

    station, manager = adapter(tmp_path)
    if fault == "identity":
        manager.devices[station.config.resources["cld"]].values["*IDN?"] = "wrong identity"
    else:

        def bad_close():
            raise OSError("closure unavailable")

        manager.close = bad_close
    monkeypatch.setattr(
        "labos.pilot_worker.load_pilot_worker_config", lambda _: SimpleNamespace(adapter_config={})
    )
    monkeypatch.setattr(cryostat_pilot, "create_adapter", lambda _: station)
    output = tmp_path / "evidence.json"
    assert (
        cryostat_pilot.main(
            ["preflight", "--config", str(tmp_path / "unused.yaml"), "--output", str(output)]
        )
        == 1
    )
    evidence = json.loads(output.read_text())
    assert evidence["status"] == "FAILED"
    assert evidence["output_enable_performed"] is False
    assert evidence["error"] or evidence["close_error"]
    assert all(not resource.writes for resource in manager.devices.values())


def test_explicit_two_channel_profile_completes_without_opening_or_using_aux(tmp_path, monkeypatch):
    from labos.cryostat_pilot import CryostatAdapter
    from labos.pilot import PilotApproval, PilotEngine

    config = settings(tmp_path)
    config["aux_enabled"] = False
    del config["resources"]["aux"]
    manager = Manager(config)
    station = CryostatAdapter(config, manager_factory=lambda: manager, chopper_factory=Chopper)
    now = [0.0]
    monkeypatch.setattr("labos.cryostat_pilot.time.monotonic", lambda: now[0])

    def sleep(seconds):
        now[0] += seconds

    plan = PilotPlan(
        sample_id="CrSBr 1",
        mode="combined",
        reference_hz=8,
        laser_current_a=0.0218,
        power_limit_w=1e-6,
        settle_s=15,
        samples_per_phase=3,
        phase_timeout_s=60,
        max_run_s=180,
    )
    approval = PilotApproval(
        enabled=True,
        sample_id="CrSBr 1",
        reference_hz=8,
        laser_current_max_a=0.0218,
        power_limit_max_w=1e-6,
        max_phase_s=60,
        max_run_s=180,
    )
    result = PilotEngine(station, clock=lambda: now[0], sleep=sleep).run(plan, approval)
    assert result["status"] == "COMPLETED", result["error"]
    assert len(manager.devices) == 5 and "GPIB1::10::INSTR" not in manager.devices
    assert result["preflight"]["readout_roles"] == ["xx", "xy"]
    assert result["preflight"]["excluded_readout_roles"] == ["aux"]
    assert all(set(s["channels"]) == {"xx", "xy"} for s in result["samples"])
    assert all(s["excluded_readout_roles"] == ["aux"] for s in result["samples"])
    assert all(s["channels"]["xy"]["harmonic"] == 2 for s in result["samples"][-3:])
    assert result["protection_verified"] is True
    cld = manager.devices[config["resources"]["cld"]]
    assert cld.values["OUTP1:STAT?"] == "0" and cld.values["SOUR1:CURR:LEV:IMM:AMPL?"] == "0"
    assert manager.devices[config["resources"]["xx"]].values["SLVL?"] == "0.004"


@pytest.mark.parametrize("fault", ["gate", "interlock", "reference", "chopper", "minimum_settle"])
def test_excluding_aux_preserves_remaining_hardware_guards(tmp_path, fault):
    from labos.cryostat_pilot import CryostatAdapter

    config = settings(tmp_path)
    config["aux_enabled"] = False
    del config["resources"]["aux"]
    manager = Manager(config)
    if fault == "gate":
        manager.devices[config["resources"]["gate"]].values["OUTP?"] = "1"
    elif fault == "interlock":
        manager.devices[config["resources"]["cld"]].values["OUTP1:PROT:INTL:TRIP?"] = "1"
    elif fault == "reference":
        manager.devices[config["resources"]["xy"]].values["FREQ?"] = "56"
    elif fault == "chopper":
        config["chopper_expected"]["blade"] = 11
    station = CryostatAdapter(config, manager_factory=lambda: manager, chopper_factory=Chopper)
    station.open()
    if fault == "minimum_settle":
        station.preflight()
        plan = PilotPlan(sample_id="CrSBr 1", mode="dark_hall", reference_hz=8, settle_s=1)
        with pytest.raises(ValueError):
            station.configure("dark_hall_2f", plan)
    else:
        with pytest.raises(ValueError):
            station.preflight()
    assert all(not r.writes for r in manager.devices.values())
    station.close()


@pytest.mark.parametrize(
    "fault", ["missing_aux_without_exclusion", "retained_aux_with_exclusion", "missing_gate"]
)
def test_channel_exclusion_requires_an_explicit_consistent_binding_set(tmp_path, fault):
    from labos.cryostat_pilot import CryostatAdapter

    config = settings(tmp_path)
    if fault == "missing_aux_without_exclusion":
        del config["resources"]["aux"]
    elif fault == "retained_aux_with_exclusion":
        config["aux_enabled"] = False
    else:
        config["aux_enabled"] = False
        del config["resources"]["aux"]
        del config["resources"]["gate"]
    with pytest.raises(ValueError):
        CryostatAdapter(config, manager_factory=lambda: pytest.fail("opened a device"))


def test_required_aux_timeout_never_silently_changes_the_instrument_set(tmp_path):
    station, manager = adapter(tmp_path)

    def timeout(command):
        raise TimeoutError("AUX did not respond")

    manager.devices["GPIB1::10::INSTR"].query = timeout
    station.open()
    with pytest.raises(TimeoutError):
        station.preflight()
    assert all(not r.writes for r in manager.devices.values())
    station.close()
