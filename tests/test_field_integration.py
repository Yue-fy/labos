import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
import httpx

from fastapi.testclient import TestClient
import pytest

from labos.central import create_app
from labos_field.engine import validate_campaign
from labos_field.models import default_task
from labos_field.records import artifact_messages, reassemble
from test_field_engine import run

ROOT = Path(__file__).resolve().parents[1]


def test_stock_central_stores_new_campaign_and_lossless_artifacts_without_execution(central_config):
    central_config.agents["cryostat-pc"] = central_config.agents.pop("pc-a")
    task = default_task("field-integration-001")
    envelope = {
        "id": "msg_field_integration",
        "kind": "note",
        "in_reply_to": None,
        "body": task.model_dump(mode="json"),
    }
    result = {"status": "FAILED", "raw": [{"i": i, "x": i / 13} for i in range(5000)]}
    parts = artifact_messages(task.task_id, result)
    path = "/api/agents/cryostat-pc/messages"
    with TestClient(create_app(central_config)) as api:
        queued = api.post(path, json=envelope, headers={"Authorization": "Bearer " + "O" * 40})
        assert queued.status_code == 200 and queued.json()["effect"] == "stored_only"
        for part in parts:
            part["in_reply_to"] = envelope["id"]
            first = api.post(path, json=part, headers={"Authorization": "Bearer " + "A" * 40})
            second = api.post(path, json=part, headers={"Authorization": "Bearer " + "A" * 40})
            assert first.status_code == second.status_code == 200
            assert first.json()["message"]["sequence"] == second.json()["message"]["sequence"]
        messages = api.get(
            path, params={"sender": "pc"}, headers={"Authorization": "Bearer " + "O" * 40}
        ).json()["messages"]
        assert reassemble(messages) == result
        with api.app.state.store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0


def test_packaged_launcher_uses_existing_core_and_contains_only_verified_extension(tmp_path):
    from scripts.build_field_extension import build

    path = build(tmp_path / "extension.zip")
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("payload-manifest.json"))
        for name, expected in manifest["files"].items():
            assert hashlib.sha256(z.read(name)).hexdigest() == expected
        assert not any(
            n.endswith(".dll") or n.startswith(("src/labos/", "deployments/")) for n in z.namelist()
        )
        z.extractall(tmp_path / "extracted")
    output = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "extracted/launch_field.py"),
            "--labos-root",
            str(ROOT),
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "PYTHONPATH": ""},
    )
    assert output.returncode == 0, output.stderr
    assert "preflight" in output.stdout and "deliver" in output.stdout


def test_central_acceptance_refuses_missing_raw_sdk_and_wrong_original_task():
    result, _, _ = run()
    with pytest.raises(ValueError, match="raw|SDK"):
        validate_campaign(result, require_raw=True)
    other = default_task("wrong-task")
    with pytest.raises(ValueError, match="task"):
        validate_campaign(result, expected_task=other)


def test_preflight_sends_full_evidence_without_requiring_unqueued_task_reference(
    tmp_path, monkeypatch
):
    import labos_field.__main__ as cli
    from labos_field.models import LocalConfig
    from labos_field.channel import Channel
    from labos_field.records import digest
    from labos.config import AgentConfig

    config = LocalConfig(
        task_id="field-preflight-test",
        message_id="msg_not_queued_yet",
        message_sha256="a" * 64,
        connection_config=tmp_path / "agent.yaml",
        optical_profile=tmp_path / "optical.yaml",
        optical_profile_sha256="b" * 64,
        state_dir=tmp_path / "state",
        magnetic_source_dir=tmp_path / "source",
        dll_path=tmp_path / "vendor.dll",
        magnetic_lease_profiles=[tmp_path / "a.toml", tmp_path / "b.toml"],
        temperature_baseline_k=180.0,
    )
    connection = AgentConfig(
        agent_id="cryostat-pc", token="x" * 32, server_url="https://central.invalid", instruments=[]
    )
    received = []

    def network(request):
        message = json.loads(request.content)
        received.append(message)
        assert message["in_reply_to"] is None
        return httpx.Response(
            200, json={"message": {**message, "sha256": digest(message), "sequence": len(received)}}
        )

    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "load_connection", lambda path, model: connection)
    monkeypatch.setattr(
        cli, "Channel", lambda value: Channel(value, transport=httpx.MockTransport(network))
    )
    monkeypatch.setattr(
        cli,
        "preflight",
        lambda value: {"status": "PASSED", "close_error": None, "raw_evidence": ["no-truncation"]},
    )
    assert cli.main(["preflight", "--config", str(tmp_path / "field.yaml"), "--send"]) == 0
    assert reassemble(received)["raw_evidence"] == ["no-truncation"]
    assert received[0]["body"]["task_id"] == "field-preflight-test-pf"
