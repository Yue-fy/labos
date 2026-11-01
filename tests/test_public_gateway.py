"""Exercise the public boundary against the real central application."""
from contextlib import contextmanager
import argparse
import importlib
import json
import subprocess
import sys

from fastapi.testclient import TestClient
import httpx
import pytest

from labos.central import create_app as central_app
from labos.cooperation import add_parser, run


def auth(token):
    return {"Authorization": ("Bearer " + token).encode("utf-8")}


@contextmanager
def gateway(config):
    module = importlib.import_module("labos.public_gateway")
    central = central_app(config)
    # TestClient owns central's lifespan; ASGITransport exercises its actual routes.
    with TestClient(central) as private:
        app = module.create_app(config, transport=httpx.ASGITransport(app=central))
        with TestClient(app) as public:
            yield public, private, central


def test_health_reports_actual_central_and_no_public_dashboard(central_config):
    with gateway(central_config) as (public, private, _):
        response = public.get("/health")
        assert response.status_code == 200
        assert response.json() == private.get("/health").json()
        assert response.json()["service"] == "labos-central"
        for path in ["/", "/docs", "/openapi.json", "/api/status", "/api/evidence",
                     "/api/plan", "/api/runs", "/api/events", "/v1/models"]:
            response = public.get(path, headers=auth("O" * 40))
            assert response.status_code == 404, path
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["Content-Type"].startswith("application/json")


@pytest.mark.parametrize("credential,status", [(None, 401), ("?" * 40, 401),
                         ("O" * 40, 403), ("B" * 40, 403), ("unicode-密", 401)])
@pytest.mark.parametrize("method,endpoint", [("GET", "health"), ("GET", "messages"),
                         ("POST", "messages"), ("POST", "register"),
                         ("POST", "heartbeat"), ("POST", "poll"),
                         ("POST", "results"), ("POST", "artifacts"),
                         ("POST", "pilot-artifacts"),
                         ("GET", "pilot-claims"), ("POST", "pilot-claims"),
                         ("POST", "disconnect")])
def test_every_pc_endpoint_requires_its_own_credential(central_config, credential, status,
                                                     method, endpoint):
    with gateway(central_config) as (public, _, _):
        response = public.request(method, f"/api/agents/pc-a/{endpoint}",
                                  headers=auth(credential) if credential else {}, json={})
        assert response.status_code == status
        assert response.headers["Cache-Control"] == "no-store"
        assert not credential or credential not in response.text


def test_unknown_pc_duplicate_auth_and_exact_method_allowlist(central_config):
    with gateway(central_config) as (public, _, _):
        assert public.get("/api/agents/unknown/health", headers=auth("A" * 40)).status_code == 403
        assert public.get("/api/agents/pc-a/health", headers=[
            ("Authorization", "Bearer " + "A" * 40),
            ("Authorization", "Bearer " + "O" * 40)]).status_code == 401
        for method, path in [("POST", "/health"), ("HEAD", "/health"),
                             ("POST", "/api/agents/pc-a/health"),
                             ("GET", "/api/agents/pc-a/register"),
                             ("DELETE", "/api/agents/pc-a/messages"),
                             ("OPTIONS", "/api/agents/pc-a/messages")]:
            response = public.request(method, path, headers=auth("A" * 40))
            assert response.status_code == 405, (method, path)
        for path in ["/api/agents/pc-a/messages/", "/api/agents/pc-a/status",
                     "/api/agents/pc-a/messages/extra", "/api/agents/pc-a%2Fpc-b/health"]:
            assert public.get(path, headers=auth("A" * 40)).status_code == 404


def test_send_pull_and_cursor_preservation_use_actual_correspondence(central_config):
    path = "/api/agents/pc-a/messages"
    with gateway(central_config) as (public, private, central):
        report = public.post(path, headers=auth("A" * 40), json={
            "id": "report1", "kind": "report", "body": {"executable": False}})
        assert report.status_code == 200, report.text
        assert report.json()["message"]["sender"] == "pc"
        cursor = report.json()["message"]["sequence"]
        reply = private.post(path, headers=auth("O" * 40), json={
            "id": "reply1", "kind": "reply", "in_reply_to": "report1",
            "body": {"next_step": "network checks"}})
        assert reply.status_code == 200
        received = public.get(path + f"?after={cursor}&sender=central&limit=1",
                              headers=auth("A" * 40)).json()
        assert [m["id"] for m in received["messages"]] == ["reply1"]
        assert not public.get(path + f"?after={received['next_cursor']}",
                              headers=auth("A" * 40)).json()["messages"]
        with central.state.store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0


def test_registration_heartbeat_poll_artifact_and_disconnect_reach_central(central_config):
    with gateway(central_config) as (public, _, _):
        headers = auth("A" * 40)
        base = "/api/agents/pc-a/"
        assert public.get(base + "health", headers=headers).json()["instrument_ids"] == ["superk_01"]
        assert public.post(base + "register", headers=headers, json={"boot_id": "boot1"}).json()["registered"]
        assert public.post(base + "heartbeat", headers=headers,
                           json={"boot_id": "boot1", "instruments": {}}).status_code == 200
        assert public.post(base + "poll", headers=headers,
                           json={"boot_id": "boot1"}).json() == {"command": None}
        # An unknown command reaches central's actual session/command validation.
        result = public.post(base + "results", headers=headers, json={
            "boot_id": "boot1", "command_id": "missing", "state": "COMPLETED", "result": {}})
        assert result.status_code == 409
        result = public.post(base + "artifacts", content=b"invalid artifact", headers={
            **headers, "X-Boot-Id": "boot1", "X-Sha256": "0" * 64})
        assert result.status_code == 400
        assert public.post(base + "disconnect", headers=headers,
                           json={"boot_id": "boot1"}).json()["disconnected"]


def test_pc_cooperate_cli_sends_and_pulls_through_gateway(central_config, tmp_path, capsys):
    path = tmp_path / "pc.yaml"
    path.write_text(json.dumps({"agent_id": "pc-a", "token": "A" * 40,
                               "instruments": [], "server_url": "https://public.example:8443"}))
    source = tmp_path / "report.json"
    source.write_text('{"executable":false,"report_id":"public-pc-intake"}')
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    with gateway(central_config) as (public, private, _):
        def bridge(request):
            response = public.request(request.method, request.url.raw_path.decode(),
                                      headers=request.headers, content=request.content)
            return httpx.Response(response.status_code, content=response.content,
                                  headers=response.headers)
        transport = httpx.MockTransport(bridge)
        send = parser.parse_args(["cooperate", "send", "--role", "pc", "--config", str(path),
                                  "--input", str(source), "--message-id", "cli_report"])
        assert run(send, transport=transport) == 0
        assert private.post("/api/agents/pc-a/messages", headers=auth("O" * 40), json={
            "id": "cli_reply", "kind": "reply", "in_reply_to": "cli_report",
            "body": {"next_step": "read-only checks"}}).status_code == 200
        output = tmp_path / "reply.json"
        pull = parser.parse_args(["cooperate", "pull", "--role", "pc", "--config", str(path),
                                  "--output", str(output)])
        assert run(pull, transport=transport) == 0
        assert [m["id"] for m in json.loads(output.read_text())["messages"]] == ["cli_reply"]
    printed = capsys.readouterr().out
    assert "A" * 40 not in printed and "O" * 40 not in printed


def test_gateway_module_cli_is_available_without_starting_a_server():
    result = subprocess.run([sys.executable, "-m", "labos.public_gateway", "--help"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert all(option in result.stdout for option in ("--config", "--host", "--port", "--max-inflight"))


@pytest.mark.parametrize("length,status", [("8388609", 413), ("9" * 5000, 413),
                         ("invalid", 400), ("-1", 400), ("+10", 400)])
def test_rejects_oversized_or_malformed_content_length_before_reading(central_config,
                                                                  length, status):
    with gateway(central_config) as (public, _, _):
        result = public.post("/api/agents/pc-a/messages", content=b"{}", headers={
            **auth("A" * 40), "Content-Length": length})
        assert result.status_code == status
        assert result.json()["detail"]


def test_caps_streamed_bodies_and_authenticates_before_size_check(central_config):
    with gateway(central_config) as (public, private, _):
        def oversized():
            for _ in range(9):
                yield b"x" * (1024 * 1024)
        result = public.post("/api/agents/pc-a/messages", content=oversized(),
                             headers=auth("A" * 40))
        assert result.status_code == 413
        assert private.get("/api/agents/pc-a/messages", headers=auth("O" * 40)).json()["messages"] == []
        result = public.post("/api/agents/pc-a/messages", content=b"{}",
                             headers={"Content-Length": "8388609"})
        assert result.status_code == 401


def test_validation_errors_do_not_echo_credentials_or_request_body(central_config, caplog):
    secret = "request-private-marker"
    with gateway(central_config) as (public, _, _):
        result = public.post("/api/agents/pc-a/register", headers=auth("A" * 40),
                             json={"boot_id": {"secret": secret, "token": "O" * 40}})
        assert result.status_code == 422
        assert secret not in result.text and "O" * 40 not in result.text
        assert secret not in caplog.text and "A" * 40 not in caplog.text


def test_fixed_loopback_origin_and_only_required_headers_reach_central(central_config,
                                                                    monkeypatch):
    module = importlib.import_module("labos.public_gateway")
    central_config.host = "untrusted.example"
    central_config.port = 18080
    monkeypatch.setenv("HTTP_PROXY", "http://proxy-user:proxy-secret@127.0.0.1:1")
    central = central_app(central_config)
    observed = []

    @central.middleware("http")
    async def observe(request, call_next):
        observed.append((request.url, dict(request.headers)))
        return await call_next(request)

    with TestClient(central), TestClient(module.create_app(
            central_config, transport=httpx.ASGITransport(app=central))) as public:
        result = public.get("/api/agents/pc-a/messages?after=3&sender=central&limit=1&url=https://evil.example",
                            headers={**auth("A" * 40), "Host": "evil.example",
                                     "Proxy-Authorization": "Basic proxy-secret",
                                     "Cookie": "operator=secret", "X-Forwarded-Host": "evil.example"})
        assert result.status_code == 200
        url, headers = observed[0]
        assert str(url).startswith("http://127.0.0.1:18080/api/agents/pc-a/messages?")
        assert url.query == "after=3&sender=central&limit=1&url=https://evil.example"
        assert "proxy-authorization" not in headers
        assert "cookie" not in headers and "x-forwarded-host" not in headers


def test_upstream_redirect_is_not_followed_or_exposed(central_config):
    module = importlib.import_module("labos.public_gateway")
    requests = []

    async def redirect(request):
        requests.append(request)
        return httpx.Response(307, headers={"Location": "https://outside.example/operator"})

    with TestClient(module.create_app(central_config, transport=httpx.MockTransport(redirect))) as public:
        result = public.get("/api/agents/pc-a/health", headers=auth("A" * 40))
        assert result.status_code == 502
        assert "location" not in result.headers
        assert "outside.example" not in result.text
        assert len(requests) == 1


def test_unreachable_upstream_is_sanitized_and_client_closes(central_config, caplog):
    module = importlib.import_module("labos.public_gateway")

    async def unavailable(request):
        raise httpx.ConnectError("http://proxy-user:proxy-secret@localhost:1", request=request)

    app = module.create_app(central_config, transport=httpx.MockTransport(unavailable))
    with TestClient(app) as public:
        result = public.get("/health")
        assert result.status_code == 503
        assert result.json() == {"detail": "central service unavailable"}
        assert result.headers["Cache-Control"] == "no-store"
        assert "proxy-secret" not in result.text and "proxy-secret" not in caplog.text
        upstream = app.state.upstream
        assert not upstream.is_closed
    assert upstream.is_closed


def test_total_upstream_timeout_is_bounded(central_config, monkeypatch):
    import asyncio
    module = importlib.import_module("labos.public_gateway")
    monkeypatch.setattr(module, "UPSTREAM_TIMEOUT_S", 0.05)

    async def blocked(request):
        await asyncio.Event().wait()

    with TestClient(module.create_app(central_config, transport=httpx.MockTransport(blocked))) as public:
        result = public.get("/health")
        assert result.status_code == 503


def test_cli_invalid_configuration_does_not_print_secrets(tmp_path):
    path = tmp_path / "invalid.yaml"
    path.write_text(json.dumps({"admin_token": "private-secret-short", "agents": {}}))
    result = subprocess.run([sys.executable, "-m", "labos.public_gateway", "--config", str(path)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "private-secret-short" not in result.stdout + result.stderr


def test_pilot_authority_only_exact_claim_routes_reach_central(central_config):
    with gateway(central_config) as (public, _, _):
        path = '/api/agents/pc-a/pilot-claims'
        assert public.get(path, headers=auth('A' * 40)).json()['commissioned'] is False
        assert public.post(path, headers=auth('A' * 40), json={}).status_code == 422
        for method in ('PUT', 'DELETE', 'PATCH', 'HEAD'):
            assert public.request(method, path, headers=auth('A' * 40)).status_code == 405
        for extra in ('/', '/reset', '/commission'):
            assert public.get(path + extra, headers=auth('A' * 40)).status_code == 404
        assert public.post('/api/pilot-authority/pc-a/commission', headers=auth('O' * 40), json={}).status_code == 404


class ChunkStream(httpx.AsyncByteStream):
    """A network boundary double: HTTPX must consume and close real chunks."""

    def __init__(self, chunks, delay=0, failure=None):
        self.chunks = chunks
        self.delay = delay
        self.failure = failure
        self.consumed = 0
        self.closed = False

    async def __aiter__(self):
        import asyncio
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.consumed += 1
            yield chunk
        if self.failure:
            raise self.failure

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("size,status", [(8388607, 200), (8388608, 200), (8388609, 502)])
@pytest.mark.parametrize("length", [None, "1"])
def test_upstream_stream_boundary_is_checked_without_trusting_length(central_config, size,
                                                                    status, length):
    module = importlib.import_module("labos.public_gateway")
    stream = ChunkStream([b"x" * (size // 2), b"x" * (size - size // 2)])
    headers = {"Content-Length": length} if length else {}
    def upstream(request):
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(200, stream=stream, headers=headers)
    with TestClient(module.create_app(central_config, transport=httpx.MockTransport(upstream))) as public:
        result = public.get("/health")
        assert result.status_code == status
        if status == 200:
            assert len(result.content) == size
        else:
            assert result.json() == {"detail": "central response too large"}
    assert stream.closed


def test_fast_unbounded_upstream_is_stopped_before_remaining_chunks(central_config):
    module = importlib.import_module("labos.public_gateway")
    stream = ChunkStream([b"x" * 65536] * 1000)
    with TestClient(module.create_app(central_config, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=stream)))) as public:
        result = public.get("/health")
        assert result.status_code == 502
    assert stream.closed and stream.consumed == 129


@pytest.mark.parametrize("status,expected,consumed", [(307, 502, 0), (500, 500, 0),
                                                     (409, 502, 1)])
def test_error_and_redirect_streams_close_without_draining_or_leaking(central_config, caplog,
                                                                      status, expected, consumed):
    module = importlib.import_module("labos.public_gateway")
    stream = ChunkStream([b"private-body-marker" * 1000000] * 5)
    with TestClient(module.create_app(central_config, transport=httpx.MockTransport(
            lambda request: httpx.Response(status, stream=stream, headers={
                "Location": "https://private-location.example", "Set-Cookie": "private-cookie"})))) as public:
        result = public.get("/health")
        assert result.status_code == expected
        assert "private-" not in result.text + caplog.text
        assert "location" not in result.headers and "set-cookie" not in result.headers
    assert stream.closed and stream.consumed == consumed


@pytest.mark.parametrize("headers", [{"Content-Encoding": "gzip"},
                                     {"Content-Encoding": "br"},
                                     {"Content-Length": "invalid"},
                                     {"Content-Length": "-1"},
                                     {"Content-Length": "9" * 5000},
                                     [("Content-Length", "1"), ("Content-Length", "2")]])
def test_untrusted_upstream_framing_is_rejected_before_body(central_config, headers):
    module = importlib.import_module("labos.public_gateway")
    stream = ChunkStream([b"private-body-marker"])
    with TestClient(module.create_app(central_config, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers=headers, stream=stream)))) as public:
        result = public.get("/health")
        assert result.status_code == 502
        assert "private-" not in result.text
    assert stream.closed and stream.consumed == 0


@pytest.mark.parametrize("body,valid", [
    (b'{"detail":"invalid agent session"}', True),
    (b'{"detail":"another live agent session exists"}', False),
    (b'{"detail":"private-marker"}', False),
    (b'{"detail":"invalid agent session","private":"private-marker"}', False),
    (b'{"code":"invalid_agent_session"}', False),
    (b'{"detail":"invalid agent session","detail":"private-marker"}', False),
    (b'[]', False), (b'null', False), (b'private-marker', False),
])
def test_only_closed_session_error_shape_crosses_boundary(central_config, body, valid):
    module = importlib.import_module("labos.public_gateway")
    stream = ChunkStream([body])
    with TestClient(module.create_app(central_config, transport=httpx.MockTransport(
            lambda request: httpx.Response(409, stream=stream)))) as public:
        result = public.post("/api/agents/pc-a/heartbeat", headers=auth("A" * 40), json={})
        assert result.status_code == 409
        assert result.json() == ({"detail": "invalid agent session", "code": "invalid_agent_session"}
                                 if valid else {"detail": "central rejected the request"})
    assert stream.closed


@pytest.mark.parametrize("endpoint,cap", [("messages", 65536), ("artifacts", 2000000),
                                         ("pilot-artifacts", 2000000), ("pilot-claims", 4096),
                                         ("register", 8388608)])
@pytest.mark.parametrize("has_length", [True, False])
def test_route_request_caps_apply_before_forwarding(central_config, endpoint, cap, has_length):
    module = importlib.import_module("labos.public_gateway")
    calls = []
    def upstream(request):
        calls.append(len(request.content))
        return httpx.Response(200, json={"accepted": True})
    with TestClient(module.create_app(central_config, transport=httpx.MockTransport(upstream))) as public:
        for size in (cap - 1, cap, cap + 1):
            body = b"x" * size
            result = public.post(f"/api/agents/pc-a/{endpoint}", headers=auth("A" * 40),
                                 content=body if has_length else iter([body]))
            assert result.status_code == (200 if size <= cap else 413)
    assert calls == [cap - 1, cap]


def test_body_total_deadline_and_read_failure_close_stream(central_config, monkeypatch):
    module = importlib.import_module("labos.public_gateway")
    monkeypatch.setattr(module, "UPSTREAM_TIMEOUT_S", 0.05)
    for stream in [ChunkStream([b"x"] * 20, delay=0.02),
                   ChunkStream([b"x"], failure=httpx.ReadError("private-exception-marker"))]:
        with TestClient(module.create_app(central_config, transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=stream)))) as public:
            result = public.get("/health")
            assert result.status_code == 503
            assert result.json() == {"detail": "central service unavailable"}
        assert stream.closed and stream.consumed < 20


def test_admission_rejects_before_read_and_releases_after_cancellation(central_config):
    import asyncio
    module = importlib.import_module("labos.public_gateway")
    async def check():
        started = asyncio.Event()
        class BlockedStream(ChunkStream):
            async def __aiter__(self):
                started.set()
                await asyncio.Event().wait()
                yield b"unreachable"
        stream = BlockedStream([])
        calls = 0
        def upstream(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, stream=stream) if calls == 1 else httpx.Response(200, json={})
        app = module.create_app(central_config, max_inflight=1, transport=httpx.MockTransport(upstream))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = asyncio.create_task(client.get("/health"))
            await asyncio.wait_for(started.wait(), 1)
            read = False
            async def body():
                nonlocal read
                read = True
                yield b"private-marker"
            try:
                overloaded = await client.post("/api/agents/pc-a/register", content=body(),
                                               headers=auth("A" * 40))
                assert overloaded.status_code == 503
                assert overloaded.json() == {"detail": "gateway busy"}
                assert not read
            finally:
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
            assert stream.closed
            assert (await client.get("/health")).status_code == 200
    asyncio.run(check())


@pytest.mark.parametrize("maximum", [0, 257, -1, True, 1.5])
def test_invalid_concurrency_setting_is_rejected(central_config, maximum):
    module = importlib.import_module("labos.public_gateway")
    with pytest.raises(ValueError, match="max_inflight"):
        module.create_app(central_config, max_inflight=maximum)


def test_actual_agent_recovers_session_through_actual_gateway(central_config, tmp_path):
    import asyncio
    from labos.agent import Agent
    from labos.config import AgentConfig
    module = importlib.import_module("labos.public_gateway")
    async def check():
        central = central_app(central_config)
        app = module.create_app(central_config, transport=httpx.ASGITransport(app=central))
        async with central.router.lifespan_context(central), app.router.lifespan_context(app):
            agent = Agent(AgentConfig(agent_id="pc-a", token="A" * 40,
                          server_url="http://localhost", data_dir=tmp_path / "agent", instruments=[]),
                          transport=httpx.ASGITransport(app=app))
            try:
                await agent.register()
                assert agent.registered
                boot_id = agent.boot_id
                with central.state.store.transaction() as db:
                    db.execute("UPDATE agents SET boot_id=NULL WHERE id='pc-a'")
                with pytest.raises(httpx.HTTPStatusError):
                    await agent.heartbeat()
                assert not agent.registered
                await agent.register()
                assert agent.registered and agent.boot_id == boot_id
                assert await agent.request("poll", json={"boot_id": boot_id}) == {"command": None}
                with pytest.raises(httpx.HTTPStatusError):
                    await agent.request("results", json={"boot_id": boot_id, "command_id": "missing",
                                                         "state": "COMPLETED", "result": {}})
                assert agent.registered
            finally:
                await agent.close()
    asyncio.run(check())


@pytest.mark.parametrize("character", ["x", "ü"])
def test_maximum_legal_receipts_and_hundred_message_page_fit(central_config, character):
    from labos.config import Enrollment
    agent_id = "p" * 80
    central_config.agents[agent_id] = Enrollment(token="C" * 40, instruments=[])
    path = f"/api/agents/{agent_id}/messages"
    with gateway(central_config) as (public, _, central):
        ids = []
        for index in range(100):
            message_id = f"message{index:03}" + "m" * 70
            ids.append(message_id)
            value = {"id": message_id, "kind": "report", "in_reply_to": None, "body": {"text": ""}}
            overhead = len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())
            available = 65536 - overhead
            value["body"]["text"] = character * (available // len(character.encode())) + "x" * (available % len(character.encode()))
            raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
            assert len(raw) == 65536
            receipt = public.post(path, headers=auth("C" * 40), content=raw)
            assert receipt.status_code == 200
            assert len(receipt.content) > 65536
            if index == 0:
                with central.state.store.transaction() as db:
                    db.execute("UPDATE sqlite_sequence SET seq=9000000000000000000 WHERE name='correspondence'")
        page = public.get(path + "?limit=100", headers=auth("C" * 40))
        assert page.status_code == 200
        assert [m["id"] for m in page.json()["messages"]] == ids
        assert page.json()["next_cursor"] == 9000000000000000099
        assert len(page.content) > 6500000
        assert public.get(path + "?limit=101", headers=auth("C" * 40)).status_code == 422


def test_historically_unbounded_heartbeat_fails_explicitly_without_partial_stop_ids(central_config,
                                                                                 monkeypatch):
    with gateway(central_config) as (public, _, central):
        public.post("/api/agents/pc-a/register", headers=auth("A" * 40), json={"boot_id": "boot1"})
        monkeypatch.setattr(central.state.store, "cancelled_runs", lambda agent_id: ["r" * 80] * 110000)
        result = public.post("/api/agents/pc-a/heartbeat", headers=auth("A" * 40),
                             json={"boot_id": "boot1", "instruments": {}})
        assert result.status_code == 502
        assert result.json() == {"detail": "central response too large"}


def test_downstream_disconnect_closes_upstream_without_retry(central_config):
    import asyncio
    module = importlib.import_module("labos.public_gateway")
    async def check():
        reading = asyncio.Event()
        disconnect = asyncio.Event()
        class BlockedStream(ChunkStream):
            async def __aiter__(self):
                reading.set()
                await asyncio.Event().wait()
                yield b"unreachable"
        stream = BlockedStream([])
        calls = []
        def upstream(request):
            calls.append(request)
            return httpx.Response(200, stream=stream)
        app = module.create_app(central_config, transport=httpx.MockTransport(upstream))
        delivered = False
        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}
        sent = []
        async def send(message):
            sent.append(message)
        async with app.router.lifespan_context(app):
            task = asyncio.create_task(app({"type": "http", "asgi": {"version": "3.0"},
                "http_version": "1.1", "scheme": "http", "method": "GET", "path": "/health",
                "raw_path": b"/health", "query_string": b"", "headers": [],
                "client": ("test", 1), "server": ("test", 80)}, receive, send))
            await asyncio.wait_for(reading.wait(), 1)
            disconnect.set()
            try:
                await asyncio.wait_for(task, 1)
            except asyncio.CancelledError:
                pass
            assert stream.closed and len(calls) == 1
            assert not sent
    asyncio.run(check())


@pytest.mark.parametrize("maximum", [1, 32])
def test_admission_covers_slow_downstream_response_delivery(central_config, maximum):
    import asyncio
    module = importlib.import_module("labos.public_gateway")
    async def check():
        app = module.create_app(central_config, **({"max_inflight": 1} if maximum == 1 else {}),
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})))
        bodies = asyncio.Queue()
        release = asyncio.Event()
        async def held_request():
            delivered = False
            async def receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                await asyncio.Event().wait()
            async def send(message):
                if message["type"] == "http.response.body":
                    bodies.put_nowait(message)
                    await release.wait()
            await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                       "scheme": "http", "method": "GET", "path": "/health", "raw_path": b"/health",
                       "query_string": b"", "headers": [], "client": ("test", 1), "server": ("test", 80)},
                      receive, send)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            tasks = [asyncio.create_task(held_request()) for _ in range(maximum)]
            try:
                for _ in range(maximum):
                    await asyncio.wait_for(bodies.get(), 1)
                result = await client.get("/health")
                assert result.status_code == 503
                assert result.json() == {"detail": "gateway busy"}
            finally:
                release.set()
                await asyncio.gather(*tasks)
            assert (await client.get("/health")).status_code == 200
    asyncio.run(check())


@pytest.mark.parametrize("endpoint", ["messages", "artifacts"])
def test_private_central_rejects_huge_chunk_before_allocating_a_copy(central_config, endpoint):
    import asyncio
    import tracemalloc
    async def check():
        app = central_app(central_config)
        body = b"x" * 16777216
        headers = [(b"authorization", b"Bearer " + b"A" * 40),
                   (b"x-boot-id", b"boot1"), (b"x-sha256", b"0" * 64)]
        sent = []
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        async def send(message):
            sent.append(message)
        async with app.router.lifespan_context(app):
            app.state.store.register("pc-a", "boot1")
            tracemalloc.start()
            try:
                await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                    "scheme": "http", "method": "POST", "path": f"/api/agents/pc-a/{endpoint}",
                    "raw_path": f"/api/agents/pc-a/{endpoint}".encode(), "query_string": b"",
                    "headers": headers, "client": ("test", 1), "server": ("test", 80)}, receive, send)
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            assert sent[0]["status"] == 413
            assert peak < 8388608
    asyncio.run(check())


def test_gateway_receive_deadline_and_cancellation_release_admission(central_config, monkeypatch):
    import asyncio
    module = importlib.import_module("labos.public_gateway")
    monkeypatch.setattr(module, "UPSTREAM_TIMEOUT_S", 0.05)
    async def check():
        calls = []
        def upstream(request):
            calls.append(request)
            return httpx.Response(200, json={})
        app = module.create_app(central_config, max_inflight=1, transport=httpx.MockTransport(upstream))
        async with app.router.lifespan_context(app), httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            async def slow_body():
                for _ in range(20):
                    await asyncio.sleep(0.02)
                    yield b"x"
            timed_out = await client.post("/api/agents/pc-a/register", headers=auth("A" * 40), content=slow_body())
            assert timed_out.status_code == 408
            assert not calls
            reading = asyncio.Event()
            closed = False
            async def blocked_body():
                nonlocal closed
                reading.set()
                try:
                    await asyncio.Event().wait()
                    yield b"unreachable"
                finally:
                    closed = True
            task = asyncio.create_task(client.post("/api/agents/pc-a/register", headers=auth("A" * 40), content=blocked_body()))
            await reading.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert closed and not calls
            assert (await client.get("/health")).status_code == 200
            assert len(calls) == 1
    asyncio.run(check())


@pytest.mark.parametrize("body,registered,status", [
    (b'{"detail":"invalid agent session"}', False, 409),
    (b'{"detail":"another live agent session exists"}', True, 409),
    (b'{"detail":"private-marker"}', True, 409),
    (b'{"detail":"invalid agent session","extra":"private-marker"}', True, 409),
    (b'{"code":"invalid_agent_session"}', True, 409),
    (b'[]', True, 409), (b'private-marker', True, 409), (b'x' * 4097, True, 502),
])
def test_actual_agent_only_resets_for_closed_session_signal(central_config, tmp_path, body, registered, status):
    import asyncio
    from labos.agent import Agent
    from labos.config import AgentConfig
    module = importlib.import_module("labos.public_gateway")
    async def check():
        calls = []
        def upstream(request):
            calls.append(request)
            return httpx.Response(409, stream=ChunkStream([body]))
        app = module.create_app(central_config, transport=httpx.MockTransport(upstream))
        async with app.router.lifespan_context(app):
            agent = Agent(AgentConfig(agent_id="pc-a", token="A" * 40,
                          server_url="http://localhost", data_dir=tmp_path / "agent", instruments=[]),
                          transport=httpx.ASGITransport(app=app))
            agent.registered = True
            try:
                with pytest.raises(httpx.HTTPStatusError) as rejected:
                    await agent.request("heartbeat", json={"boot_id": agent.boot_id, "instruments": {}})
                assert rejected.value.response.status_code == status
                assert agent.registered is registered
                assert len(calls) == 1
            finally:
                await agent.close()
    asyncio.run(check())


@pytest.mark.parametrize("maximum", ["0", "257", "-1", "invalid"])
def test_cli_rejects_invalid_concurrency_without_starting_a_server(maximum):
    result = subprocess.run([sys.executable, "-m", "labos.public_gateway", "--config", "/unused-private.yaml",
                             "--max-inflight", maximum], capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "--max-inflight" in result.stderr


def test_actual_agent_run_loop_reregisters_after_central_session_loss(central_config, tmp_path):
    import asyncio
    from labos.agent import Agent
    from labos.config import AgentConfig
    module = importlib.import_module("labos.public_gateway")
    async def check():
        central = central_app(central_config)
        private = httpx.ASGITransport(app=central)
        boot_ids = []
        session_lost = False
        recovered = False
        async def relay(request):
            nonlocal session_lost, recovered
            response = await private.handle_async_request(request)
            if request.url.path.endswith("/register") and response.status_code == 200:
                boot_ids.append(json.loads(request.content)["boot_id"])
            elif request.url.path.endswith("/poll") and response.status_code == 200:
                if not session_lost:
                    with central.state.store.transaction() as db:
                        db.execute("UPDATE agents SET boot_id=NULL WHERE id='pc-a'")
                    session_lost = True
                elif len(boot_ids) == 2:
                    recovered = True
                    agent.shutdown.set()
            return response
        app = module.create_app(central_config, transport=httpx.MockTransport(relay))
        async with central.router.lifespan_context(central), app.router.lifespan_context(app):
            agent = Agent(AgentConfig(agent_id="pc-a", token="A" * 40, server_url="http://localhost",
                          data_dir=tmp_path / "agent", instruments=[], heartbeat_s=0.1, poll_s=0.05),
                          transport=httpx.ASGITransport(app=app))
            await asyncio.wait_for(agent.run(), 5)
            assert recovered and session_lost
            assert boot_ids == [agent.boot_id, agent.boot_id]
            assert agent.client.is_closed
    asyncio.run(check())
