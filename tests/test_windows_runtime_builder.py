import hashlib
import json
import os
import warnings
import zipfile
from pathlib import Path

import pytest

from scripts import build_windows_runtime as builder


def write_zip(path, members):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                member = zipfile.ZipInfo(name)
                # Preserve unsafe test names that ZipInfo normalizes on Windows.
                member.filename = name
                archive.writestr(member, data)


@pytest.fixture
def runtime_build(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    original = tmp_path / "build/windows-runtime/python.zip"
    write_zip(original, [("python.exe", b"synthetic-python"), ("Lib/", b""), ("python314._pth", b"old")])
    monkeypatch.setattr(builder, "PYTHON_SHA256", hashlib.sha256(original.read_bytes()).hexdigest())

    def no_network(*args, **kwargs):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(builder.urllib.request, "urlopen", no_network)
    return tmp_path, original


def install_pip_fixture(monkeypatch, wheels):
    def download(command, check):
        assert check is True
        destination = Path(command[command.index("--dest") + 1])
        for filename, members in wheels:
            write_zip(destination / filename, members)
    monkeypatch.setattr(builder.subprocess, "run", download)


def test_runtime_uses_fresh_wheels_only_and_keeps_third_party_guides(runtime_build, monkeypatch):
    root, _ = runtime_build
    write_zip(root / "build/windows-runtime/wheels/demo-9.whl", [("demo.py", b"stale")])
    install_pip_fixture(monkeypatch, [("demo-10.whl", [("demo.py", b"fresh"), ("docs/README_ZH.md", b"dependency")])])
    builder.build()
    with zipfile.ZipFile(root / "dist/delivery/windows-x64-runtime.zip") as package:
        assert package.read("python/Lib/site-packages/demo.py") == b"fresh"
        assert package.read("python/Lib/site-packages/docs/README_ZH.md") == b"dependency"
        assert len(package.namelist()) == len(set(package.namelist()))
        provenance = json.loads(package.read("python/RUNTIME_PROVENANCE.json"))
        assert [wheel["file"] for wheel in provenance["wheels"]] == ["demo-10.whl"]
    assert sorted(p.name for p in (root / "build/windows-runtime").iterdir()) == ["python.zip", "wheels"]


@pytest.mark.parametrize("wheels", [
    [("one.whl", [("a.py", b"one"), ("x.data/purelib/a.py", b"two")])],
    [("one.whl", [("a.py", b"one")]), ("two.whl", [("A.py", b"two")])],
    [("one.whl", [("x.data/platlib/a.py", b"one")]), ("two.whl", [("a.py", b"two")])],
    [("one.whl", [("bad\\name.py", b"one")])],
    [("one.whl", [("a.py:stream", b"one")])],
    [("one.whl", [("x.data/purelib/COM³.py", b"one")])],
    [("one.whl", [("a.py", b"one"), ("a.py", b"two")])],
    [("one.whl", [("x.data/", b""), ("x.data/purelib/", b""), ("x.data/purelib/../bad", b"one")])],
])
def test_runtime_rejects_unsafe_original_and_remapped_wheel_destinations(runtime_build, monkeypatch, wheels):
    root, _ = runtime_build
    install_pip_fixture(monkeypatch, wheels)
    with pytest.raises(ValueError):
        builder.build()
    output = root / "dist/delivery"
    assert not output.exists() or list(output.iterdir()) == []


def test_runtime_rejects_collisions_with_upstream(runtime_build, monkeypatch):
    root, original = runtime_build
    write_zip(original, [("python.exe", b"synthetic"), ("Lib/site-packages/a.py", b"upstream")])
    monkeypatch.setattr(builder, "PYTHON_SHA256", hashlib.sha256(original.read_bytes()).hexdigest())
    install_pip_fixture(monkeypatch, [("one.whl", [("a.py", b"wheel")])])
    with pytest.raises(ValueError):
        builder.build()
    assert not (root / "dist/delivery/windows-x64-runtime.zip").exists()


@pytest.mark.parametrize("name", ["..\\escape", "python.exe:stream", "CON", "A/../b"])
def test_runtime_rejects_unsafe_upstream_before_publication(runtime_build, monkeypatch, name):
    root, original = runtime_build
    write_zip(original, [(name, b"synthetic")])
    monkeypatch.setattr(builder, "PYTHON_SHA256", hashlib.sha256(original.read_bytes()).hexdigest())
    install_pip_fixture(monkeypatch, [])
    with pytest.raises(ValueError):
        builder.build()
    assert not (root / "dist/delivery/windows-x64-runtime.zip").exists()


def test_runtime_preserves_prior_output_even_when_new_inputs_invalid(runtime_build, monkeypatch):
    root, _ = runtime_build
    output = root / "dist/delivery/windows-x64-runtime.zip"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"prior verified runtime")
    install_pip_fixture(monkeypatch, [("bad.whl", [("../escape", b"bad")])])
    with pytest.raises(FileExistsError):
        builder.build()
    assert output.read_bytes() == b"prior verified runtime"
    assert list(output.parent.iterdir()) == [output]


def test_second_build_uses_new_resolution_without_historical_wheels(runtime_build, monkeypatch):
    root, _ = runtime_build
    install_pip_fixture(monkeypatch, [("demo-1.whl", [("demo.py", b"first")])])
    builder.build()
    output = root / "dist/delivery/windows-x64-runtime.zip"
    first = root / "first.zip"
    output.rename(first)
    install_pip_fixture(monkeypatch, [("demo-2.whl", [("demo.py", b"second")])])
    builder.build()
    with zipfile.ZipFile(first) as archive:
        assert archive.read("python/Lib/site-packages/demo.py") == b"first"
    with zipfile.ZipFile(output) as archive:
        assert archive.read("python/Lib/site-packages/demo.py") == b"second"
        provenance = json.loads(archive.read("python/RUNTIME_PROVENANCE.json"))
        assert [wheel["file"] for wheel in provenance["wheels"]] == ["demo-2.whl"]


def test_runtime_concurrent_output_preserved_and_staging_removed(runtime_build, monkeypatch):
    root, _ = runtime_build
    output = root / "dist/delivery/windows-x64-runtime.zip"
    install_pip_fixture(monkeypatch, [])
    original_link = os.link

    def race(source, target, **kwargs):
        output.write_bytes(b"concurrent runtime")
        return original_link(source, target, **kwargs)

    monkeypatch.setattr(os, "link", race)
    with pytest.raises(FileExistsError):
        builder.build()
    assert output.read_bytes() == b"concurrent runtime"
    assert list(output.parent.iterdir()) == [output]


def test_runtime_rejects_multiple_versions_of_same_distribution(runtime_build, monkeypatch):
    root, _ = runtime_build
    install_pip_fixture(monkeypatch, [
        ("demo_lib-1-py3-none-any.whl", [("demo_lib-1.dist-info/METADATA", b"old")]),
        ("demo.lib-2-py3-none-any.whl", [("demo.lib-2.dist-info/METADATA", b"new")]),
    ])
    with pytest.raises(ValueError):
        builder.build()
    assert not (root / "dist/delivery/windows-x64-runtime.zip").exists()


def test_runtime_merges_ordinary_shared_and_remapped_directory_entries(runtime_build, monkeypatch):
    root, _ = runtime_build
    install_pip_fixture(monkeypatch, [
        ("one.whl", [("shared/", b""), ("shared/one.py", b"one")]),
        ("two.whl", [("x.data/", b""), ("x.data/purelib/", b""),
                     ("x.data/purelib/shared/", b""), ("x.data/purelib/shared/two.py", b"two")]),
    ])
    builder.build()
    with zipfile.ZipFile(root / "dist/delivery/windows-x64-runtime.zip") as package:
        assert package.read("python/Lib/site-packages/shared/one.py") == b"one"
        assert package.read("python/Lib/site-packages/shared/two.py") == b"two"
        assert len(package.namelist()) == len(set(package.namelist()))
