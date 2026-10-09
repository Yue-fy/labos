import zipfile

import httpx

from labos.cli import doctor, provision
from labos.config import AgentConfig, CentralConfig, load_config


def test_provision_generates_distinct_secrets_and_relative_paths(tmp_path):
    paths = provision(tmp_path / "Lab deployment", "http://127.0.0.1:8000")
    central = load_config(paths["central"], CentralConfig)
    a = load_config(paths["pc-a"], AgentConfig)
    b = load_config(paths["pc-b"], AgentConfig)
    assert len({central.admin_token, a.token, b.token}) == 3
    assert a.data_dir.parent.name == "pc-a"
    assert a.token == central.agents["pc-a"].token
    assert central.admin_token not in paths["pc-a"].read_text()
    assert b.token not in paths["pc-a"].read_text()
    assert a.server_url == "http://127.0.0.1:8000"


def test_doctor_checks_agent_auth_without_registering(tmp_path):
    paths = provision(tmp_path, "http://127.0.0.1:8000")
    config = load_config(paths["pc-a"], AgentConfig)
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"service": "labos-central", "status": "ok"})
        assert request.headers["Authorization"] == f"Bearer {config.token}"
        return httpx.Response(200, json={"agent_id": "pc-a", "enrolled": True})
    assert doctor(config, httpx.MockTransport(handler))["authenticated"]
    assert all(request.method == "GET" for request in requests)


def test_provision_refuses_overwrite_and_real_mode(tmp_path):
    import pytest
    from labos.models import InstrumentSpec
    provision(tmp_path, "http://localhost:8000")
    with pytest.raises(FileExistsError):
        provision(tmp_path, "http://localhost:8000")
    with pytest.raises(ValueError):
        InstrumentSpec(id="real_laser", kind="laser", mode="real")


def test_personalized_bundle_excludes_other_credentials(tmp_path):
    from labos.delivery import build_agent_bundle
    paths = provision(tmp_path / "deployment", "http://localhost:8000")
    config = load_config(paths["central"], CentralConfig)
    archive = build_agent_bundle(paths["pc-a"], tmp_path / "pc-a.zip")
    with zipfile.ZipFile(archive) as package:
        contents = b"\n".join(package.read(n) for n in package.namelist())
    assert config.admin_token.encode() not in contents
    assert config.agents["pc-b"].token.encode() not in contents
    assert config.agents["pc-a"].token.encode() in contents
