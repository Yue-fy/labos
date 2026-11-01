import pytest
import yaml
import time

from labos_field.engine import CampaignEngine, validate_campaign
from labos_field.models import default_task
from labos.pilot import PilotApproval
from test_field_magnet import Clock, State
from dataclasses import asdict, replace


class Optical:
    def __init__(self):
        self.emission = False
        self.open_count = self.close_count = self.on_count = 0
        self.excitation = 0.004
        self.fail_read = False

    def open(self):
        self.open_count += 1

    def close(self):
        self.close_count += 1

    def set_guard(self, *args):
        pass

    def preflight(self):
        return {"ready": True, "laser_enabled": self.emission}

    def configure(self, phase, plan):
        self.laser_off()

    def laser_on(self, current):
        assert current == 0.02
        self.emission = True
        self.on_count += 1

    def laser_off(self):
        self.emission = False
        return {
            "laser_off_verified": True,
            "emission_off_readback": True,
            "zero_current_setpoint_verified": True,
        }

    def protect_excitation(self):
        return {"minimum_excitation_verified": True, "actual_v_rms": 0.004}

    def read_sample(self, phase):
        if self.fail_read:
            raise OSError("acquisition failed")
        channel = {
            "x_v": 0.002 if self.emission else 0.0,
            "y_v": 0.001,
            "harmonic": 1,
            "lia_status_raw": 0,
            "error_status_raw": 0,
            "reference_hz": 8.0,
        }
        return {
            "channels": {"xx": dict(channel), "xy": dict(channel)},
            "power_w": 475e-9 if self.emission else 0.0,
            "simulated": False,
            "laser_enabled": self.emission,
            "excitation_v_rms": 0.004,
        }


class Magnet:
    def __init__(self, optical=None):
        self.state = State()
        self.targets = []
        self.zero_count = self.close_count = 0
        self.healthy = True
        self.optical = optical
        self.fail_at = None
        self.fail_zero = False
        self.stall_on_light = False

    def set_guard(self, deadline):
        pass

    def open(self, writes=False):
        return {"initial_state": asdict(self.state), "writes_authorized": writes}

    def move(self, z):
        assert not self.optical.emission
        self.targets.append(z)
        if z == self.fail_at:
            raise OSError("field transition failed")
        from test_field_magnet import Vector

        self.state = replace(
            self.state,
            field=Vector(0.0, z),
            field_setpoint=Vector(0.0, z),
            field_control_enabled=True,
        )
        return {"qualified": True, "state": asdict(self.state), "target_z_t": z}

    def read(self):
        if self.stall_on_light and self.optical.emission:
            self.healthy = False
            raise TimeoutError("SDK child stalled during illumination")
        return {"state": asdict(self.state)}

    def zero(self):
        assert not self.optical.emission
        self.zero_count += 1
        if self.fail_zero:
            raise OSError("zero return failed")
        self.state = State()
        return {
            "zero_verified": True,
            "initial_control_restored": True,
            "state": asdict(self.state),
            "post_restore_zero_states": [asdict(self.state)] * 11,
        }

    def close(self):
        self.close_count += 1
        return {"closed": True}


def run(optical=None, magnet=None, task=None, event_sink=lambda event: None):
    clock = Clock()
    optical = optical or Optical()
    magnet = magnet or Magnet(optical)
    config = type(
        "Settings",
        (),
        {
            "max_campaign_s": 6300.0,
            "cleanup_timeout_s": 900.0,
            "temperature_baseline_k": 180.0,
            "temperature_setpoint_k": 180.0,
            "temperature_drift_max_k": 0.1,
        },
    )()
    approval = PilotApproval(
        enabled=True,
        sample_id="CrSBr 1",
        laser_current_max_a=0.0218,
        power_limit_max_w=1e-6,
        reference_hz=8.0,
        max_phase_s=60.0,
        max_run_s=180.0,
    )
    result = CampaignEngine(optical, magnet, config, clock=clock, sleep=clock.sleep).run(
        task or default_task("campaign-test-001"), approval, event_sink=event_sink
    )
    return result, optical, magnet


def test_five_native_points_and_thirty_raw_samples_with_one_shared_session():
    result, optical, magnet = run()
    assert result["status"] == "COMPLETED"
    assert [p["target_z_t"] for p in result["points"]] == [-0.5, -0.25, 0.0, 0.25, 0.5]
    assert sum(len(p["optical"]["samples"]) for p in result["points"]) == 30
    assert optical.open_count == optical.close_count == 1
    assert optical.on_count == 5 and not optical.emission
    assert magnet.zero_count == magnet.close_count == 1
    assert validate_campaign(result)["accepted"] is True
    for p in result["points"]:
        for sample in p["optical"]["samples"]:
            assert sample["magnetic_before"]["state"]["field"]["bz_t"] == p["target_z_t"]
            assert sample["magnetic_after"]["state"]["field"]["bz_t"] == p["target_z_t"]


def test_first_transition_failure_stops_remaining_points_but_attempts_protected_zero():
    optical = Optical()
    magnet = Magnet(optical)
    magnet.fail_at = -0.25
    result, optical, magnet = run(optical, magnet)
    assert result["status"] == "FAILED"
    assert magnet.targets == [-0.5, -0.25] and optical.on_count == 1
    assert magnet.zero_count == 1 and not optical.emission
    assert validate_campaign(result)["accepted"] is False


def test_sdk_stall_in_light_does_not_prevent_parent_laser_protection():
    optical = Optical()
    magnet = Magnet(optical)
    magnet.stall_on_light = True
    result, optical, magnet = run(optical, magnet)
    assert result["status"] == "UNKNOWN" and not optical.emission
    assert optical.close_count == 1 and magnet.targets == [-0.5]
    assert magnet.zero_count == 0  # No blind command into an uncertain child.


def test_failed_final_zero_or_close_never_reports_completed():
    optical = Optical()
    magnet = Magnet(optical)
    magnet.fail_zero = True
    result, optical, _ = run(optical, magnet)
    assert len(result["points"]) == 5 and result["status"] == "UNKNOWN" and not optical.emission
    assert validate_campaign(result)["accepted"] is False


def test_log_failure_still_attempts_optical_protection_zero_and_closure():
    clock = Clock()
    optical = Optical()
    magnet = Magnet(optical)
    config = type(
        "Settings",
        (),
        {
            "max_campaign_s": 6300.0,
            "cleanup_timeout_s": 900.0,
            "temperature_baseline_k": 180.0,
            "temperature_setpoint_k": 180.0,
            "temperature_drift_max_k": 0.1,
        },
    )()
    approval = PilotApproval(
        enabled=True,
        sample_id="CrSBr 1",
        laser_current_max_a=0.0218,
        power_limit_max_w=1e-6,
        reference_hz=8.0,
        max_phase_s=60.0,
        max_run_s=180.0,
    )

    def failed_log(event):
        raise OSError("disk full")

    result = CampaignEngine(optical, magnet, config, clock=clock, sleep=clock.sleep).run(
        default_task("campaign-log-failure"), approval, event_sink=failed_log
    )
    assert result["status"] != "COMPLETED"
    assert not optical.emission and optical.close_count == 1
    assert result["evidence_errors"]


def test_missing_or_rejected_sample_cannot_pass_central_acceptance():
    result, _, _ = run()
    result["points"][2]["optical"]["samples"].pop()
    with pytest.raises(ValueError):
        validate_campaign(result)


def test_operator_interrupt_retains_first_raw_sample_and_closes_outputs():
    from labos_field.records import artifact_messages, reassemble

    optical = Optical()
    original = optical.read_sample
    count = [0]

    def interrupted(phase):
        count[0] += 1
        if count[0] == 2:
            raise KeyboardInterrupt("operator stop")
        return original(phase)

    optical.read_sample = interrupted
    result, optical, magnet = run(optical, Magnet(optical))
    assert result["status"] != "COMPLETED" and not optical.emission
    assert result["points"][0]["optical"]["status"] == "CANCELLED"
    records = result["points"][0]["raw_reads"]
    assert records[0]["raw"]["channels"]["xx"]["x_v"] == 0.0
    assert records[0]["phase"] == "dark_baseline"
    recovered = reassemble(artifact_messages("interrupted-task", result))
    assert recovered["points"][0]["raw_reads"] == records
    assert optical.close_count == 1 and magnet.zero_count == 1


def delayed_illuminated_child(connection, config, state_dir):
    connection.send({"ready": True})
    request = connection.recv()
    assert request["args"]["illuminated"] is True
    time.sleep(0.5)
    connection.send({"id": request["id"], "ok": True, "result": {"late": True}})
    connection.close()


def test_real_delayed_child_during_illumination_leaves_parent_free_to_close_laser(tmp_path):
    from labos_field.rpc import MagnetProcess

    optical = Optical()
    rpc = MagnetProcess({}, tmp_path, target=delayed_illuminated_child)
    assert rpc.connection.poll(5.0) and rpc.connection.recv()["ready"]

    class ActualStall(Magnet):
        def read(self):
            if self.optical.emission:
                try:
                    rpc.call("read", {"illuminated": True}, timeout=0.05)
                except Exception:
                    self.healthy = False
                    raise
            return super().read()

    try:
        result, optical, magnet = run(optical, ActualStall(optical))
        assert result["status"] == "UNKNOWN" and not optical.emission
        assert optical.close_count == 1 and magnet.zero_count == 0
        assert rpc.process.is_alive()  # Parent protected optics before the blocked child returned.
    finally:
        rpc.process.join(3.0)
        rpc.connection.close()
    assert rpc.process.exitcode == 0


def test_disabled_cli_run_never_creates_a_hardware_intent(tmp_path, capsys):
    from labos_field.__main__ import main

    config = {
        "enabled": False,
        "task_id": "not-running",
        "message_id": "msg_not_running",
        "message_sha256": "a" * 64,
        "connection_config": "missing.yaml",
        "optical_profile": "missing-optical.yaml",
        "optical_profile_sha256": "b" * 64,
        "state_dir": str(tmp_path / "state"),
        "magnetic_source_dir": "missing-src",
        "dll_path": "missing.dll",
        "magnetic_lease_profiles": ["one.toml", "two.toml"],
        "temperature_baseline_k": 180.0,
    }
    path = tmp_path / "field.yaml"
    path.write_text(yaml.safe_dump(config))
    assert main(["run", "--config", str(path)]) == 1
    assert "disabled" in capsys.readouterr().out
    assert not (tmp_path / "state" / "field-intents.sqlite").exists()
