"""Replay/HTTP checks of explicit OFF/ON readback scope, not hardware acceptance."""

import runpy

import pytest
from fastapi.testclient import TestClient

from labos.central import create_app
from labos.cryostat_pilot import CryostatAdapter, CryostatConfig
from labos.files import InstanceLock
from labos.pilot import PilotApproval, PilotEngine, PilotPlan
from test_cryostat_pilot import Manager, settings
from test_pilot_worker import approval, configuration, module, send, task, transport


def readback_settings(tmp_path):
    cfg = settings(tmp_path)
    cfg.update(experiment_scope="optical_readback", aux_enabled=False)
    cfg["resources"].pop("aux")
    for k in list(cfg):
        if k.startswith("chopper_"):
            cfg.pop(k)
    return cfg


def plan():
    return PilotPlan(
        sample_id="CrSBr 1",
        mode="photoresponse",
        laser_current_a=0.0218,
        power_limit_w=1e-6,
        reference_hz=8.0,
        settle_s=15.0,
        samples_per_phase=3,
        phase_timeout_s=60.0,
        max_run_s=180.0,
    )


def bench(tmp_path):
    cfg = readback_settings(tmp_path)
    manager = Manager(cfg)

    def forbidden(*_):
        pytest.fail("explicit optical readback must never open the chopper")

    a = CryostatAdapter(cfg, manager_factory=lambda: manager, chopper_factory=forbidden)
    return a, manager


def test_readback_engine_collects_off_on_power_voltages_without_serial(tmp_path, monkeypatch):
    a, m = bench(tmp_path)
    now = [0.0]
    monkeypatch.setattr("labos.cryostat_pilot.time.monotonic", lambda: now[0])

    def sleep(t):
        now[0] += t

    local = PilotApproval(
        enabled=True,
        sample_id="CrSBr 1",
        reference_hz=8.0,
        laser_current_max_a=0.0218,
        power_limit_max_w=1e-6,
        max_phase_s=60.0,
        max_run_s=180.0,
    )
    r = PilotEngine(a, clock=lambda: now[0], sleep=sleep).run(plan(), local)
    assert r["status"] == "COMPLETED" and r["protection_verified"]
    assert len(r["samples"]) == 6
    assert [s["laser_enabled"] for s in r["samples"]] == [False] * 3 + [True] * 3
    assert r["preflight"]["chopper"]["out_of_scope"] is True
    for s in r["samples"]:
        assert s["experiment_scope"] == "optical_readback"
        assert s["chopper"]["out_of_scope"] is True
        assert "chopper_refout_hz" not in s
        assert s["optical_modulation_verified"] is False
        assert s["power_w"] == 4.8e-7
        assert set(s["channels"]) == {"xx", "xy"}
    cld = m.devices[a.config.resources["cld"]]
    assert cld.writes.count("OUTP1:STAT 1") == 1
    assert cld.values["OUTP1:STAT?"] == "0"
    assert cld.values["SOUR1:CURR:LEV:IMM:AMPL?"] == "0"
    xx = m.devices[a.config.resources["xx"]]
    assert set(xx.writes) <= {"SLVL 0.004", "HARM 1"}
    gate = m.devices[a.config.resources["gate"]]
    assert not gate.writes and set(gate.queries) == {"*IDN?", "OUTP?"}
    assert all(x.closed for x in m.devices.values())


def test_overpowered_dark_readback_stops_before_any_laser_enable(tmp_path, monkeypatch):
    a, m = bench(tmp_path)
    now = [0.0]
    monkeypatch.setattr("labos.cryostat_pilot.time.monotonic", lambda: now[0])
    m.devices[a.config.resources["pm"]].values["READ?"] = "2e-6"

    def sleep(t):
        now[0] += t

    local = PilotApproval(
        enabled=True,
        sample_id="CrSBr 1",
        reference_hz=8.0,
        laser_current_max_a=0.0218,
        power_limit_max_w=1e-6,
        max_phase_s=60.0,
        max_run_s=180.0,
    )
    r = PilotEngine(a, clock=lambda: now[0], sleep=sleep).run(plan(), local)
    assert r["status"] == "FAILED" and r["protection_verified"]
    assert r["samples"] == [] and r["rejected_samples"][0]["raw"]["power_w"] == 2e-6
    assert "OUTP1:STAT 1" not in m.devices[a.config.resources["cld"]].writes


@pytest.mark.parametrize(
    "role,command,value",
    [
        ("cld", "SENS2:TEMP:DATA?", "27"),
        ("gate", "OUTP?", "1"),
        ("pm", "SENS:CORR:WAV?", "980"),
        ("xx", "FREQ?", "9"),
        ("xy", "FMOD?", "1"),
    ],
)
def test_readback_retains_preflight_guards_and_no_output_takeover(tmp_path, role, command, value):
    a, m = bench(tmp_path)
    m.devices[a.config.resources[role]].values[command] = value
    a.open()
    with pytest.raises(ValueError):
        a.preflight()
    assert not any(x.writes for x in m.devices.values())
    a.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_laser_current_a", 0.022),
        ("power_limit_w", 2e-6),
        ("reference_hz", 9),
        ("aux_enabled", True),
    ],
)
def test_readback_profile_has_narrow_local_bounds(tmp_path, field, value):
    cfg = readback_settings(tmp_path)
    cfg[field] = value
    with pytest.raises(ValueError):
        CryostatConfig.model_validate(cfg)


@pytest.mark.parametrize("mode", ["combined", "dark_hall"])
def test_readback_worker_rejects_other_modes_before_intent(tmp_path, central_config, mode):
    p = plan().model_dump(mode="json")
    p["mode"] = mode
    if mode == "dark_hall":
        p.update(laser_current_a=None, power_limit_w=None)
    cfg = configuration(
        tmp_path,
        adapter_config={"experiment_scope": "optical_readback"},
        approval=approval(
            reference_hz=8.0, power_limit_max_w=1e-6, max_phase_s=60.0, max_run_s=180.0
        ),
    )

    def forbidden(_):
        pytest.fail("scope mismatch constructed an adapter")

    with TestClient(create_app(central_config)) as api:
        envelope = send(api, "mismatch", task(pilot_plan=p))
        w = module().PilotWorker(cfg, transport(api), forbidden)
        assert w.respond(envelope, "")["answer"]["status"] == "needs_input"
        with w.physical_db() as db:
            assert db.execute("SELECT COUNT(*) FROM executions").fetchone()[0] == 0


def test_prepare_new_readback_profile_preserves_sources_and_diagnostics(tmp_path):
    from labos.optical_readback import prepare_config
    from labos.pilot_worker import load_pilot_worker_config

    base = settings(tmp_path)
    base["aux_enabled"] = False
    base["resources"].pop("aux")
    base.update(
        cld_acknowledged_connection_diagnostics=[1, 1, 8192],
        cld_acknowledgement_note="Exact existing local acknowledgment",
    )
    cfg = configuration(
        tmp_path,
        adapter_config=base,
        approval=approval(enabled=False, reference_hz=8.0, max_phase_s=60.0, max_run_s=180.0),
    )
    source = tmp_path / "pilot-worker.yaml"
    source.write_text(cfg.model_dump_json())
    saved = source.read_bytes()
    output = tmp_path / "optical-readback-worker.yaml"
    prepare_config(source, output, start_after=102)
    new = load_pilot_worker_config(output)
    assert source.read_bytes() == saved
    assert new.approval.enabled is False and new.start_after == 102
    assert new.approval.laser_current_max_a == cfg.approval.laser_current_max_a
    assert new.approval.power_limit_max_w == cfg.approval.power_limit_max_w
    assert new.state_dir != cfg.state_dir
    assert new.adapter_config["experiment_scope"] == "optical_readback"
    assert set(new.adapter_config["resources"]) == {"cld", "pm", "xx", "xy", "gate"}
    assert new.adapter_config["cld_acknowledged_connection_diagnostics"] == [1, 1, 8192]
    assert new.adapter_config["cld_acknowledgement_note"] == base["cld_acknowledgement_note"]
    assert not any(k.startswith("chopper_") for k in new.adapter_config)
    with pytest.raises(FileExistsError):
        prepare_config(source, output, start_after=102)


def test_update_refuses_active_readback_worker_before_mutation(tmp_path):
    from test_pilot_update import fixture, APPLY

    update, target = fixture(tmp_path)
    (target / "optical-readback-worker.yaml").write_text(
        "agent_id: pc-a\nconnection_config: config.yaml\nstate_dir: data/optical-readback-pilot\n"
    )
    with InstanceLock(target / "data/optical-readback-pilot"), pytest.raises(RuntimeError):
        runpy.run_path(str(APPLY))["apply_update"](update, target)
    assert (target / "Check-Pilot-Runtime.py").read_text() == "# previous runtime check\n"
