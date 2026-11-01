import json
import os
import stat
import warnings
import zipfile

import pytest
import yaml

from labos.delivery import build_agent_bundle
from labos import __version__
from labos.cli import provision
from scripts.build_delivery import build_release


def test_role_archives_are_complete_and_have_no_live_credentials(tmp_path):
    packages = build_release(tmp_path)
    assert {p.name for p in packages} >= {f"LabOS-Central-{__version__}.zip",
                                         f"LabOS-Agent-{__version__}.zip"}
    for package_path in packages:
        with zipfile.ZipFile(package_path) as package:
            names = package.namelist()
            assert len(names) == len(set(names)), "archive must not contain duplicate entries"
            assert "Start-Agent.ps1" in names
            assert "Install.ps1" in names
            assert not any(name.endswith("_ZH.md") for name in names)
            assert "QUICKSTART_EN.md" in names
            assert "NETWORK_EN.md" in names
            for guide in ("AGENTS.md", "README_AGENT_KIT_EN.md", "PC_AGENT_GUIDE_EN.md",
                          "SERVER_AGENT_GUIDE_EN.md", "AGENT_HANDOFF_EN.md", "CAVITY_REFERENCE_EN.md"):
                assert guide in names
            for template in ("PC_INTAKE_TEMPLATE.json", "SERVER_REPLY_TEMPLATE.json"):
                json.loads(package.read(template))
            assert "docs/WINDOWS_INSTALL_FIX_EN.md" in names
            assert "src/labos/cli.py" in names
            assert all(not name.startswith("/") and ".." not in name.split("/") for name in names)
            assert "config.yaml" not in names
            assert not any("central.sqlite" in name or "operator.token" in name for name in names)


def test_generic_releases_ship_fresh_uncommissioned_pilot_template(tmp_path):
    for package_path in build_release(tmp_path):
        with zipfile.ZipFile(package_path) as package:
            template = yaml.safe_load(package.read("pilot-worker.example.yaml"))
        approval, adapter = template["approval"], template["adapter_config"]
        assert (approval["sample_id"],
                adapter["chopper_phase_lock_manually_confirmed"],
                adapter["chopper_phase_lock_confirmation_note"]) == ("example-sample", False, "")
        assert approval["enabled"] is False
        assert adapter["commissioned"] is False
        assert adapter["manual_route_confirmed"] is False


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
        assert "AGENTS.md" in package.namelist()
        assert "PC_AGENT_GUIDE_EN.md" in package.namelist()


def test_dashboard_has_no_persistent_token_storage():
    from pathlib import Path
    import labos
    text = (Path(labos.__file__).parent / "static/index.html").read_text()
    assert "localStorage" not in text
    assert "sessionStorage" not in text
    assert "innerHTML" not in text


@pytest.fixture
def agent_config(tmp_path):
    path = tmp_path / "input.yaml"
    path.write_text("agent_id: pc-test\ntoken: " + "A" * 32 +
                    "\nserver_url: http://localhost:8000\ninstruments: []\n")
    return path


UNSAFE_MEMBERS = [
    ["python/..\\escape"], ["python/python.exe:payload"],
    ["python/python.exe", "python/python.exe"],
    ["python/python.exe", "python/PYTHON.EXE"],
    ["/python/x"], ["C:/python/x"], ["\\server\\python"],
    ["python/./x"], ["python/../x"], ["python//x"],
    ["python/CON.txt"], ["python/com¹.txt"], ["python/LPT²"],
    ["python/lpt³.log"], ["python/name."], ["python/name "],
    ["python/a?b"], ["python/a\x01b"],
    ["python/a", "python/a/b"], ["python/A/b", "python/a/c"],
    ["python/a/", "python/a"],
]


@pytest.mark.parametrize("members", UNSAFE_MEMBERS)
@pytest.mark.parametrize("personalized", [True, False])
def test_builders_reject_unsafe_runtime_before_publication(tmp_path, agent_config, members, personalized):
    runtime = tmp_path / "runtime.zip"
    with zipfile.ZipFile(runtime, "w") as package:
        for name in members:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                package.writestr(name, b"synthetic")
    output = tmp_path / "release"
    output.mkdir()
    with pytest.raises(ValueError):
        if personalized:
            build_agent_bundle(agent_config, output / "pc.zip", runtime)
        else:
            build_release(output, runtime)
    assert list(output.iterdir()) == []


def test_personalized_staging_private_during_config_write_and_cleaned_on_failure(tmp_path, agent_config, monkeypatch):
    output = tmp_path / "release"
    output.mkdir()
    original = zipfile.ZipFile.writestr
    modes = []

    def fail_after_config(package, name, data, *args, **kwargs):
        result = original(package, name, data, *args, **kwargs)
        if name == "config.yaml":
            modes.append(stat.S_IMODE(os.fstat(package.fp.fileno()).st_mode))
            raise OSError("synthetic disk failure after credential write")
        return result

    monkeypatch.setattr(zipfile.ZipFile, "writestr", fail_after_config)
    previous = os.umask(0o022)
    try:
        with pytest.raises(OSError, match="synthetic disk failure"):
            build_agent_bundle(agent_config, output / "pc.zip")
    finally:
        os.umask(previous)
    if os.name == "posix":
        assert modes == [0o600]
    assert list(output.iterdir()) == []


def test_personalized_existing_output_preserved(tmp_path, agent_config):
    output = tmp_path / "pc.zip"
    output.write_bytes(b"existing delivery")
    with pytest.raises(FileExistsError):
        build_agent_bundle(agent_config, output)
    assert output.read_bytes() == b"existing delivery"


@pytest.mark.parametrize("collision", [f"LabOS-Central-{__version__}.zip", f"LabOS-Agent-{__version__}.zip",
                                       f"LabOS-Agent-Windows-x64-{__version__}.zip", "SHA256SUMS"])
def test_generic_release_preflights_every_output(tmp_path, collision):
    runtime = tmp_path / "runtime.zip"
    with zipfile.ZipFile(runtime, "w") as package:
        package.writestr("python/", b"")
        package.writestr("python/python.exe", b"synthetic")
    output = tmp_path / "release"
    output.mkdir()
    (output / collision).write_bytes(b"prior release")
    with pytest.raises(FileExistsError):
        build_release(output, runtime)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == {collision: b"prior release"}


def test_runtime_directory_entries_work_in_both_delivery_builders(tmp_path, agent_config):
    runtime = tmp_path / "runtime.zip"
    with zipfile.ZipFile(runtime, "w") as package:
        package.writestr("python/", b"")
        package.writestr("python/Lib/", b"")
        package.writestr("python/Lib/test.py", b"synthetic")
    personal = build_agent_bundle(agent_config, tmp_path / "pc.zip", runtime)
    generic = build_release(tmp_path / "release", runtime)[-1]
    for path in (personal, generic):
        with zipfile.ZipFile(path) as package:
            assert package.read("python/Lib/test.py") == b"synthetic"


def test_generic_late_publication_failure_rolls_back_only_new_files(tmp_path, monkeypatch):
    output = tmp_path / "release"
    output.mkdir()
    (output / "unrelated").write_bytes(b"keep")
    original_link = os.link
    calls = []

    def fail_second(source, target, **kwargs):
        calls.append(target)
        if len(calls) == 2:
            raise OSError("synthetic publication failure")
        return original_link(source, target, **kwargs)

    monkeypatch.setattr(os, "link", fail_second)
    with pytest.raises(OSError, match="synthetic publication failure"):
        build_release(output)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == {"unrelated": b"keep"}


def test_missing_ca_leaves_no_archive(tmp_path, agent_config):
    agent_config.write_text(agent_config.read_text() + "ca_file: missing-ca.pem\n")
    output = tmp_path / "release"
    output.mkdir()
    with pytest.raises(FileNotFoundError):
        build_agent_bundle(agent_config, output / "pc.zip")
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("personalized", [True, False])
def test_original_nul_names_rejected_before_zipinfo_truncation(tmp_path, agent_config, personalized):
    runtime = tmp_path / "runtime.zip"
    with zipfile.ZipFile(runtime, "w") as package:
        package.writestr("python/a!b", b"synthetic")
    runtime.write_bytes(runtime.read_bytes().replace(b"python/a!b", b"python/a\x00b"))
    output = tmp_path / "release"
    output.mkdir()
    with pytest.raises(ValueError):
        if personalized:
            build_agent_bundle(agent_config, output / "pc.zip", runtime)
        else:
            build_release(output, runtime)
    assert list(output.iterdir()) == []


def test_personalized_runtime_read_failure_removes_credentials(tmp_path, agent_config, monkeypatch):
    runtime = tmp_path / "runtime.zip"
    with zipfile.ZipFile(runtime, "w") as package:
        package.writestr("python/python.exe", b"synthetic")
    original_read = zipfile.ZipFile.read

    def fail_runtime_read(package, member, *args, **kwargs):
        if isinstance(member, zipfile.ZipInfo) and member.filename == "python/python.exe":
            raise zipfile.BadZipFile("synthetic CRC failure")
        return original_read(package, member, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "read", fail_runtime_read)
    output = tmp_path / "release"
    output.mkdir()
    with pytest.raises(zipfile.BadZipFile, match="synthetic CRC"):
        build_agent_bundle(agent_config, output / "pc.zip", runtime)
    assert list(output.iterdir()) == []


def test_personalized_concurrent_output_preserved_and_staging_removed(tmp_path, agent_config, monkeypatch):
    output = tmp_path / "release"
    output.mkdir()
    target = output / "pc.zip"
    original_link = os.link

    def race(source, destination, **kwargs):
        target.write_bytes(b"concurrent winner")
        return original_link(source, destination, **kwargs)

    monkeypatch.setattr(os, "link", race)
    with pytest.raises(FileExistsError):
        build_agent_bundle(agent_config, target)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == {"pc.zip": b"concurrent winner"}


def test_personalized_archive_complete_before_publication(tmp_path, agent_config, monkeypatch):
    original_link = os.link

    def inspect_source(source, target, **kwargs):
        with zipfile.ZipFile(source) as archive:
            assert "token:" in archive.read("config.yaml").decode()
        return original_link(source, target, **kwargs)

    monkeypatch.setattr(os, "link", inspect_source)
    build_agent_bundle(agent_config, tmp_path / "pc.zip")
