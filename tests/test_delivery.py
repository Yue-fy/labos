import zipfile

from labos.delivery import build_agent_bundle
from labos.cli import provision
from scripts.build_delivery import build_release


def test_role_archives_are_complete_and_have_no_live_credentials(tmp_path):
    packages = build_release(tmp_path)
    assert {p.name for p in packages} >= {"LabOS-Central-0.2.0.zip", "LabOS-Agent-0.2.0.zip"}
    for package_path in packages:
        with zipfile.ZipFile(package_path) as package:
            names = package.namelist()
            assert len(names) == len(set(names)), "archive must not contain duplicate entries"
            assert "Start-Agent.ps1" in names
            assert "Install.ps1" in names
            assert "NETWORK_ZH.md" in names
            assert "src/labos/cli.py" in names
            assert all(not name.startswith("/") and ".." not in name.split("/") for name in names)
            assert "config.yaml" not in names
            assert not any("central.sqlite" in name or "operator.token" in name for name in names)


def test_windows_runtime_can_be_added_to_personalized_pc_bundle(tmp_path):
    paths = provision(tmp_path / "configs", "http://localhost:8000")
    runtime = tmp_path / "runtime.zip"
    with zipfile.ZipFile(runtime, "w") as package:
        package.writestr("python/python.exe", "test-runtime")
        package.writestr("python/python314._pth", "../src\n")
    output = build_agent_bundle(paths["pc-a"], tmp_path / "pc.zip", runtime_archive=runtime)
    with zipfile.ZipFile(output) as package:
        assert "python/python.exe" in package.namelist()
        assert "config.yaml" in package.namelist()


def test_dashboard_has_no_persistent_token_storage():
    from pathlib import Path
    import labos
    text = (Path(labos.__file__).parent / "static/index.html").read_text()
    assert "localStorage" not in text
    assert "sessionStorage" not in text
    assert "innerHTML" not in text
