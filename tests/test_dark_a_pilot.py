"""Dark voltage workflow at replay/HTTP boundaries; never hardware acceptance."""

import pytest
from fastapi.testclient import TestClient

from labos.central import create_app
from labos.cryostat_pilot import CryostatAdapter, CryostatConfig
from labos.pilot import PilotEngine
from test_cryostat_pilot import Manager, settings
from test_pilot import SimulatedBench, approval, plan
from test_pilot_worker import configuration, module, send, task, transport


def dark_settings(tmp_path):
    cfg = settings(tmp_path)
    cfg.update(experiment_scope="dark_a", aux_enabled=False)
    cfg["resources"] = {k: v for k, v in cfg["resources"].items() if k in {"cld", "xx", "gate"}}
    for key in list(cfg):
        if key.startswith("chopper_"):
            cfg.pop(key)
    return cfg


def dark_plan(**overrides):
    return plan(mode="dark_a", laser_current_a=None, power_limit_w=None,
                reference_hz=8.0, settle_s=15.0, samples_per_phase=3,
                phase_timeout_s=30.0, max_run_s=90.0, **overrides)


def test_dark_engine_runs_two_voltage_phases_without_laser_enable():
    bench = SimulatedBench()
    result = PilotEngine(bench, clock=bench.clock, sleep=bench.clock.sleep).run(
        dark_plan(), approval(reference_hz=8.0, laser_current_max_a=None,
                              power_limit_max_w=None))
    assert result["status"] == "COMPLETED"
    assert [s["phase"] for s in result["samples"]] == ["dark_a_1f"] * 3 + ["dark_a_2f"] * 3
    assert not any(x["operation"] == "laser_on" for x in bench.history)
    with pytest.raises(ValueError):
        plan(mode="dark_a")


def test_dark_adapter_has_three_sessions_no_optical_bus_and_raw_xx_only(tmp_path):
    cfg = dark_settings(tmp_path)
    manager = Manager(cfg)
    def forbidden(*args):
        pytest.fail("dark a-axis test must never open chopper")
    adapter = CryostatAdapter(cfg, manager_factory=lambda: manager, chopper_factory=forbidden)
    # Accelerate only the engine clock. Real adapter guard deadlines stay unset here.
    adapter.open()
    observed = adapter.preflight()
    assert observed["readout_roles"] == ["xx"]
    assert observed["excluded_readout_roles"] == ["xy", "aux"]
    assert observed["measurement_plane"] == "XX voltage input; operator identifies a axis"
    assert observed["sample_current_calibrated"] is False
    assert all(not x.writes for x in manager.devices.values())
    samples = []
    for phase in ("dark_a_1f", "dark_a_2f"):
        adapter.configure(phase, dark_plan())
        sample = adapter.read_sample(phase)
        samples.append(sample)
        assert set(sample["channels"]) == {"xx"}
        assert "power_w" not in sample and "nominal_wavelength_nm" not in sample
        assert sample["laser_enabled"] is False
    assert [s["channels"]["xx"]["harmonic"] for s in samples] == [1, 2]
    assert samples[1]["channels"]["xx"]["detection_frequency_hz"] == 16
    protection = adapter.protect_excitation()
    assert protection["minimum_excitation_verified"] is True
    assert protection["measurement_harmonic_restored"] is True
    xx = manager.devices[cfg["resources"]["xx"]]
    assert xx.values["HARM?"] == "1"
    assert set(xx.writes) <= {"HARM 1", "HARM 2", "SLVL 0.004"}
    gate = manager.devices[cfg["resources"]["gate"]]
    assert not gate.writes and set(gate.queries) == {"*IDN?", "OUTP?"}
    cld = manager.devices[cfg["resources"]["cld"]]
    assert "OUTP1:STAT 1" not in cld.writes
    adapter.close()
    assert all(x.closed for x in manager.devices.values())


@pytest.mark.parametrize("fault", ["frequency", "amplitude", "status", "laser", "gate"])
def test_dark_sample_guard_failures_retain_partial_and_protect(tmp_path, fault):
    cfg = dark_settings(tmp_path)
    manager = Manager(cfg)
    a = CryostatAdapter(cfg, manager_factory=lambda: manager)
    a.open()
    a.preflight()
    a.configure("dark_a_2f", dark_plan())
    role, key, value = {
        "frequency": ("xx", "FREQ?", "9"),
        "amplitude": ("xx", "SLVL?", "0.005"),
        "status": ("xx", "LIAS?", "1"),
        "laser": ("cld", "OUTP1:STAT?", "1"),
        "gate": ("gate", "OUTP?", "1"),
    }[fault]
    manager.devices[cfg["resources"][role]].values[key] = value
    with pytest.raises(ValueError) as exc:
        a.read_sample("dark_a_2f")
    assert hasattr(exc.value, "raw_sample")
    assert a.laser_off()["laser_off_verified"] is True
    # A frequency drift is reported and never corrected with a FREQ write.
    p = a.protect_excitation()
    assert p["minimum_excitation_verified"] is (fault != "frequency")
    a.close()


def test_optical_config_still_requires_chopper_and_dark_rejects_extra_roles(tmp_path):
    cfg = settings(tmp_path)
    cfg.pop("chopper_port")
    with pytest.raises(ValueError):
        CryostatConfig.model_validate(cfg)
    cfg = dark_settings(tmp_path)
    cfg["resources"]["xy"] = "GPIB1::9::INSTR"
    with pytest.raises(ValueError):
        CryostatConfig.model_validate(cfg)


@pytest.mark.parametrize("local_scope,requested_mode", [("dark_a", "combined"), ("optical_transport", "dark_a")])
def test_worker_scope_mismatch_rejected_before_intent_or_factory(tmp_path, central_config, local_scope, requested_mode):
    from test_pilot_worker import approval as worker_approval, plan as worker_plan
    config = configuration(tmp_path, adapter_config={"experiment_scope": local_scope},
                           approval=worker_approval())
    def forbidden(_):
        pytest.fail("scope mismatch reached adapter factory")
    p = worker_plan(mode=requested_mode)
    if requested_mode == "dark_a":
        p.update(laser_current_a=None, power_limit_w=None)
    with TestClient(create_app(central_config)) as api:
        envelope = send(api, "mismatch", task(pilot_plan=p))
        worker = module().PilotWorker(config, transport(api), forbidden)
        response = worker.respond(envelope, "")
        assert response["answer"]["status"] == "needs_input"
        with worker.physical_db() as db:
            assert db.execute("SELECT COUNT(*) FROM executions").fetchone()[0] == 0


def test_dark_profile_preparation_preserves_source_and_disables_optics(tmp_path):
    from labos.dark_a import prepare_config
    from labos.pilot_worker import load_pilot_worker_config
    cfg = configuration(tmp_path, approval={
        "enabled": False, "sample_id": "CrSBr 1", "reference_hz": 8,
        "laser_current_max_a": 0.0218, "power_limit_max_w": 1e-6,
        "max_phase_s": 90, "max_run_s": 300}, adapter_config=settings(tmp_path))
    source = tmp_path / "pilot-worker.yaml"
    source.write_text(cfg.model_dump_json())
    original = source.read_bytes()
    output = tmp_path / "dark-a-worker.yaml"
    prepare_config(source, output, start_after=80)
    candidate = load_pilot_worker_config(output)
    assert source.read_bytes() == original
    assert candidate.approval.enabled is False
    assert candidate.approval.laser_current_max_a is None
    assert candidate.approval.power_limit_max_w is None
    assert candidate.approval.max_run_s == 90
    assert candidate.state_dir != cfg.state_dir
    assert candidate.start_after == 80
    assert set(candidate.adapter_config["resources"]) == {"cld", "xx", "gate"}
    assert candidate.adapter_config["station_config"] == cfg.adapter_config["station_config"]
    with pytest.raises(FileExistsError):
        prepare_config(source, output, start_after=80)
    assert source.read_bytes() == original


def test_dark_artifact_crosses_real_http_boundary(tmp_path, central_config):
    from test_pilot_artifacts import auth, fixture_payload, queue
    from labos.files import json_bytes
    import hashlib
    p, payload = fixture_payload()
    p["mode"] = "dark_a"
    payload["plan_sha256"] = hashlib.sha256(json_bytes(p)).hexdigest()
    payload["report"]["samples"][0].update(phase="dark_a_2f", channels={"xx": {"x_v": 1e-8, "harmonic": 2}})
    with TestClient(create_app(central_config)) as api:
        queue(api, p)
        response = api.post('/api/agents/pc-a/pilot-artifacts', headers=auth('A') | {'X-SHA256': hashlib.sha256(json_bytes(payload)).hexdigest()}, content=json_bytes(payload))
        assert response.status_code == 200, response.text


def test_dark_adapter_refuses_laser_enable_even_with_wrong_phase_marker(tmp_path):
    cfg = dark_settings(tmp_path)
    m = Manager(cfg)
    a = CryostatAdapter(cfg, manager_factory=lambda: m)
    a.open()
    a.preflight()
    a.phase = 'illuminated'
    with pytest.raises(ValueError):
        a.laser_on(0.0218)
    assert not m.devices[cfg['resources']['cld']].writes
    a.close()


def test_dark_rechecks_frequency_after_snapshot_before_accepting_voltage(tmp_path):
    cfg = dark_settings(tmp_path)
    m = Manager(cfg)
    a = CryostatAdapter(cfg, manager_factory=lambda: m)
    a.open()
    a.preflight()
    a.configure('dark_a_2f', dark_plan())
    xx = m.devices[cfg['resources']['xx']]
    original = xx.query
    def query(command):
        value = original(command)
        if command.startswith('SNAP?'):
            xx.values['FREQ?'] = '9'
        return value
    xx.query = query
    with pytest.raises(ValueError) as exc:
        a.read_sample('dark_a_2f')
    assert exc.value.raw_sample['channels']['xx']['harmonic'] == 2
    assert a.laser_off()['laser_off_verified']
    a.protect_excitation()
    a.close()


def test_dark_cleanup_attempts_harmonic_restore_after_amplitude_read_failure(tmp_path):
    cfg = dark_settings(tmp_path)
    m = Manager(cfg)
    a = CryostatAdapter(cfg, manager_factory=lambda: m)
    a.open()
    a.preflight()
    a.configure('dark_a_2f', dark_plan())
    xx = m.devices[cfg['resources']['xx']]
    original = xx.query
    def query(command):
        if command == 'SLVL?':
            raise TimeoutError('readback failed')
        return original(command)
    xx.query = query
    result = a.protect_excitation()
    assert result['minimum_excitation_verified'] is False
    assert result['actual_v_rms'] is None
    assert result['measurement_harmonic_restored'] is True
    assert xx.values['HARM?'] == '1'
    a.close()


def test_dark_cleanup_faults_do_not_replace_acquisition_fault_after_deadline(tmp_path, monkeypatch):
    cfg = dark_settings(tmp_path)
    manager = Manager(cfg)
    adapter = CryostatAdapter(cfg, manager_factory=lambda: manager)
    adapter.open()
    adapter.preflight()
    adapter.configure("dark_a_2f", dark_plan())
    xx = adapter.resources["xx"]
    original = xx.query

    cleanup = [False]

    def failed(command):
        if command.startswith("SNAP?"):
            raise OSError("snapshot lost")
        if cleanup[0] and command == "SLVL?":
            raise TimeoutError("cleanup amplitude lost")
        return original(command)

    xx.query = failed
    with pytest.raises(OSError, match="snapshot lost"):
        adapter.read_sample("dark_a_2f")
    before = adapter.diagnostics()
    cleanup[0] = True
    monkeypatch.setattr("labos.cryostat_pilot.time.monotonic", lambda: 10.0)
    adapter.set_guard(1.0, lambda: True)
    assert adapter.laser_off()["laser_off_verified"]
    result = adapter.protect_excitation()
    assert result["minimum_excitation_verified"] is False
    assert result["measurement_harmonic_restored"] is True
    adapter.close()
    after = adapter.diagnostics()
    assert after["first_acquisition_fault"] == before["first_acquisition_fault"]
    assert after["last_acquisition_io"] == before["last_acquisition_io"]
    assert after["first_acquisition_fault"]["io"]["command"] == "SNAP? 1,2,3,4,9"
    assert any(event.get("exception_type") == "TimeoutError" and event["protection"]
               for event in after["events"])
