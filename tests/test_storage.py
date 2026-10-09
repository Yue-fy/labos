import hashlib
import json

import pytest

from labos.files import export_hdf5
from labos.journal import Journal
from labos.models import InstrumentSpec, Plan, SetupProfile
from labos.store import Store


def ready_store(tmp_path):
    store = Store(tmp_path)
    store.enroll("pc-a", [InstrumentSpec(id="superk_01", kind="laser")])
    store.enroll("pc-b", [InstrumentSpec(id="rotator_01", kind="rotator"),
                          InstrumentSpec(id="spectrometer_01", kind="spectrometer")])
    return store


def test_resource_reservation_and_interrupted_runs(tmp_path):
    store = ready_store(tmp_path)
    run = store.create_run(Plan(), SetupProfile(), {"preflight": True})
    with pytest.raises(ValueError, match="reserved"):
        store.create_run(Plan(), SetupProfile(), {})
    store.recover()
    assert store.run(run["id"])["status"] == "INTERRUPTED"
    with pytest.raises(ValueError, match="reserved"):
        store.create_run(Plan(), SetupProfile(), {})


def test_command_idempotency_and_ambiguous_dispatch(tmp_path):
    store = ready_store(tmp_path)
    store.register("pc-a", "boot-a", now=100)
    run_id = store.create_run(Plan(), SetupProfile(), {})["id"]
    cmd = store.new_command(run_id, "point0", "superk_01", "set_wavelength", {"nm": 650})
    assert store.new_command(run_id, "point0", "superk_01", "set_wavelength", {"nm": 650})["id"] == cmd["id"]
    with pytest.raises(ValueError, match="different"):
        store.new_command(run_id, "point0", "superk_01", "set_wavelength", {"nm": 700})
    assert store.claim("pc-a", "boot-a")["id"] == cmd["id"]
    store.recover()
    assert store.command(cmd["id"])["state"] == "UNKNOWN"
    assert store.claim("pc-a", "boot-a") is None


def test_journal_never_replays_started_command(tmp_path):
    payload = {"id": "cmd1", "op": "set_angle", "parameters": {"angle_deg": 45}}
    journal = Journal(tmp_path)
    assert journal.start(payload) is None
    assert Journal(tmp_path).get("cmd1")["state"] == "UNKNOWN"
    assert journal.start(payload)["state"] == "UNKNOWN"
    with pytest.raises(ValueError, match="different"):
        journal.start({**payload, "parameters": {"angle_deg": 50}})


def artifact(store):
    run = store.create_run(Plan(), SetupProfile(), {})
    store.register("pc-b", "boot-b")
    params = {"point_index": 0, "sample_id": "demo_sample", "wavelength_nm": 650,
              "angle_deg": 0, "exposure_ms": 100, "power_percent": 5, "readbacks": {}}
    cmd = store.new_command(run["id"], "capture0", "spectrometer_01", "acquire_and_store", params)
    store.claim("pc-b", "boot-b")
    data = {"schema_version": 1, "measurement_id": cmd["id"], "command_id": cmd["id"],
            "experiment_id": run["id"], "point_index": 0, "instrument_id": "spectrometer_01",
            "agent_id": "pc-b", "timestamp": "2026-10-09T12:00:00+00:00",
            "sample_id": "demo_sample", "wavelength_nm": 650, "angle_deg": 0,
            "power_percent": 5, "exposure_ms": 100, "readbacks": {},
            "spectrum_axis_nm": [500, 501], "counts": [1, 2],
            "driver_version": "simulator-0.1.0", "workflow_version": "polarization-0.1.0",
            "simulated": True}
    return run, data


def test_upload_integrity_deduplication_and_hdf5(tmp_path):
    store = ready_store(tmp_path)
    run, data = artifact(store)
    content = json.dumps(data).encode()
    sha = hashlib.sha256(content).hexdigest()
    store.accept_artifact("pc-b", content, sha)
    store.accept_artifact("pc-b", content, sha)
    assert len(store.measurements(run["id"])) == 1
    with pytest.raises(ValueError, match="hash"):
        store.accept_artifact("pc-b", content, "0" * 64)
    with pytest.raises(ValueError, match="ownership"):
        store.accept_artifact("pc-a", content, sha)
    path = export_hdf5(store, run["id"])
    import h5py
    with h5py.File(path) as h5:
        assert h5["raw/counts"].shape == (1, 2)
        assert h5.attrs["simulated"]


def test_nonfinite_measurement_is_rejected(tmp_path):
    store = ready_store(tmp_path)
    _, data = artifact(store)
    data["counts"] = [float("nan"), 2]
    content = json.dumps(data).encode()
    with pytest.raises(ValueError):
        store.accept_artifact("pc-b", content, hashlib.sha256(content).hexdigest())


@pytest.mark.parametrize("field,value", [("simulated", False), ("driver_version", "unapproved"),
                                         ("workflow_version", "invented")])
def test_artifact_cannot_claim_a_different_driver_or_real_hardware(tmp_path, field, value):
    store = ready_store(tmp_path)
    _, data = artifact(store)
    data[field] = value
    content = json.dumps(data).encode()
    with pytest.raises(ValueError):
        store.accept_artifact("pc-b", content, hashlib.sha256(content).hexdigest())


def test_old_session_and_duplicate_live_agent_are_rejected(tmp_path):
    store = ready_store(tmp_path)
    store.register("pc-a", "boot1", now=100)
    with pytest.raises(ValueError, match="live"):
        store.register("pc-a", "boot2", now=101, offline_after=10)
    store.register("pc-a", "boot2", now=111, offline_after=10)
    with pytest.raises(ValueError, match="session"):
        store.heartbeat("pc-a", "boot1", {}, now=112)


def test_old_run_cannot_reconcile_or_queue_commands_on_new_run_resources(tmp_path):
    store = ready_store(tmp_path)
    old = store.create_run(Plan(), SetupProfile(), {})
    store.set_run(old["id"], "FAILED", "previous error", release=True)
    new = store.create_run(Plan(), SetupProfile(), {})
    with pytest.raises(ValueError, match="reserved"):
        store.begin_reconcile(old["id"])
    with pytest.raises(ValueError, match="ownership"):
        store.new_command(old["id"], "unsafe-recovery", "superk_01", "safe_shutdown", {})
    assert store.run(old["id"])["status"] == "FAILED"
    assert all(i["lock_run"] == new["id"] for i in store.registry()["instruments"])


def test_reconciliation_atomically_reserves_previously_released_resources(tmp_path):
    store = ready_store(tmp_path)
    run = store.create_run(Plan(), SetupProfile(), {})
    store.set_run(run["id"], "FAILED", release=True)
    store.begin_reconcile(run["id"])
    assert store.run(run["id"])["status"] == "RECONCILING"
    assert all(i["lock_run"] == run["id"] for i in store.registry()["instruments"])
