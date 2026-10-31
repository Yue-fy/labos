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
    assert "--config" in result.stdout and "--host" in result.stdout and "--port" in result.stdout


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
