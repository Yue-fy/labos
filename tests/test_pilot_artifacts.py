"""Real HTTP boundaries for physical time-series delivery, separate from spectra."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from labos.central import create_app
from labos.files import json_bytes


def auth(character):
    return {"Authorization": "Bearer " + character * 40}


def fixture_payload():
    plan = {
        "sample_id": "CrSBr 1",
        "mode": "dark_hall",
        "reference_hz": 8,
        "laser_current_a": None,
        "power_limit_w": None,
        "excitation_v_rms": 0.004,
        "samples_per_phase": 1,
        "interval_s": 0,
        "settle_s": 0,
        "phase_timeout_s": 30,
        "max_run_s": 120,
    }
    # Match canonical model normalization, without importing the store under test.
    for key in [
        "reference_hz",
        "excitation_v_rms",
        "interval_s",
        "settle_s",
        "phase_timeout_s",
        "max_run_s",
    ]:
        plan[key] = float(plan[key])
    digest = hashlib.sha256(json_bytes(plan)).hexdigest()
    report = {
        "status": "COMPLETED",
        "samples": [
            {
                "phase": "dark_hall_2f",
                "channels": {"xy": {"x_v": 1e-8, "y_v": -2e-9, "harmonic": 2}},
            }
        ],
        "cleanup": [
            {"laser_off_verified": True, "minimum_excitation_verified": True, "actual_v_rms": 0.004}
        ],
        "acquisition_complete": True,
        "protection_verified": True,
        "task_id": "pilot-001",
        "plan": plan,
        "config_sha256": "c" * 64,
        "adapter_id": "cryostat_v1",
    }
    return plan, {"message_id": "msg_pilot_001", "plan_sha256": digest, "report": report}


def queue(api, plan):
    r = api.post(
        "/api/agents/pc-a/messages",
        headers=auth("O"),
        json={
            "id": "msg_pilot_001",
            "kind": "note",
            "body": {
                "protocol": "labos-agent-v1",
                "document_type": "labos_pilot_task",
                "task_id": "pilot-001",
                "instruction": "Finite test",
                "pilot_plan": plan,
                "executable": False,
            },
        },
    )
    assert r.status_code == 200


def upload(api, payload, **kwargs):
    data = json_bytes(payload)
    return api.post(
        "/api/agents/pc-a/pilot-artifacts",
        content=data,
        headers={
            **auth("A"),
            "Content-Type": "application/json",
            "X-SHA256": hashlib.sha256(data).hexdigest(),
            **kwargs,
        },
    )


def test_raw_physical_artifact_is_durable_idempotent_and_operator_readable(central_config):
    plan, payload = fixture_payload()
    with TestClient(create_app(central_config)) as api:
        queue(api, plan)
        first = upload(api, payload)
        assert first.status_code == 200, first.text
        assert first.json()["sha256"] == hashlib.sha256(json_bytes(payload)).hexdigest()
        assert upload(api, payload).json() == first.json()
        assert (
            api.get("/api/pilot-artifacts/pc-a/msg_pilot_001", headers=auth("A")).status_code == 403
        )
        assert not api.app.state.store.runs()
    with TestClient(create_app(central_config)) as api:
        loaded = api.get("/api/pilot-artifacts/pc-a/msg_pilot_001", headers=auth("O"))
        assert loaded.status_code == 200
        assert loaded.json() == payload
        assert loaded.json()["report"]["samples"][0]["channels"]["xy"]["harmonic"] == 2
        payload["report"]["samples"][0]["channels"]["xy"]["x_v"] = 0.1
        assert upload(api, payload).status_code == 409
        original = api.get("/api/pilot-artifacts/pc-a/msg_pilot_001", headers=auth("O")).json()
        assert original["report"]["samples"][0]["channels"]["xy"]["x_v"] == 1e-8


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_parent",
        "wrong_plan",
        "wrong_task",
        "wrong_status",
        "credential",
        "nonfinite",
        "not_pilot_task",
        "non_object_sample",
        "non_object_channels",
        "non_object_channel",
        "non_numeric_voltage",
        "non_object_phase",
    ],
)
def test_invalid_artifacts_do_not_become_measurements(central_config, mutation):
    plan, payload = fixture_payload()
    with TestClient(create_app(central_config)) as api:
        queue(api, plan)
        if mutation == "unknown_parent":
            payload["message_id"] = "missing"
        elif mutation == "wrong_plan":
            payload["plan_sha256"] = "d" * 64
        elif mutation == "wrong_task":
            payload["report"]["task_id"] = "other"
        elif mutation == "wrong_status":
            payload["report"]["protection_verified"] = False
        elif mutation == "credential":
            payload["report"]["error"] = "A" * 40
        elif mutation == "nonfinite":
            payload["report"]["samples"][0]["channels"]["xy"]["x_v"] = float("nan")
        elif mutation == "not_pilot_task":
            payload["message_id"] = "ordinary"
            api.post(
                "/api/agents/pc-a/messages",
                headers=auth("O"),
                json={"id": "ordinary", "kind": "note", "body": {"text": "hello"}},
            )
        elif mutation == "non_object_sample":
            payload["report"]["samples"] = [1]
        elif mutation == "non_object_channels":
            payload["report"]["samples"][0]["channels"] = []
        elif mutation == "non_object_channel":
            payload["report"]["samples"][0]["channels"]["xy"] = 1
        elif mutation == "non_numeric_voltage":
            payload["report"]["samples"][0]["channels"]["xy"]["x_v"] = "bad"
        elif mutation == "non_object_phase":
            payload["report"]["samples"][0]["phase"] = []
        data = json.dumps(payload, allow_nan=True).encode()
        r = api.post(
            "/api/agents/pc-a/pilot-artifacts",
            content=data,
            headers={**auth("A"), "X-SHA256": hashlib.sha256(data).hexdigest()},
        )
        expected = 404 if mutation == "unknown_parent" else 409
        assert r.status_code == expected, r.text
        assert not list((central_config.data_dir / "pilot-artifacts").rglob("*.json"))


def test_artifact_auth_and_checksum_limits(central_config):
    plan, payload = fixture_payload()
    data = json_bytes(payload)
    with TestClient(create_app(central_config)) as api:
        queue(api, plan)
        for character, expected in [("B", 403), ("O", 403)]:
            r = api.post(
                "/api/agents/pc-a/pilot-artifacts",
                content=data,
                headers={**auth(character), "X-SHA256": hashlib.sha256(data).hexdigest()},
            )
            assert r.status_code == expected
        assert upload(api, payload, **{"X-SHA256": "0" * 64}).status_code == 409
        r = api.post(
            "/api/agents/pc-a/pilot-artifacts",
            content=b"x" * 2_000_001,
            headers={**auth("A"), "X-SHA256": "0" * 64},
        )
        assert r.status_code == 413
