import hashlib
import json

import pytest

from labos.source_context import ReadOnlySources, SourceContextError


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_read_and_outline_do_not_import_production_code(tmp_path, newline):
    root = tmp_path / "production"
    root.mkdir()
    code = "raise RuntimeError('must never execute')\nclass Meter:\n    def read_power(self, timeout=1):\n        return 0.0\n"
    code = code.replace("\n", newline)
    (root / "meter.py").write_text(code, encoding="utf-8", newline="\n")
    sources = ReadOnlySources({"src": root})
    evidence = sources.collect(
        [
            {"root": "src", "path": "meter.py", "kind": "outline"},
            {"root": "src", "path": "meter.py", "kind": "read", "start_line": 2, "end_line": 4},
        ]
    )
    assert evidence[0]["sha256"] == hashlib.sha256(code.encode()).hexdigest()
    assert "Meter.read_power" in evidence[0]["content"]
    assert "timeout=1" in evidence[0]["content"]
    assert "class Meter" in evidence[1]["content"]
    assert "RuntimeError" not in evidence[1]["content"]
    assert evidence[1]["start_line"] == 2


@pytest.mark.parametrize(
    "path", ["../outside.py", "..\\outside.py", "/etc/passwd", "C:\\outside.py", "secret.toml"]
)
def test_paths_and_file_types_are_confined(tmp_path, path):
    (tmp_path / "secret.toml").write_text("private material")
    with pytest.raises(SourceContextError):
        ReadOnlySources({"src": tmp_path}).collect([{"root": "src", "path": path, "kind": "read"}])


def test_symlink_cannot_escape_registered_root(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("private material")
    (root / "alias.py").symlink_to(outside)
    with pytest.raises(SourceContextError):
        ReadOnlySources({"src": root}).collect(
            [{"root": "src", "path": "alias.py", "kind": "read"}]
        )


def test_evidence_is_bounded_and_truncation_is_explicit(tmp_path):
    (tmp_path / "guide.md").write_text("\U0001f52c" * 50000, encoding="utf-8")
    evidence = ReadOnlySources({"docs": tmp_path}).collect(
        [{"root": "docs", "path": "guide.md", "kind": "read"} for _ in range(6)]
    )
    assert len(json.dumps(evidence, ensure_ascii=False).encode()) <= 12288
    assert all(e["truncated"] for e in evidence)
    assert all(e["sha256"] for e in evidence)


def test_index_contains_only_supported_files_without_following_directory_links(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "meter.py").write_text("pass\n")
    (root / "secret.yaml").write_text("private material")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "hidden.py").write_text("pass\n")
    (root / "link").symlink_to(outside, target_is_directory=True)
    evidence = ReadOnlySources({"src": root}).collect(
        [{"root": "src", "path": ".", "kind": "index"}]
    )
    assert "meter.py" in evidence[0]["content"]
    assert "secret.yaml" not in evidence[0]["content"]
    assert "hidden.py" not in evidence[0]["content"]


def test_unregistered_roots_are_rejected(tmp_path):
    with pytest.raises(SourceContextError, match="registered"):
        ReadOnlySources({}).collect(
            [{"root": "production_src", "path": "meter.py", "kind": "read"}]
        )


def test_cli_accepts_program_profile_and_exports_valid_analysis_task(tmp_path):
    import yaml
    from labos.source_context import main
    from labos.cooperation_worker import Task

    (tmp_path / "meter.py").write_text(
        "raise RuntimeError('never import')\ndef read_power(): pass\n"
    )
    (tmp_path / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "agent_id": "program-pc-01",
                "token": "p" * 40,
                "server_url": "https://example.org",
                "instruments": [],
            }
        )
    )
    config = tmp_path / "program.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "agent_id": "program-pc-01",
                "connection_config": "agent.yaml",
                "programs": {},
                "source_roots": {"src": "."},
            }
        )
    )
    manifest = tmp_path / "requests.json"
    manifest.write_text(
        json.dumps({"requests": [{"root": "src", "path": "meter.py", "kind": "outline"}]})
    )
    output = tmp_path / "task.json"
    assert (
        main(
            [
                "--profile",
                "program",
                "--config",
                str(config),
                "--requests",
                str(manifest),
                "--output",
                str(output),
                "--as-task",
            ]
        )
        == 0
    )
    task = Task.model_validate_json(output.read_text())
    assert "read_power" in task.context["source_evidence"][0]["content"]

    manifest.write_text(
        json.dumps(
            {
                "requests": [{"root": "src", "path": "meter.py", "kind": "outline"}],
                "instruction": "x" * 8001,
            }
        )
    )
    rejected = tmp_path / "rejected.json"
    assert (
        main(
            [
                "--profile",
                "program",
                "--config",
                str(config),
                "--requests",
                str(manifest),
                "--output",
                str(rejected),
                "--as-task",
            ]
        )
        == 1
    )
    assert not rejected.exists()


@pytest.mark.parametrize("special", ["plain", "\\", '"'])
def test_cli_refuses_export_of_provisioned_credential(tmp_path, special):
    import yaml
    from labos.source_context import main

    token = "private-pc-token-" + special + "s" * 32
    (tmp_path / "guide.md").write_text(token)
    (tmp_path / "agent.yaml").write_text(
        yaml.safe_dump(
            {
                "agent_id": "pc-a",
                "token": token,
                "server_url": "https://example.org",
                "instruments": [],
            }
        )
    )
    (tmp_path / "worker.yaml").write_text(
        yaml.safe_dump(
            {
                "role": "pc",
                "agent_id": "pc-a",
                "connection_config": "agent.yaml",
                "source_roots": {"src": "."},
            }
        )
    )
    (tmp_path / "request.json").write_text(
        json.dumps({"requests": [{"root": "src", "path": "guide.md"}]})
    )
    output = tmp_path / "evidence.json"
    assert (
        main(
            [
                "--config",
                str(tmp_path / "worker.yaml"),
                "--requests",
                str(tmp_path / "request.json"),
                "--output",
                str(output),
            ]
        )
        == 1
    )
    assert not output.exists()


@pytest.mark.parametrize("swap", ["leaf", "parent"])
def test_source_open_is_confined_even_if_path_changes_after_validation(tmp_path, monkeypatch, swap):
    import os

    root = tmp_path / "approved"
    folder = root / "nested"
    folder.mkdir(parents=True)
    target = folder / "meter.py"
    target.write_text("approved = True\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "meter.py"
    secret.write_text("outside_secret = 'must not export'\n")
    sources = ReadOnlySources({"src": root})
    original = os.open
    swapped = False

    def replace_before_open(path, *args, **kwargs):
        nonlocal swapped
        if not swapped and os.fspath(path) == str(target):
            swapped = True
            if swap == "leaf":
                target.unlink()
                target.symlink_to(secret)
            else:
                folder.rename(root / "previous")
                folder.symlink_to(outside, target_is_directory=True)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", replace_before_open)
    with pytest.raises(SourceContextError):
        sources.collect([{"root": "src", "path": "nested/meter.py", "kind": "read"}])
    assert swapped


@pytest.mark.parametrize("directories,count", [(False, 10020), (True, 1020)])
def test_index_bounds_scanned_entries_and_directories(tmp_path, directories, count):
    for i in range(count):
        path = tmp_path / f"entry{i}"
        path.mkdir() if directories else path.touch()
    item = ReadOnlySources({"src": tmp_path}).collect(
        [{"root": "src", "path": ".", "kind": "index"}])[0]
    assert item["truncated"] is True
    assert item["scan"]["entries"] <= 10000
    assert item["scan"]["directories"] <= 1000
    assert item["scan"]["limit"] in {"entries", "directories"}


def test_source_guard_interrupts_scan_and_closes_iterator(tmp_path, monkeypatch):
    import os
    from labos.cooperation_budget import OperationStopped
    for i in range(10):
        (tmp_path / f"entry{i}").touch()
    actual = os.scandir
    opened = []
    def scandir(path):
        iterator = actual(path)
        opened.append(iterator)
        return iterator
    monkeypatch.setattr(os, "scandir", scandir)
    checks = []
    def guard():
        checks.append(1)
        if len(checks) == 12:
            raise OperationStopped("cancelled")
    with pytest.raises(OperationStopped):
        ReadOnlySources({"src": tmp_path}).collect(
            [{"root": "src", "path": ".", "kind": "index"}], guard)
    assert opened
    assert list(opened[0]) == []


def test_outline_bounds_traversal_and_retained_definitions(tmp_path):
    code = "\n".join(f"def function_{i}(): pass" for i in range(3000))
    (tmp_path / "many.py").write_text(code, encoding="utf-8", newline="\n")
    item = ReadOnlySources({"src": tmp_path}).collect(
        [{"root": "src", "path": "many.py", "kind": "outline"}])[0]
    assert item["truncated"]
    assert item["scan"]["nodes"] <= 10000
    assert item["scan"]["definitions"] <= 250
    assert item["sha256"] == hashlib.sha256(code.encode()).hexdigest()


def test_even_internal_source_symlinks_are_rejected(tmp_path):
    (tmp_path / "real.py").write_text("pass")
    (tmp_path / "alias.py").symlink_to(tmp_path / "real.py")
    with pytest.raises(SourceContextError):
        ReadOnlySources({"src": tmp_path}).collect([{"root": "src", "path": "alias.py"}])


def test_outline_stops_on_large_expression_and_omits_large_signature(tmp_path):
    (tmp_path / "nodes.py").write_text("items = [" + "0," * 20000 + "]")
    (tmp_path / "signature.py").write_text("def many(" + ",".join(f"x{i}" for i in range(2000)) + "): pass")
    evidence = ReadOnlySources({"src": tmp_path}).collect([
        {"root": "src", "path": "nodes.py", "kind": "outline"},
        {"root": "src", "path": "signature.py", "kind": "outline"}])
    assert evidence[0]["scan"]["nodes"] == 10000
    assert evidence[0]["scan"]["limit"] == "nodes"
    assert evidence[0]["truncated"]
    assert "signature omitted" in evidence[1]["content"]
    assert evidence[1]["truncated"]


def test_outline_omits_oversize_import_before_rendering(tmp_path, monkeypatch):
    import ast
    (tmp_path / "large.py").write_text("from " + "module" * 1000 + " import value")
    original = ast.unparse
    def bounded_unparse(node):
        if isinstance(node, ast.ImportFrom) and len(node.module) > 4096:
            pytest.fail("Oversize import was rendered before truncation")
        return original(node)
    monkeypatch.setattr(ast, "unparse", bounded_unparse)
    evidence = ReadOnlySources({"src": tmp_path}).collect(
        [{"root": "src", "path": "large.py", "kind": "outline"}])[0]
    assert "import omitted" in evidence["content"]
    assert evidence["truncated"]


def test_outline_marks_shortened_definition_name(tmp_path):
    (tmp_path / "name.py").write_text("def " + "a" * 5000 + "(): pass")
    evidence = ReadOnlySources({"src": tmp_path}).collect(
        [{"root": "src", "path": "name.py", "kind": "outline"}])[0]
    assert evidence["truncated"]
