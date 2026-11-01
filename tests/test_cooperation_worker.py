"""Automation contracts: actual API storage and actual subprocess boundaries."""

import json
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from labos.central import create_app
from labos.config import AgentConfig
from labos.cooperation_worker import Worker, WorkerConfig
from labos.cooperation_models import Answer, Responder


def task(task_id="task_demo"):
    return {
        "protocol": "labos-agent-v1",
        "document_type": "labos_auto_task",
        "task_id": task_id,
        "instruction": "Summarize the supplied connection evidence.",
        "context": {"runtime_check": "passed"},
        "executable": False,
    }


class Reports:
    def respond(self, message, context):
        if message["body"]["document_type"] == "labos_auto_result":
            assert (
                message["original_task"]["instruction"]
                == "Summarize the supplied connection evidence."
            )
        return {
            "backend": "test",
            "answer": Answer(
                status="completed",
                summary="Runtime check passed; devices were not opened.",
                findings=[message["body"]["document_type"]],
                questions=[],
            ).model_dump(),
        }


def connection(tmp_path, central_config, role):
    if role == "central":
        config = central_config
    else:
        config = AgentConfig(
            agent_id="pc-a", token="A" * 40, server_url="http://localhost:8000", instruments=[]
        )
    path = tmp_path / f"{role}.json"
    path.write_text(config.model_dump_json())
    return WorkerConfig(
        role=role,
        agent_id="pc-a",
        connection_config=path,
        state_dir=tmp_path / role,
        backend="local",
        local_url="http://localhost:8000/v1",
        local_model="test",
    )


def bridge(api, drop=None):
    def request(req):
        response = api.request(req.method, str(req.url), content=req.content, headers=req.headers)
        if drop and req.method == "POST" and drop.pop():
            raise httpx.ReadTimeout("response lost after storage")
        return httpx.Response(response.status_code, content=response.content, headers=response.headers)

    return httpx.MockTransport(request)


def send(api, message_id, body, sender="central", reference=None):
    r = api.post(
        "/api/agents/pc-a/messages",
        headers={"Authorization": "Bearer " + ("O" if sender == "central" else "A") * 40},
        json={
            "id": message_id,
            "kind": "reply" if reference else "note",
            "body": body,
            "in_reply_to": reference,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["message"]


def messages(api):
    return api.get(
        "/api/agents/pc-a/messages", headers={"Authorization": "Bearer " + "O" * 40}
    ).json()["messages"]


@pytest.mark.parametrize("special", ["\\", '"'])
@pytest.mark.parametrize("origin", ["source", "generated"])
def test_escaped_credentials_never_reach_model_input_or_uploaded_output(
    tmp_path, central_config, special, origin
):
    credential = "private-" + special + "s" * 40
    central_config.agents["pc-a"].token = credential
    config = connection(tmp_path, central_config, "pc")
    values = json.loads(config.connection_config.read_text())
    values["token"] = credential
    config.connection_config.write_text(json.dumps(values))
    calls = []

    class LeakingModel:
        def respond(self, message, context):
            calls.append(message)
            return {
                "backend": "test",
                "answer": {
                    "status": "completed",
                    "summary": credential,
                    "findings": [],
                    "questions": [],
                },
            }

    body = task()
    if origin == "source":
        root = tmp_path / "approved"
        root.mkdir()
        (root / "guide.md").write_text(credential)
        config.source_roots = {"src": root}
        body["context"]["source_requests"] = [{"root": "src", "path": "guide.md"}]
    with TestClient(create_app(central_config)) as api:
        send(api, "credential_task", body)
        worker = Worker(config, bridge(api), LeakingModel())
        worker.tick()
        if origin == "generated":
            with worker.db() as db:
                db.execute("UPDATE inbox SET retry_at=0")
            worker.tick()
        received = messages(api)
        assert len(received) == 2
        assert received[-1]["body"]["answer"]["status"] in {"needs_input", "failed"}
        assert credential not in str(received)
        assert len(calls) == (0 if origin == "source" else 2)


def test_numeric_credential_in_context_is_rejected_before_inference(tmp_path, central_config):
    credential = "7" * 40
    config = connection(tmp_path, central_config, "pc")
    values = json.loads(config.connection_config.read_text())
    values["token"] = credential
    config.connection_config.write_text(json.dumps(values))
    body = task()
    body["context"]["value"] = int(credential)
    envelope = {
        "id": "numeric_secret",
        "agent_id": "pc-a",
        "sequence": 1,
        "sender": "central",
        "kind": "note",
        "body": body,
    }

    class MustNotInfer:
        def respond(self, *args):
            raise AssertionError("Credential-bearing input reached the model")

    def transport(request):
        assert request.method == "GET"
        return httpx.Response(200, json={"messages": [envelope], "next_cursor": 1})

    worker = Worker(config, httpx.MockTransport(transport), MustNotInfer())
    worker.tick()
    assert worker.status()["counts"] == {"rejected": 1}


def test_task_result_review_terminates_without_hardware_or_manual_relay(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        send(api, "task_message", task())
        pc = Worker(connection(tmp_path, central_config, "pc"), bridge(api), Reports())
        central = Worker(connection(tmp_path, central_config, "central"), bridge(api), Reports())
        pc.tick()
        central.tick()
        pc.tick()
        central.tick()
        received = messages(api)
        assert [m["body"]["document_type"] for m in received] == [
            "labos_auto_task",
            "labos_auto_result",
            "labos_auto_review",
        ]
        assert received[1]["in_reply_to"] == "task_message"
        assert received[2]["in_reply_to"] == received[1]["id"]
        assert received[1]["body"]["task_id"] == "task_demo"
        assert received[2]["body"]["answer"]["status"] == "completed"
        status = api.get("/api/status", headers={"Authorization": "Bearer " + "O" * 40}).json()
        assert not status["runs"]
        assert all(not a["online"] for a in status["agents"])


def test_restart_after_lost_send_response_uses_cached_output(tmp_path, central_config, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("labos.cooperation_worker.time.time", lambda: clock[0])

    class MustNotInvoke:
        def respond(self, *args):
            raise AssertionError("a cached response was regenerated")

    with TestClient(create_app(central_config)) as api:
        send(api, "task_message", task())
        config = connection(tmp_path, central_config, "pc")
        worker = Worker(config, bridge(api, [True]), Reports())
        worker.tick()
        assert len(messages(api)) == 2
        restarted = Worker(config, bridge(api), MustNotInvoke())
        clock[0] += 11
        restarted.tick()
        restarted.tick()
        assert len(messages(api)) == 2
        assert restarted.status()["counts"]["sent"] == 1


def test_ordinary_messages_and_unmatched_results_do_not_invoke_model(tmp_path, central_config):
    class MustNotInvoke:
        def respond(self, *args):
            raise AssertionError("ordinary correspondence invoked a model")

    with TestClient(create_app(central_config)) as api:
        send(api, "ordinary", {"content": "Thank you"})
        send(
            api,
            "wrong_result",
            {
                "protocol": "labos-agent-v1",
                "document_type": "labos_auto_result",
                "task_id": "task_demo",
            },
            "pc",
            "ordinary",
        )
        Worker(connection(tmp_path, central_config, "pc"), bridge(api), MustNotInvoke()).tick()
        Worker(connection(tmp_path, central_config, "central"), bridge(api), MustNotInvoke()).tick()
        assert len(messages(api)) == 2


def test_invalid_task_does_not_block_next_valid_task(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        send(api, "bad_task", {**task(), "instruction": ""})
        send(api, "good_task", task("task_second"))
        worker = Worker(connection(tmp_path, central_config, "pc"), bridge(api), Reports())
        worker.tick()
        worker.tick()
        assert messages(api)[-1]["body"]["task_id"] == "task_second"
        assert worker.status()["counts"]["rejected"] == 1


def test_backend_failure_has_bounded_retries_and_returns_failure(
    tmp_path, central_config, monkeypatch
):
    class Unavailable:
        def respond(self, *args):
            raise RuntimeError("quota error containing sensitive provider diagnostics")

    clock = [1000.0]
    monkeypatch.setattr("labos.cooperation_worker.time.time", lambda: clock[0])
    with TestClient(create_app(central_config)) as api:
        send(api, "task_message", task())
        worker = Worker(connection(tmp_path, central_config, "pc"), bridge(api), Unavailable())
        worker.tick()
        worker.tick()
        assert len(messages(api)) == 1
        clock[0] += 61
        worker.tick()
        assert messages(api)[-1]["body"]["answer"]["status"] == "failed"
        assert "sensitive provider" not in json.dumps(messages(api))
        worker.tick()
        assert len(messages(api)) == 2


def test_context_must_not_contain_connection_credentials(tmp_path, central_config):
    import pytest

    config = connection(tmp_path, central_config, "central")
    secret_file = tmp_path / "context.md"
    secret_file.write_text("Do not forward this: " + "O" * 40)
    config.context_files = [secret_file]
    with pytest.raises(ValueError, match="credential"):
        Worker(config)


def test_codex_provider_uses_stdin_and_disables_execution_tools(tmp_path):
    script = tmp_path / "fake codex.py"
    script.write_text("""import json, pathlib, sys
args=sys.argv[1:]
data=json.loads(sys.stdin.read())
assert data["message"]["body"]["instruction"].endswith("$(ignored)")
assert "--ignore-user-config" in args
assert args[args.index("--sandbox")+1] == "read-only"
for feature in ("shell_tool", "unified_exec", "multi_agent", "apps", "plugins", "hooks"):
 assert feature in [args[i+1] for i,x in enumerate(args[:-1]) if x=="--disable"]
pathlib.Path(args[args.index("-o")+1]).write_text(json.dumps({"status":"completed","summary":"Static review only.","findings":[],"questions":[]}))
""")
    config = WorkerConfig(
        role="pc",
        agent_id="pc-a",
        connection_config=tmp_path / "unused",
        state_dir=tmp_path / "state with spaces",
        codex_command=[sys.executable, str(script)],
    )
    message = {"body": {**task(), "instruction": "Review $(ignored)"}}
    result = Responder(config).respond(message, "Static context")
    assert result["answer"]["summary"] == "Static review only."
    assert result["backend"] == "codex"


def test_codex_failure_falls_back_to_loopback_model(tmp_path):
    script = tmp_path / "unavailable.py"
    script.write_text('import sys; print("private diagnostics",file=sys.stderr); sys.exit(1)')
    config = WorkerConfig(
        role="central",
        agent_id="pc-a",
        connection_config=tmp_path / "unused",
        state_dir=tmp_path / "state",
        codex_command=[sys.executable, str(script)],
        local_url="http://127.0.0.1:8000/v1",
        local_model="server-model",
    )

    def local(request):
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "server-model"
        assert "tools" not in body
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "status": "completed",
                                    "summary": "Local fallback worked.",
                                    "findings": [],
                                    "questions": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    result = Responder(config, httpx.MockTransport(local)).respond({"body": task()}, "")
    assert result["backend"] == "local_fallback"
    assert result["answer"]["summary"] == "Local fallback worked."
    assert "private diagnostics" not in json.dumps(result)


def test_local_model_endpoint_must_be_loopback(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="loopback"):
        WorkerConfig(
            role="pc",
            agent_id="pc-a",
            connection_config=tmp_path / "unused",
            state_dir=tmp_path / "state",
            backend="local",
            local_url="http://100.88.168.125:8000/v1",
            local_model="test",
        )


def test_worker_state_cannot_be_reused_for_another_role(tmp_path, central_config):
    import pytest

    pc = connection(tmp_path, central_config, "pc")
    Worker(pc)
    central = connection(tmp_path, central_config, "central")
    central.state_dir = pc.state_dir
    with pytest.raises(ValueError, match="identity"):
        Worker(central)


def test_result_with_different_task_id_is_archived(tmp_path, central_config):
    class MustNotInvoke:
        def respond(self, *args):
            raise AssertionError("wrong task ID triggered inference")

    with TestClient(create_app(central_config)) as api:
        send(api, "original_task", task("expected_task"))
        send(
            api,
            "wrong_task_result",
            {
                "protocol": "labos-agent-v1",
                "document_type": "labos_auto_result",
                "task_id": "another_task",
                "backend": "codex",
                "model_attempts": 1,
                "executable": False,
                "answer": {
                    "status": "completed",
                    "summary": "Unrelated result.",
                    "findings": [],
                    "questions": [],
                },
            },
            "pc",
            "original_task",
        )
        Worker(connection(tmp_path, central_config, "central"), bridge(api), MustNotInvoke()).tick()
        assert len(messages(api)) == 2


def test_missing_task_ids_cannot_crash_daemon_or_block_later_tasks(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        malformed = task()
        del malformed["task_id"]
        send(api, "malformed_parent", malformed)
        send(
            api,
            "malformed_result",
            {
                "protocol": "labos-agent-v1",
                "document_type": "labos_auto_result",
                "backend": "codex",
                "model_attempts": 1,
                "answer": {
                    "status": "completed",
                    "summary": "Missing identity.",
                    "findings": [],
                    "questions": [],
                },
            },
            "pc",
            "malformed_parent",
        )
        send(api, "good_later_task", task("later_task"), "pc")
        worker = Worker(connection(tmp_path, central_config, "central"), bridge(api), Reports())
        worker.tick()
        worker.tick()
        assert messages(api)[-1]["body"]["task_id"] == "later_task"
        assert worker.status()["counts"]["rejected"] == 1


def test_permanent_reply_rejection_does_not_block_next_task(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        send(api, "first_task", task("conflicted_task"))
        send(api, "second_task", task("next_task"))
        collided = [False]

        def request(req):
            if req.method == "POST" and not collided[0]:
                collided[0] = True
                send(
                    api, json.loads(req.content)["id"], {"content": "Existing conflicting message"}
                )
            response = api.request(
                req.method, str(req.url), content=req.content, headers=req.headers
            )
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        worker = Worker(
            connection(tmp_path, central_config, "pc"), httpx.MockTransport(request), Reports()
        )
        worker.tick()
        worker.tick()
        assert messages(api)[-1]["body"].get("task_id") == "next_task"
        assert worker.status()["counts"]["rejected"] == 1


def test_oversized_model_reply_produces_bounded_failure_report(tmp_path, central_config):
    class LargeReport:
        def respond(self, *args):
            return {
                "backend": "test",
                "answer": Answer(
                    status="completed",
                    summary="Large static report.",
                    findings=["\U0001f52c" * 2000] * 20,
                    questions=[],
                ).model_dump(),
            }

    with TestClient(create_app(central_config)) as api:
        send(api, "task_message", task())
        Worker(connection(tmp_path, central_config, "pc"), bridge(api), LargeReport()).tick()
        assert len(messages(api)) == 2
        assert messages(api)[-1]["body"]["answer"]["status"] == "failed"
        assert len(json.dumps(messages(api)[-1])) < 5000


def test_registered_source_is_supplied_without_execution_and_returned_to_central(
    tmp_path, central_config
):
    class SourceReview:
        def respond(self, message, context):
            assert "def read_power" in message["approved_source_evidence"][0]["content"]
            return Reports().respond(message, context)

    source = tmp_path / "production"
    source.mkdir()
    (source / "meter.py").write_text(
        "raise RuntimeError('do not import')\ndef read_power():\n    return 0.0\n"
    )
    with TestClient(create_app(central_config)) as api:
        body = task()
        body["context"]["source_requests"] = [
            {"root": "production_src", "path": "meter.py", "kind": "read"}
        ]
        send(api, "source_task", body)
        cfg = connection(tmp_path, central_config, "pc")
        cfg.source_roots = {"production_src": source}
        Worker(cfg, bridge(api), SourceReview()).tick()
        reply = messages(api)[-1]
        assert "def read_power" in reply["body"]["source_evidence"][0]["content"]
        Worker(connection(tmp_path, central_config, "central"), bridge(api), Reports()).tick()
        assert messages(api)[-1]["body"]["document_type"] == "labos_auto_review"


def test_missing_source_registration_returns_actionable_report_without_model(
    tmp_path, central_config
):
    class MustNotInvoke:
        def respond(self, *args):
            raise AssertionError("source registration must be checked before inference")

    with TestClient(create_app(central_config)) as api:
        body = task()
        body["context"]["source_requests"] = [
            {"root": "production_src", "path": "meter.py", "kind": "read"}
        ]
        send(api, "source_task", body)
        Worker(connection(tmp_path, central_config, "pc"), bridge(api), MustNotInvoke()).tick()
        reply = messages(api)[-1]["body"]
        assert reply["answer"]["status"] == "needs_input"
        assert "registered" in reply["answer"]["summary"]
        assert reply["model_attempts"] == 0


def pilot_review_fixture(api, *, mutation=None, noncanonical=True):
    from test_pilot_artifacts import auth, fixture_payload, queue
    import hashlib

    plan, payload = fixture_payload()
    payload['report']['note'] = 'Mätning 光'
    queue(api, plan)
    if mutation == 'message':
        payload['message_id'] = 'wrong_message'
    elif mutation == 'task':
        payload['report']['task_id'] = 'wrong_task'
    elif mutation == 'plan':
        payload['report']['plan']['reference_hz'] = 9.0
    elif mutation == 'sample_shape':
        payload['report']['samples'] = [3]
    elif mutation == 'plan_hash':
        payload['plan_sha256'] = '0' * 64
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode() + b'\n' if noncanonical else json.dumps(payload, separators=(',', ':')).encode()
    if mutation == 'malformed_json':
        data = b'{ broken JSON'
    digest = hashlib.sha256(data).hexdigest()
    # Mutated transport evidence bypasses upload only in the binding rejection cases.
    if mutation not in {'message', 'task', 'plan', 'plan_hash', 'reference_shape', 'malformed_json', 'sample_shape'}:
        assert api.post('/api/agents/pc-a/pilot-artifacts', content=data,
                        headers={**auth('A'), 'X-SHA256': digest}).status_code == 200
    send(api, 'physical_result', {
        'protocol': 'labos-agent-v1', 'document_type': 'labos_auto_result',
        'task_id': 'pilot-001', 'executable': False, 'backend': 'pilot', 'model_attempts': 0,
        'answer': {'status': 'completed', 'summary': 'Finite test.', 'findings': [], 'questions': []},
        'pilot_result': {'artifact': [] if mutation == 'reference_shape' else {
            'message_id': 'msg_pilot_001', 'sha256': digest}},
    }, sender='pc', reference='msg_pilot_001')
    return data


@pytest.mark.parametrize('noncanonical', [False, True])
def test_central_verifies_original_artifact_bytes_before_review(tmp_path, central_config, noncanonical):
    reviewed = []

    class Reviewer:
        def respond(self, message, context):
            reviewed.append(message)
            return {'backend': 'test', 'answer': Answer(status='completed', summary='Verified.', findings=[], questions=[]).model_dump()}

    with TestClient(create_app(central_config)) as api:
        data = pilot_review_fixture(api, noncanonical=noncanonical)
        worker = Worker(connection(tmp_path, central_config, 'central'), bridge(api), Reviewer())
        worker.tick()
        assert len(reviewed) == 1
        import hashlib
        assert reviewed[0]['stored_pilot_evidence']['sha256'] == hashlib.sha256(data).hexdigest()
        assert reviewed[0]['original_task']['task_id'] == 'pilot-001'
        assert messages(api)[-1]['body']['model_attempts'] == 1
        worker.tick()
        assert len(reviewed) == 1 and len(messages(api)) == 3


@pytest.mark.parametrize('fault', ['503', 'timeout', '404', 'checksum', 'message', 'task', 'plan', 'plan_hash', 'reference_shape', 'malformed_json', 'sample_shape'])
def test_evidence_failure_spends_no_inference_attempts_and_recovers_without_replay(
    tmp_path, central_config, monkeypatch, fault
):
    calls = []
    clock = [1000.0]
    monkeypatch.setattr('labos.cooperation_worker.time.time', lambda: clock[0])

    class Reviewer:
        def respond(self, message, context):
            calls.append(message)
            return {'backend': 'test', 'answer': Answer(status='completed', summary='Verified.', findings=[], questions=[]).model_dump()}

    with TestClient(create_app(central_config)) as api:
        data = pilot_review_fixture(api, mutation=fault)

        def request(req):
            if '/pilot-artifacts/' in req.url.path:
                if fault == 'timeout':
                    raise httpx.ReadTimeout('temporary evidence failure')
                if fault in {'503', '404'}:
                    return httpx.Response(int(fault))
                # Canonicalization has the same semantic object and a different byte hash.
                content = json.dumps(json.loads(data), sort_keys=True).encode() if fault == 'checksum' else data
                return httpx.Response(200, content=content)
            response = api.request(req.method, str(req.url), content=req.content, headers=req.headers)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        config = connection(tmp_path, central_config, 'central')
        worker = Worker(config, httpx.MockTransport(request), Reviewer())
        for _ in range(2):
            worker.tick()
            clock[0] += 61
        assert calls == []
        with worker.db() as db:
            row = db.execute("SELECT * FROM inbox WHERE id='physical_result'").fetchone()
        assert row['attempts'] == 0 and row['response'] is None
        if fault in {'503', 'timeout'}:
            assert row['state'] == 'pending'
            restarted = Worker(config, bridge(api), Reviewer())
            restarted.tick()
            restarted.tick()
            assert len(calls) == 1
            assert messages(api)[-1]['body']['model_attempts'] == 1
            assert len(messages(api)) == 3
        else:
            assert row['state'] == 'rejected'
            assert 'evidence' in row['error']
            assert len(messages(api)) == 2


def page_message(sequence=1, **changes):
    return {"id": f"message_{sequence}", "agent_id": "pc-a", "sender": "central",
            "sequence": sequence, "kind": "note", "in_reply_to": None,
            "body": {"document_type": "ordinary"}, **changes}


@pytest.mark.parametrize("bad", [
    "<html>upstream failure</html>", {}, {"messages": {}, "next_cursor": 0},
    {"messages": [], "next_cursor": 1}, {"messages": [], "next_cursor": -1},
    {"messages": [], "next_cursor": 2**63},
    {"messages": [page_message()], "next_cursor": 0},
    {"messages": [page_message(agent_id="other")], "next_cursor": 1},
    {"messages": [page_message(sender="pc")], "next_cursor": 1},
    {"messages": [page_message(sequence=True)], "next_cursor": 1},
    {"messages": [page_message(sequence=2**63)], "next_cursor": 2**63},
    {"messages": [page_message(sequence=0)], "next_cursor": 0},
    {"messages": [page_message(), page_message()], "next_cursor": 1},
    {"messages": [page_message(2), page_message(1)], "next_cursor": 1},
    {"messages": [page_message(), {"id": "broken"}], "next_cursor": 2},
    {"messages": [page_message(i) for i in range(1, 102)], "next_cursor": 101},
])
def test_entire_invalid_page_is_atomic_and_next_tick_recovers(tmp_path, central_config, bad):
    responses = [bad, {"messages": [page_message()], "next_cursor": 1}]
    def transport(request):
        assert request.method == "GET"
        payload = responses.pop(0)
        return (httpx.Response(200, text=payload) if isinstance(payload, str)
                else httpx.Response(200, json=payload))
    worker = Worker(connection(tmp_path, central_config, "pc"), httpx.MockTransport(transport), Reports())
    assert worker.tick()["phase"] == "protocol_unavailable"
    with worker.db() as db:
        assert db.execute("SELECT value FROM state WHERE key='cursor'").fetchone()[0] == "0"
        assert db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM backend_invocations").fetchone()[0] == 0
    worker.tick()
    assert worker.status()["counts"] == {"archived": 1}


def test_parent_lookup_resumes_after_restart_with_two_pages_per_tick(tmp_path, central_config):
    config = connection(tmp_path, central_config, "central")
    requested = []
    parent = page_message(501, id="old_parent", body=task())
    result = page_message(502, id="result", sender="pc", kind="reply", in_reply_to="old_parent",
                          body={"protocol": "labos-agent-v1", "document_type": "labos_auto_result",
                                "task_id": "task_demo", "backend": "test", "model_attempts": 0,
                                "answer": {"status": "completed", "summary": "done", "findings": [], "questions": []}})
    posts = []
    def transport(request):
        if request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(200, json={})
        after = int(request.url.params["after"])
        if request.url.params["sender"] == "pc":
            return httpx.Response(200, json={"messages": [result] if after == 0 else [],
                                           "next_cursor": 502})
        requested.append(after)
        batch = ([page_message(i) for i in range(after + 1, after + 101)]
                 if after < 500 else [parent] if after == 500 else [])
        return httpx.Response(200, json={"messages": batch,
                                       "next_cursor": batch[-1]["sequence"] if batch else after})
    worker = Worker(config, httpx.MockTransport(transport), Reports())
    worker.tick()
    assert requested == [0, 100]
    assert worker.status()["counts"] == {"pending": 1}
    worker.client.close()
    worker = Worker(config, httpx.MockTransport(transport), Reports())
    worker.tick()
    assert requested == [0, 100, 200, 300]
    with worker.db() as db:
        assert db.execute("SELECT COUNT(*) FROM backend_invocations").fetchone()[0] == 0
    worker.tick()
    assert requested == [0, 100, 200, 300, 400, 500]
    assert len(posts) == 1
    assert worker.status()["counts"] == {"sent": 1}
    assert worker.find_own_message("message_1")["sequence"] == 1
    assert len(requested) == 6


@pytest.mark.parametrize("field,value", [("kind", []), ("id", "bad.id"), ("body", []),
                                         ("agent_id", None), ("sequence", 1.5)])
def test_invalid_envelope_field_is_protocol_unavailable(tmp_path, central_config, field, value):
    worker = Worker(connection(tmp_path, central_config, "pc"),
                    httpx.MockTransport(lambda _: httpx.Response(200, json={
                        "messages": [page_message(**{field: value})], "next_cursor": 1})), Reports())
    assert worker.tick()["phase"] == "protocol_unavailable"
    assert worker.status()["cursor"] == 0


def test_parent_scan_stop_preserves_progress_without_model_spend(tmp_path, central_config, monkeypatch):
    from labos.cooperation_budget import Operation, OperationStopped
    config = connection(tmp_path, central_config, "central")
    stopped = [False]
    requests = []
    def transport(request):
        after = int(request.url.params["after"])
        requests.append(after)
        stopped[0] = after == 100
        return httpx.Response(200, json={"messages": [page_message(i) for i in range(after + 1, after + 101)],
                                       "next_cursor": after + 100})
    worker = Worker(config, httpx.MockTransport(transport), Reports())
    operation = Operation(180, stopped=lambda: stopped[0])
    with pytest.raises(OperationStopped):
        worker.find_own_message("unseen", operation.check)
    with worker.db() as db:
        assert db.execute("SELECT value FROM state WHERE key='own_cursor'").fetchone()[0] == "100"
        assert db.execute("SELECT COUNT(*) FROM own_messages").fetchone()[0] == 100
        assert db.execute("SELECT COUNT(*) FROM backend_invocations").fetchone()[0] == 0
    assert requests == [0, 100]


def test_parent_nonprogress_page_preserves_cache_and_can_recover(tmp_path, central_config):
    config = connection(tmp_path, central_config, "central")
    from labos.correspondence_page import ProtocolUnavailable
    pages = [{"messages": [page_message()], "next_cursor": 1},
             {"messages": [page_message()], "next_cursor": 1},
             {"messages": [], "next_cursor": 1}]
    worker = Worker(config, httpx.MockTransport(lambda _: httpx.Response(200, json=pages.pop(0))), Reports())
    with pytest.raises(ProtocolUnavailable):
        worker.find_own_message("missing")
    assert worker.find_own_message("message_1")["sequence"] == 1
    assert worker.find_own_message("missing") is None
    assert not pages


def test_source_preparation_observes_same_operation_before_provider(tmp_path, central_config, monkeypatch):
    from labos.cooperation_budget import Operation
    clock = [0.0]
    operation = Operation(180, clock=lambda: clock[0])
    (tmp_path / "guide.md").write_text("evidence")
    config = connection(tmp_path, central_config, "pc")
    config.source_roots = {"src": tmp_path}
    body = task()
    body["context"]["source_requests"] = [{"root": "src", "path": "guide.md"}]
    with TestClient(create_app(central_config)) as api:
        send(api, "source_deadline", body)
        worker = Worker(config, bridge(api), Reports())
        monkeypatch.setattr(worker, "new_operation", lambda: operation)
        resolve = worker.sources.resolve
        def slow_resolve(request):
            clock[0] = 181
            return resolve(request)
        monkeypatch.setattr(worker.sources, "resolve", slow_resolve)
        worker.tick()
        reply = messages(api)[-1]["body"]
        assert reply["model_attempts"] == 0
        assert reply["answer"]["status"] == "failed"


def test_invalid_page_preserves_existing_pending_job_and_nonzero_cursor(tmp_path, central_config):
    config = connection(tmp_path, central_config, "pc")
    config.start_after = 5
    responses = [{"messages": [page_message(4)], "next_cursor": 4},
                 {"messages": [], "next_cursor": 5}]
    worker = Worker(config, httpx.MockTransport(lambda _: httpx.Response(200, json=responses.pop(0))), Reports())
    with worker.db() as db:
        db.execute("INSERT INTO inbox(id,sequence,envelope,state) VALUES(?,?,?,'pending')",
                   ("queued", 5, json.dumps(page_message(5, id="queued"))))
    assert worker.tick()["phase"] == "protocol_unavailable"
    assert worker.status()["cursor"] == 5
    assert worker.status()["counts"] == {"pending": 1}
    with worker.db() as db:
        assert db.execute("SELECT COUNT(*) FROM backend_invocations").fetchone()[0] == 0
    worker.tick()
    assert worker.status()["counts"] == {"archived": 1}


def test_malformed_parent_page_leaves_review_pending_then_recovers(tmp_path, central_config):
    with TestClient(create_app(central_config)) as api:
        send(api, "parent", task())
        pc = Worker(connection(tmp_path, central_config, "pc"), bridge(api), Reports())
        pc.tick()
        bad = [True]
        def transport(request):
            if request.method == "GET" and request.url.params.get("sender") == "central" and bad:
                bad.pop()
                return httpx.Response(200, text="<html>unavailable</html>")
            response = api.request(request.method, str(request.url), content=request.content, headers=request.headers)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        worker = Worker(connection(tmp_path, central_config, "central"), httpx.MockTransport(transport), Reports())
        assert worker.tick()["phase"] == "protocol_unavailable"
        assert worker.status()["counts"] == {"pending": 1}
        with worker.db() as db:
            assert db.execute("SELECT COUNT(*) FROM backend_invocations").fetchone()[0] == 0
            assert db.execute("SELECT value FROM state WHERE key='own_cursor'").fetchone()[0] == "0"
        worker.tick()
        assert worker.status()["counts"] == {"sent": 1}
        assert messages(api)[-1]["body"]["document_type"] == "labos_auto_review"
