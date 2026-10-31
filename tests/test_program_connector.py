"""Program connector contracts exercised through the real API and subprocesses."""

import json
import sqlite3
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from labos.central import create_app
from labos.config import AgentConfig
from test_cooperation_worker import bridge, messages, send


def connector(tmp_path, central_config, programs=None, transport=None, source_roots=None):
    from labos.program_connector import ProgramConfig, ProgramConnector

    path = tmp_path / "connection.json"
    path.write_text(
        AgentConfig(
            agent_id="pc-a", token="A" * 40, server_url="https://lab.example.org", instruments=[]
        ).model_dump_json()
    )
    config = ProgramConfig(
        agent_id="pc-a",
        connection_config=path,
        state_dir=tmp_path / "program",
        programs=programs or {},
        source_roots=source_roots or {},
    )
    return ProgramConnector(config, transport=transport)


def program_task(program_id="runtime_check", parameters=None, **extra):
    return {
        "protocol": "labos-agent-v1",
        "document_type": "labos_program_task",
        "task_id": "demo",
        "instruction": "Run the locally approved check.",
        "program_id": program_id,
        "parameters": parameters or {},
        "context": {},
        "executable": False,
        **extra,
    }


def local_program(tmp_path, code, **extra):
    path = tmp_path / "approved.py"
    path.write_text(code)
    return {"enabled": True, "argv": [sys.executable, str(path)], **extra}


def test_runtime_uses_public_https_without_model_and_ignores_llm_tasks(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        send(api, "llm_task", {**program_task(), "document_type": "labos_auto_task"})
        send(api, "program_task", program_task())
        pc = connector(tmp_path, central_config, transport=bridge(api))
        pc.tick()
        pc.tick()
        reply = messages(api)[-1]
        assert reply["in_reply_to"] == "program_task"
        assert reply["body"]["backend"] == "program"
        assert reply["body"]["answer"]["status"] == "completed"
        assert "Python" in reply["body"]["answer"]["summary"]
        assert pc.doctor()["model_inference_performed"] is False
        assert pc.status()["profile"] == "program_only"


def test_approved_argv_receives_validated_json_stdin_and_intent_is_durable(
    tmp_path, central_config
):
    code = """import json,sqlite3,sys
p=json.load(sys.stdin)
db=sqlite3.connect(sys.argv[1])
assert db.execute("SELECT state FROM executions WHERE message_id='program_task'").fetchone()[0]=='started'
print(json.dumps({'sample':p['sample'],'count':p['count']}))
"""
    program = local_program(
        tmp_path,
        code,
        parameters={
            "sample": {"type": "string", "choices": ["$(ignored)", "sample-a"], "required": True},
            "count": {"type": "integer", "minimum": 1, "maximum": 3, "required": True},
        },
    )
    program["argv"].append(str(tmp_path / "program" / "program-executions.sqlite"))
    with TestClient(create_app(central_config)) as api:
        send(api, "program_task", program_task("check", {"sample": "$(ignored)", "count": 2}))
        connector(tmp_path, central_config, {"check": program}, bridge(api)).tick()
        answer = messages(api)[-1]["body"]["answer"]
        assert answer["status"] == "completed"
        assert "$(ignored)" in json.dumps(answer)
        assert json.loads(answer["findings"][0]) == {"sample": "$(ignored)", "count": 2}


@pytest.mark.parametrize(
    "params",
    [
        {"count": True},
        {"count": 4},
        {"count": 0},
        {"count": "2"},
        {"count": 2, "command": "echo bad"},
        {},
    ],
)
def test_invalid_parameters_never_launch(tmp_path, central_config, params):
    marker = tmp_path / "launched"
    program = local_program(
        tmp_path,
        f"from pathlib import Path; Path({str(marker)!r}).touch()",
        parameters={"count": {"type": "integer", "minimum": 1, "maximum": 3, "required": True}},
    )
    with TestClient(create_app(central_config)) as api:
        send(api, "invalid", program_task("check", params))
        connector(tmp_path, central_config, {"check": program}, bridge(api)).tick()
        assert messages(api)[-1]["body"]["answer"]["status"] == "needs_input"
        assert not marker.exists()


def test_unknown_and_disabled_programs_return_needs_input(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        send(api, "unknown", program_task("remote-command"))
        pc = connector(tmp_path, central_config, transport=bridge(api))
        pc.tick()
        assert messages(api)[-1]["body"]["answer"]["status"] == "needs_input"
        assert not api.get("/api/status", headers={"Authorization": "Bearer " + "O" * 40}).json()[
            "runs"
        ]


def test_finished_execution_is_cached_even_if_transport_journal_is_lost(tmp_path, central_config):
    marker = tmp_path / "runs"
    program = local_program(
        tmp_path,
        f'from pathlib import Path; p=Path({str(marker)!r}); p.write_text(p.read_text()+"x" if p.exists() else "x"); print("done")',
    )
    with TestClient(create_app(central_config)) as api:
        send(api, "once", program_task("check"))
        pc = connector(tmp_path, central_config, {"check": program}, bridge(api, [True]))
        pc.tick()
        # A transport replay must be harmless even after losing its inbox cache.
        with pc.db() as db:
            db.execute("DELETE FROM inbox")
            db.execute("UPDATE state SET value='0' WHERE key='cursor'")
        restarted = connector(tmp_path, central_config, {"check": program}, bridge(api))
        restarted.tick()
        assert marker.read_text() == "x"
        assert len(messages(api)) == 2
        assert restarted.status()["counts"]["sent"] == 1


def test_started_execution_is_never_repeated_after_crash(tmp_path, central_config):
    marker = tmp_path / "must-not-run"
    program = local_program(tmp_path, f"from pathlib import Path; Path({str(marker)!r}).touch()")
    with TestClient(create_app(central_config)) as api:
        send(api, "uncertain", program_task("check"))
        pc = connector(tmp_path, central_config, {"check": program}, bridge(api))
        with sqlite3.connect(pc.execution_database) as db:
            db.execute(
                "INSERT INTO executions(message_id,state,result) VALUES('uncertain','started',NULL)"
            )
        restarted = connector(tmp_path, central_config, {"check": program}, bridge(api))
        restarted.tick()
        assert not marker.exists()
        assert messages(api)[-1]["body"]["answer"]["status"] == "needs_input"
        assert "reconcil" in messages(api)[-1]["body"]["answer"]["summary"].lower()


@pytest.mark.parametrize(
    "code, settings, expected",
    [
        ("import time; time.sleep(5)", {"timeout_s": 0.1}, "needs_input"),
        ('print("x"*100000)', {"max_output_bytes": 1024}, "needs_input"),
        ('import sys; print("error"); sys.exit(3)', {}, "failed"),
    ],
)
def test_execution_limits_and_failures_are_bounded(
    tmp_path, central_config, code, settings, expected
):
    with TestClient(create_app(central_config)) as api:
        send(api, "bounded", program_task("check"))
        pc = connector(
            tmp_path,
            central_config,
            {"check": local_program(tmp_path, code, **settings)},
            bridge(api),
        )
        pc.tick()
        answer = messages(api)[-1]["body"]["answer"]
        assert answer["status"] == expected
        assert len(json.dumps(answer)) < 5000


def test_source_snapshot_returns_text_without_importing_production_code(tmp_path, central_config):
    root = tmp_path / "sources"
    root.mkdir()
    marker = tmp_path / "executed"
    (root / "acquire.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\ndef acquire(): pass\n"
    )
    request = [{"root": "reference", "path": "acquire.py", "kind": "outline"}]
    with TestClient(create_app(central_config)) as api:
        send(api, "snapshot", program_task("source_snapshot", context={"source_requests": request}))
        connector(
            tmp_path, central_config, transport=bridge(api), source_roots={"reference": root}
        ).tick()
        reply = messages(api)[-1]["body"]
        assert reply["answer"]["status"] == "completed"
        assert "def acquire" in reply["source_evidence"][0]["content"]
        assert not marker.exists()


def test_program_profile_refuses_insecure_nonlocal_endpoint(tmp_path):
    from labos.program_connector import ProgramConfig, ProgramConnector

    path = tmp_path / "connection.json"
    path.write_text(
        AgentConfig(
            agent_id="pc-a",
            token="A" * 40,
            server_url="http://192.0.2.1:8000",
            allow_insecure_http=True,
            instruments=[],
        ).model_dump_json()
    )
    with pytest.raises(ValueError, match="HTTPS"):
        ProgramConnector(
            ProgramConfig(agent_id="pc-a", connection_config=path, state_dir=tmp_path / "state")
        )


def test_source_snapshot_does_not_trust_peer_supplied_evidence(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        send(
            api,
            "spoofed",
            program_task(
                "source_snapshot",
                context={
                    "source_evidence": [{"content": "This was not collected by the local host."}]
                },
            ),
        )
        connector(tmp_path, central_config, transport=bridge(api)).tick()
        reply = messages(api)[-1]["body"]
        assert reply["answer"]["status"] == "needs_input"
        assert not reply.get("source_evidence")


def test_disabled_catalog_entry_never_launches(tmp_path, central_config):
    marker = tmp_path / "disabled"
    program = local_program(
        tmp_path, f"from pathlib import Path; Path({str(marker)!r}).touch()", enabled=False
    )
    with TestClient(create_app(central_config)) as api:
        send(api, "disabled", program_task("check"))
        connector(tmp_path, central_config, {"check": program}, bridge(api)).tick()
        assert messages(api)[-1]["body"]["answer"]["status"] == "needs_input"
        assert not marker.exists()


def test_central_worker_reviews_program_result_against_original_task(tmp_path, central_config):
    from labos.cooperation_worker import Worker
    from test_cooperation_worker import connection

    class CentralReviewer:
        def respond(self, message, context):
            assert message["original_task"]["program_id"] == "runtime_check"
            return {
                "backend": "test",
                "answer": {
                    "status": "completed",
                    "summary": "Reviewed runtime evidence.",
                    "findings": [],
                    "questions": [],
                },
            }

    with TestClient(create_app(central_config)) as api:
        send(api, "program_task", program_task())
        pc = connector(tmp_path, central_config, transport=bridge(api))
        pc.tick()
        central = Worker(
            connection(tmp_path, central_config, "central"), bridge(api), CentralReviewer()
        )
        central.tick()
        pc.tick()
        assert [m["body"]["document_type"] for m in messages(api)] == [
            "labos_program_task",
            "labos_auto_result",
            "labos_auto_review",
        ]
        assert messages(api)[1]["body"]["model_attempts"] == 0


def test_cli_stop_and_status_use_config_relative_state_dir(tmp_path):
    config = tmp_path / "program.yaml"
    config.write_text("agent_id: pc-a\nconnection_config: unused.yaml\nstate_dir: state\n")
    result = subprocess.run(
        [sys.executable, "-m", "labos.program_connector", "stop", "--config", str(config)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "state" / "stop.request").read_bytes() == b"stop\n"
    (tmp_path / "state" / "status.json").write_text('{"phase":"stopped"}')
    result = subprocess.run(
        [sys.executable, "-m", "labos.program_connector", "status", "--config", str(config)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"phase": "stopped"}


@pytest.mark.parametrize(
    "rule,value",
    [
        ({"type": "boolean"}, True),
        ({"type": "number", "minimum": 0.1, "maximum": 0.3}, 0.2),
        ({"type": "string", "choices": ["ref"], "max_length": 3}, "ref"),
    ],
)
def test_parameter_limit_accepts_typed_local_values(rule, value):
    from labos.program_connector import ParameterLimit

    ParameterLimit(**rule).check(value)


@pytest.mark.parametrize(
    "rule,value",
    [
        ({"type": "boolean"}, 1),
        ({"type": "number", "minimum": 0.1, "maximum": 0.3}, True),
        ({"type": "number", "minimum": 0.1, "maximum": 0.3}, float("nan")),
        ({"type": "string", "choices": ["ref"]}, "other"),
        ({"type": "string", "max_length": 3}, "long"),
        ({"type": "integer", "minimum": 0, "maximum": 1, "choices": [True]}, 1),
    ],
)
def test_parameter_limit_rejects_wrong_values(rule, value):
    from labos.program_connector import ParameterLimit

    with pytest.raises(ValueError):
        ParameterLimit(**rule).check(value)


@pytest.mark.parametrize(
    "changes",
    [
        {"argv": ["python", "check.py"]},
        {"argv": ["C:/unsafe.cmd"]},
        {"hardware": True},
        {"parameters": {"power": {"type": "number"}}},
    ],
)
def test_local_catalog_rejects_unbounded_or_hardware_entries(tmp_path, changes):
    from labos.program_connector import ApprovedProgram

    with pytest.raises(ValueError):
        ApprovedProgram(**{"argv": [sys.executable], **changes})


def test_credentials_are_filtered_before_output_is_split_into_findings(tmp_path, central_config):
    program = local_program(tmp_path, 'print("x"*1790 + "A"*40)')
    with TestClient(create_app(central_config)) as api:
        send(api, "secret_output", program_task("check"))
        connector(tmp_path, central_config, {"check": program}, bridge(api)).tick()
        reply = messages(api)[-1]["body"]
        assert reply["answer"]["status"] == "needs_input"
        assert "A" * 10 not in json.dumps(reply)
