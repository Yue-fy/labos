from fastapi.testclient import TestClient

from labos.central import create_app


def headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_and_agent_scopes(central_config):
    with TestClient(create_app(central_config)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/status").status_code == 401
        assert client.get("/api/status", headers=headers("A" * 40)).status_code == 403
        assert client.get("/api/status", headers=headers("O" * 40)).status_code == 200
        assert client.post("/api/agents/pc-b/register", headers=headers("A" * 40),
                           json={"boot_id": "boot1"}).status_code == 403


def test_registration_identity_and_stale_session(central_config):
    with TestClient(create_app(central_config)) as client:
        auth = headers("A" * 40)
        assert client.post("/api/agents/pc-a/register", headers=auth,
                           json={"boot_id": "boot1"}).status_code == 200
        assert client.post("/api/agents/pc-a/register", headers=auth,
                           json={"boot_id": "boot2"}).status_code == 409
        body = {"boot_id": "boot1", "instruments": {"rotator_01": {"stable": True}}}
        assert client.post("/api/agents/pc-a/heartbeat", headers=auth, json=body).status_code == 409
        assert client.post("/api/agents/pc-a/poll", headers=auth,
                           json={"boot_id": "obsolete"}).status_code == 409


def test_start_rejects_offline_and_unconfirmed_setup(central_config):
    with TestClient(create_app(central_config)) as client:
        assert client.post("/api/runs", headers=headers("O" * 40), json={}).status_code == 409


def test_agent_named_operator_does_not_gain_operator_permissions(central_config):
    central_config.agents["operator"] = central_config.agents.pop("pc-a")
    with TestClient(create_app(central_config)) as client:
        assert client.get("/api/status", headers=headers("A" * 40)).status_code == 403

