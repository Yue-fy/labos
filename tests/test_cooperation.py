from fastapi.testclient import TestClient
import argparse
import json

import httpx
import pytest

from labos.central import create_app
from labos.cli import provision
from labos.config import CentralConfig, load_config
from labos.cooperation import add_parser, run


def auth(token):
    return {"Authorization": "Bearer " + token}


def report(message_id="msg_report_1", **changes):
    return {
        "id": message_id,
        "kind": "report",
        "body": {"document_type": "pc_intake", "executable": False},
        **changes,
    }


def test_messages_are_durable_idempotent_and_never_execute_commands(central_config):
    path = "/api/agents/pc-a/messages"
    app = create_app(central_config)
    with TestClient(app) as client:
        first = client.post(path, headers=auth("A" * 40), json=report())
        assert first.status_code == 200, first.text
        assert first.json()["effect"] == "stored_only"
        assert first.json()["message"]["sender"] == "pc"
        again = client.post(path, headers=auth("A" * 40), json=report())
        assert again.json()["message"]["sequence"] == first.json()["message"]["sequence"]
        assert (
            client.post(
                path, headers=auth("A" * 40), json=report(body={"changed": True})
            ).status_code
            == 409
        )
        with app.state.store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0
    with TestClient(create_app(central_config)) as client:
        records = client.get(path, headers=auth("O" * 40)).json()["messages"]
        assert len(records) == 1
        assert records[0]["body"]["executable"] is False


def test_message_authentication_and_pc_isolation(central_config):
    with TestClient(create_app(central_config)) as client:
        path = "/api/agents/pc-a/messages"
        assert client.post(path, json=report()).status_code == 401
        assert client.post(path, headers=auth("B" * 40), json=report()).status_code == 403
        assert client.get(path, headers=auth("B" * 40)).status_code == 403
        assert (
            client.post(path, headers=auth("A" * 40), json=report(sender="central")).status_code
            == 422
        )


def test_replies_and_cursor_pagination(central_config):
    with TestClient(create_app(central_config)) as client:
        path = "/api/agents/pc-a/messages"
        sent = client.post(path, headers=auth("A" * 40), json=report()).json()["message"]
        reply = client.post(
            path,
            headers=auth("O" * 40),
            json=report(
                "msg_reply_1",
                kind="reply",
                in_reply_to=sent["id"],
                body={"next_step": "Network checks only"},
            ),
        )
        assert reply.status_code == 200, reply.text
        assert reply.json()["message"]["sender"] == "central"
        incoming = client.get(
            path, params={"sender": "central", "after": sent["sequence"]}, headers=auth("A" * 40)
        ).json()
        assert [m["id"] for m in incoming["messages"]] == ["msg_reply_1"]
        assert incoming["next_cursor"] == reply.json()["message"]["sequence"]
        assert not client.get(
            path, params={"after": incoming["next_cursor"]}, headers=auth("A" * 40)
        ).json()["messages"]


def test_reply_cannot_reference_another_pc_or_an_unknown_message(central_config):
    with TestClient(create_app(central_config)) as client:
        client.post("/api/agents/pc-a/messages", headers=auth("A" * 40), json=report())
        for reference in ["msg_report_1", "missing_message"]:
            result = client.post(
                "/api/agents/pc-b/messages",
                headers=auth("O" * 40),
                json=report("reply_other", kind="reply", in_reply_to=reference),
            )
            assert result.status_code == 409


def test_message_payload_size_and_credentials_are_rejected(central_config):
    with TestClient(create_app(central_config)) as client:
        path = "/api/agents/pc-a/messages"
        assert (
            client.post(
                path, headers=auth("A" * 40), json=report(body={"text": "x" * 70000})
            ).status_code
            == 413
        )
        for body in [
            {"nested": {"admin_token": "sensitive"}},
            {"text": "A" * 40},
            {"text": "O" * 40},
        ]:
            response = client.post(path, headers=auth("A" * 40), json=report(body=body))
            assert response.status_code == 409
            assert "sensitive" not in response.text and "A" * 40 not in response.text


@pytest.mark.parametrize("special", ["\\", '"', "numeric"])
def test_json_escaped_credentials_cannot_enter_correspondence(central_config, special):
    credential = "7" * 40 if special == "numeric" else "private-" + special + "a" * 40
    central_config.agents["pc-a"].token = credential
    with TestClient(create_app(central_config)) as client:
        response = client.post(
            "/api/agents/pc-a/messages",
            headers=auth(credential),
            json=report(
                body={"nested": [{"text": int(credential) if special == "numeric" else credential}]}
            ),
        )
        assert response.status_code == 409
        assert not client.get("/api/agents/pc-a/messages", headers=auth(credential)).json()[
            "messages"
        ]


def test_cli_sends_and_pulls_through_actual_api_without_registering(tmp_path, capsys):
    configs = provision(tmp_path / "config", "http://localhost:8000")
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    source = tmp_path / "report.json"
    source.write_text('{"report_id":"pc-intake-001","executable":false}')
    central = load_config(configs["central"], CentralConfig)
    with TestClient(create_app(central)) as api:

        def handler(request):
            assert request.url.path.endswith("/messages")
            response = api.request(
                request.method, str(request.url), content=request.content, headers=request.headers
            )
            return httpx.Response(response.status_code, json=response.json())

        transport = httpx.MockTransport(handler)
        send = parser.parse_args(
            [
                "cooperate",
                "send",
                "--role",
                "pc",
                "--config",
                str(configs["pc-a"]),
                "--input",
                str(source),
            ]
        )
        assert run(send, transport) == 0
        assert run(send, transport) == 0
        output = tmp_path / "received.json"
        pull = parser.parse_args(
            [
                "cooperate",
                "pull",
                "--role",
                "central",
                "--agent",
                "pc-a",
                "--config",
                str(configs["central"]),
                "--output",
                str(output),
            ]
        )
        assert run(pull, transport) == 0
        messages = json.loads(output.read_text())["messages"]
        assert len(messages) == 1
        assert messages[0]["body"]["report_id"] == "pc-intake-001"
    printed = capsys.readouterr().out
    assert central.admin_token not in printed
    assert central.agents["pc-a"].token not in printed


def test_pc_cli_does_not_send_credential_to_an_overridden_origin(tmp_path):
    configs = provision(tmp_path / "config", "http://localhost:8000")
    parser = argparse.ArgumentParser()
    add_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        [
            "cooperate",
            "pull",
            "--role",
            "pc",
            "--config",
            str(configs["pc-a"]),
            "--server-url",
            "http://other-host.example",
        ]
    )

    def forbidden_request(request):
        raise AssertionError("credential was sent to an unprovisioned origin")

    with pytest.raises(ValueError, match="provisioned"):
        run(args, httpx.MockTransport(forbidden_request))
