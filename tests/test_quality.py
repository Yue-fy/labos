import asyncio
import hashlib
import json

import h5py
import pytest

from labos.files import export_hdf5
from labos.models import Plan
from labos.store import Store
from test_runtime import run_with_local_pump
from test_storage import artifact, ready_store


def test_count_threshold_equality_rejects_but_preserves_raw(central_config, tmp_path):
    plan = Plan(angle_stop_deg=20, exposure_ms=1, quality={"max_counts": 2})
    store, run_id = asyncio.run(run_with_local_pump(central_config, tmp_path, plan))
    assert store.run(run_id)["status"] == "FAILED"
    assert store.run(run_id)["points"] == 0
    rows = store.measurements(run_id)
    assert len(rows) == 1
    assert store.qualification(rows[0]["measurement_id"])["status"] == "rejected"
    assert store.measurements(run_id, qualified_only=True) == []
    assert (store.root / "raw" / (rows[0]["measurement_id"] + ".json")).exists()
    assert all(i["lock_run"] is None for i in store.registry()["instruments"])
    with h5py.File(export_hdf5(store, run_id)) as h5:
        assert h5["raw/counts"].shape[0] == 0
        assert len(h5["audit/measurements_json"]) == 1
        assert 'rejected' in h5["audit/qualifications_json"][0].decode()


def test_local_detector_ceiling_rejects_without_operator_threshold(central_config, tmp_path):
    central_config.agents["pc-b"].instruments[1].detector_max_counts = 2
    store, run_id = asyncio.run(run_with_local_pump(
        central_config, tmp_path, Plan(angle_stop_deg=0, exposure_ms=1)))
    row = store.measurements(run_id)[0]
    assert row["detector_flags"]["overloaded"] is True
    assert "detector_overload" in store.qualification(row["measurement_id"])["reasons"]
    assert store.run(run_id)["status"] == "FAILED"


def test_provenance_tampering_is_refused(tmp_path):
    store = ready_store(tmp_path)
    run, data = artifact(store)
    # Existing fixture represents a legacy command. New commands bind the exact hashes.
    command = store.command(data["command_id"])
    params = {**command["parameters"], "provenance": store.provenance(run["id"])}
    with store.transaction() as db:
        db.execute("UPDATE commands SET parameters=? WHERE id=?", (json.dumps(params), data["command_id"]))
    data["provenance"] = {**store.provenance(run["id"]), "plan_sha256": "0" * 64}
    data["detector_flags"] = {"overloaded": False}
    content = json.dumps(data).encode()
    with pytest.raises(ValueError, match="provenance"):
        store.accept_artifact("pc-b", content, hashlib.sha256(content).hexdigest())
    assert not store.measurements(run["id"])


def test_historical_data_is_unassessed_not_silently_qualified(tmp_path):
    store = ready_store(tmp_path)
    run, data = artifact(store)
    with store.transaction() as db:
        db.execute("INSERT INTO measurements(id,run_id,point_index,sha,body) VALUES(?,?,?,?,?)",
                   (data["measurement_id"], run["id"], 0, "old", json.dumps(data)))
    reopened = Store(tmp_path)
    assert len(reopened.measurements(run["id"])) == 1
    assert reopened.measurements(run["id"], qualified_only=True) == []
    with h5py.File(export_hdf5(reopened, run["id"])) as h5:
        assert h5["raw/counts"].shape[0] == 0
        assert "unassessed" in h5["audit/qualifications_json"][0].decode()


def test_overload_flag_cannot_be_hidden_by_low_counts(central_config, tmp_path):
    from labos.files import Measurement
    from labos.models import QualityPolicy
    from labos.quality import assess
    store = ready_store(tmp_path)
    _, data = artifact(store)
    data["detector_flags"] = {"overloaded": True}
    data["provenance"] = store.provenance(data["experiment_id"])
    quality = assess(Measurement.model_validate(data), QualityPolicy(), None)
    assert quality["status"] == "rejected"
    assert "detector_overload" in quality["reasons"]


def test_stale_capture_result_cannot_skip_a_rejected_point(central_config, tmp_path, monkeypatch):
    from labos.agent import Agent
    from labos.drivers import SimulatedInstrument
    original_driver, original_agent = SimulatedInstrument.execute, Agent.execute
    first_id = []

    async def overload_after_first(self, op, parameters, cancel):
        result = await original_driver(self, op, parameters, cancel)
        if op == "acquire_and_store" and parameters["point_index"] > 0:
            result["detector_flags"]["overloaded"] = True
        return result

    async def stale_result(self, command):
        response = await original_agent(self, command)
        if command["op"] == "acquire_and_store":
            if not first_id:
                first_id.append(response["result"]["measurement_id"])
            response["result"]["measurement_id"] = first_id[0]
        return response

    monkeypatch.setattr(SimulatedInstrument, "execute", overload_after_first)
    monkeypatch.setattr(Agent, "execute", stale_result)
    store, run_id = asyncio.run(run_with_local_pump(
        central_config, tmp_path, Plan(angle_stop_deg=20, exposure_ms=1)))
    assert store.run(run_id)["status"] == "FAILED"
    assert "identity" in store.run(run_id)["error"]
    assert store.measurement_summary(run_id) == {"accepted": 1, "rejected": 1, "unassessed": 0, "total": 2}


def test_legacy_plan_late_upload_remains_synchronizable(tmp_path):
    store = ready_store(tmp_path)
    run, data = artifact(store)
    old_plan = {**run["plan"], "exposure_ms": 0.0001}
    old_plan.pop("quality")
    old_plan.pop("evidence_ids")
    parameters = {**store.command(data["command_id"])["parameters"], "exposure_ms": 0.0001}
    parameters.pop("provenance")
    data.update(exposure_ms=0.0001, workflow_version="polarization-0.1.0")
    data.pop("provenance")
    data.pop("detector_flags")
    with store.transaction() as db:
        db.execute("UPDATE runs SET plan=?,preflight='{}' WHERE id=?", (json.dumps(old_plan), run["id"]))
        db.execute("UPDATE commands SET parameters=? WHERE id=?", (json.dumps(parameters), data["command_id"]))
    content = json.dumps(data).encode()
    store.accept_artifact("pc-b", content, hashlib.sha256(content).hexdigest())
    assert len(store.measurements(run["id"])) == 1
    assert store.qualification(data["measurement_id"])["status"] == "unassessed"


def test_export_keeps_raw_audit_and_hashes_in_one_snapshot(tmp_path, monkeypatch):
    store = ready_store(tmp_path)
    run, first = artifact(store)
    content = json.dumps(first).encode()
    store.accept_artifact("pc-b", content, hashlib.sha256(content).hexdigest())
    params = {**store.command(first["command_id"])["parameters"], "point_index": 1, "angle_deg": 10}
    second_command = store.new_command(run["id"], "capture1", "spectrometer_01", "acquire_and_store", params)
    store.claim("pc-b", "boot-b")
    second = {**first, "measurement_id": second_command["id"], "command_id": second_command["id"],
              "point_index": 1, "angle_deg": 10}
    second_bytes = json.dumps(second).encode()
    original = store.measurements
    injected = []

    def late_upload(run_id, qualified_only=False):
        rows = original(run_id, qualified_only)
        if not qualified_only and not injected:
            injected.append(True)
            store.accept_artifact("pc-b", second_bytes, hashlib.sha256(second_bytes).hexdigest())
        return rows

    monkeypatch.setattr(store, "measurements", late_upload)
    with h5py.File(export_hdf5(store, run["id"])) as h5:
        raw = h5["raw/counts"].shape[0]
        assert raw == len(h5["audit/measurements_json"])
        assert raw == len(h5["audit/qualifications_json"])
        assert raw == len(h5["audit/artifact_sha256"])
