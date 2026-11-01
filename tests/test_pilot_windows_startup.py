"""Execute portable PowerShell scripts with disposable shell and Python boundaries."""

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

import pytest


ASSETS = Path(
    os.environ.get(
        "LABOS_TEST_PILOT_ASSETS", Path(__file__).resolve().parents[1] / "src/labos/assets"
    )
)


@pytest.fixture
def pilot_scripts(tmp_path):
    pwsh = os.environ.get("LABOS_TEST_PWSH") or shutil.which("pwsh")
    if not pwsh or os.name == "nt":
        pytest.skip("Linux PowerShell boundary fixtures; native Windows smoke is separate")
    startup = tmp_path / "mock startup"
    startup.mkdir()
    root = tmp_path / "LabOS (test) 中文"
    root.mkdir()
    for path in ASSETS.glob("*.ps1"):
        shutil.copy(path, root / path.name)
    helper = root / "Pilot-Startup.ps1"
    if helper.exists():
        helper.write_text(
            helper.read_text().replace(
                "[Environment]::GetFolderPath('Startup')", "$env:TEST_STARTUP"
            )
        )
    (root / "python").mkdir()
    fake = root / "fake.py"
    fake.write_text("""import datetime, json, os, pathlib, sys, time
args = sys.argv[1:]
mode = os.environ.get("TEST_MODE", "ready")
if "Check-Pilot-Runtime.py" in " ".join(args):
    sys.exit(7 if mode == "runtime_failure" else 0)
config = pathlib.Path(args[-1])
if not config.is_absolute():
    config = pathlib.Path.cwd() / config
if not config.exists():
    sys.exit(8)
settings = json.loads(config.read_text())
state = config.parent / settings.get("state_dir", "state")
if "-" in args:
    print(json.dumps({"config_sha256": "a" * 64, "state_dir": str(state), "experiment_scope": "dark_a"}))
elif "doctor" in args:
    if mode == "duplicate":
        print("worker already running", file=sys.stderr)
        sys.exit(9)
    print(json.dumps({"authority_ready": mode != "uncommissioned", "profile_ready": mode != "invalid_profile", "configured_approval_enabled": mode != "disabled", "physical_enabled": False, "config_sha256": "b" * 64 if mode == "doctor_mismatch" else "a" * 64, "experiment_scope": "optical_readback" if mode == "scope_mismatch" else "dark_a"}))
elif "stop" in args:
    sys.exit(12 if mode == "stop_failure" else 0)
elif "run" in args:
    if mode == "exit_child":
        print("synthetic child failure", file=sys.stderr)
        sys.exit(23)
    state.mkdir(exist_ok=True)
    payload = {"instance_id": "c" * 32, "launch_id": os.environ.get("LABOS_PILOT_LAUNCH_ID"), "config_sha256": "a" * 64, "pid": os.getpid(), "phase": "started", "snapshot_only": True, "updated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if mode == "wrong_nonce": payload["launch_id"] = "d" * 32
    if mode == "wrong_pid": payload["pid"] += 1
    if mode == "wrong_hash": payload["config_sha256"] = "b" * 64
    if mode == "stale": payload["updated_at_utc"] = "2000-01-01T00:00:00Z"
    if mode == "future": payload["updated_at_utc"] = "2099-01-01T00:00:00Z"
    if mode == "stopped": payload["phase"] = "stopped"
    if mode == "no_utc": payload["updated_at_utc"] = datetime.datetime.now().isoformat()
    if mode == "bad_instance": payload["instance_id"] = "not-a-worker-id"
    if mode == "not_snapshot": payload["snapshot_only"] = False
    (state / "status.json").write_text(json.dumps(payload))
    time.sleep(3)
""")
    python = root / "python/python.exe"
    python.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(fake))} "$@"\n'
    )
    python.chmod(0o755)
    for profile in ("one profile.json", "two profile.json"):
        (root / profile).write_text(json.dumps({"state_dir": profile + ".state"}))
    runner = tmp_path / "runner.ps1"
    runner.write_text(r"""$PSNativeCommandArgumentPassing = 'Legacy'
$env:SystemRoot = '/mock Windows'
function global:New-Object {
    param([string]$ComObject)
    if ($ComObject -ne 'WScript.Shell') { throw 'Unexpected COM request' }
    $shell = [pscustomobject]@{}
    $shell | Add-Member ScriptMethod CreateShortcut {
        param($path)
        $item = [pscustomobject]@{ Path = $path; TargetPath = ''; Arguments = ''; WorkingDirectory = ''; WindowStyle = 7; Description = '' }
        if (Test-Path -LiteralPath $path) {
            $saved = Get-Content -Raw -LiteralPath $path | ConvertFrom-Json
            $item.TargetPath = $saved.TargetPath; $item.Arguments = $saved.Arguments
        }
        $item | Add-Member ScriptMethod Save { $this | ConvertTo-Json | Set-Content -LiteralPath $this.Path }
        return $item
    }
    return $shell
}
function global:Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$PassThru, $RedirectStandardOutput, $RedirectStandardError)
    if ($FilePath -like '*powershell.exe') { return }
    $parameters = @{ FilePath=$FilePath; ArgumentList=$ArgumentList; WorkingDirectory=$WorkingDirectory; PassThru=$PassThru }
    if ($RedirectStandardOutput) { $parameters.RedirectStandardOutput=$RedirectStandardOutput }
    if ($RedirectStandardError) { $parameters.RedirectStandardError=$RedirectStandardError }
    Microsoft.PowerShell.Management\Start-Process @parameters
}
# Redirect only Startup folder discovery; never access the user's real startup.
$scriptText = Get-Content -Raw -LiteralPath $env:TEST_SCRIPT
$scriptText = $scriptText.Replace("[Environment]::GetFolderPath('Startup')", '$env:TEST_STARTUP')
$scriptPath = Join-Path (Split-Path $env:TEST_SCRIPT) 'fixture-entry.ps1'
Set-Content -LiteralPath $scriptPath -Value $scriptText
& $scriptPath @args
exit $LASTEXITCODE
""")

    def run(script, profile="one profile.json", mode="ready", disable=False, root_dir=None):
        directory = root_dir or root
        args = [pwsh, "-NoProfile", "-File", str(runner), "-Config", profile]
        if script in {"Start-Pilot.ps1", "Install-Pilot.ps1"}:
            args += ["-ReadinessTimeoutSeconds", "1"]
        if disable:
            args.append("-DisableStartup")
        return subprocess.run(
            args,
            env={
                **os.environ,
                "TEST_MODE": mode,
                "TEST_SCRIPT": str(directory / script),
                "TEST_STARTUP": str(startup),
            },
            capture_output=True,
            text=True,
            timeout=15,
        )

    yield root, startup, run
    # Harmless fixtures exit on their own; allow subprocess pipes/files to settle.
    time.sleep(3)


def test_install_and_disable_keep_profiles_and_installations_separate(pilot_scripts, tmp_path):
    root, startup, run = pilot_scripts
    other = tmp_path / "other installation"
    shutil.copytree(root, other)
    for directory, profile in [
        (root, "one profile.json"),
        (root, "two profile.json"),
        (other, "one profile.json"),
    ]:
        result = run("Install-Pilot.ps1", profile, root_dir=directory)
        assert result.returncode == 0, result.stdout + result.stderr
    links = list(startup.glob("*.lnk"))
    assert len(links) == 3
    logs = list((root / "logs").glob("physical-pilot-*/*.stdout.log"))
    assert len(logs) == 2
    result = run("Stop-Pilot.ps1", disable=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(list(startup.glob("*.lnk"))) == 2


@pytest.mark.parametrize(
    "failure", ["missing_python", "missing_config", "malformed_config", "stop_failure"]
)
def test_disable_startup_attempts_owned_removal_after_stop_failure(pilot_scripts, failure):
    root, startup, run = pilot_scripts
    result = run("Install-Pilot.ps1")
    assert result.returncode == 0, result.stdout + result.stderr
    if failure == "missing_python":
        (root / "python/python.exe").unlink()
    if failure == "missing_config":
        (root / "one profile.json").unlink()
    if failure == "malformed_config":
        (root / "one profile.json").write_text("invalid JSON")
    result = run("Stop-Pilot.ps1", mode=failure, disable=True)
    assert result.returncode != 0
    assert not list(startup.glob("*.lnk"))
    if failure == "stop_failure":
        assert result.returncode == 12


def test_unrelated_legacy_shortcut_is_preserved(pilot_scripts):
    _, startup, run = pilot_scripts
    legacy = startup / "LabOS-Physical-Pilot.lnk"
    legacy.write_text(json.dumps({"TargetPath": "other.exe", "Arguments": "other profile"}))
    before = legacy.read_bytes()
    assert run("Stop-Pilot.ps1", disable=True).returncode == 0
    assert legacy.read_bytes() == before


@pytest.mark.parametrize(
    "mode",
    [
        "disabled",
        "invalid_profile",
        "uncommissioned",
        "doctor_mismatch",
        "scope_mismatch",
        "duplicate",
    ],
)
def test_precheck_refuses_unready_or_duplicate_worker(pilot_scripts, mode):
    root, startup, run = pilot_scripts
    result = run("Install-Pilot.ps1", mode=mode)
    assert result.returncode != 0
    assert not list(startup.glob("*.lnk"))
    assert not list(root.glob("**/status.json"))
    assert (
        "Doctor" in result.stdout + result.stderr
        or "already running" in result.stdout + result.stderr
    )


@pytest.mark.parametrize(
    "mode",
    [
        "wrong_nonce",
        "wrong_pid",
        "wrong_hash",
        "stale",
        "future",
        "stopped",
        "no_utc",
        "bad_instance",
        "not_snapshot",
        "exit_child",
    ],
)
def test_launch_requires_own_fresh_running_child(pilot_scripts, mode):
    _, startup, run = pilot_scripts
    result = run("Install-Pilot.ps1", mode=mode)
    assert result.returncode != 0
    assert not list(startup.glob("*.lnk"))
    assert "readiness" in result.stdout + result.stderr or "exited" in result.stdout + result.stderr
    if mode == "exit_child":
        assert result.returncode == 23


def test_start_reports_fresh_child_without_treating_inspection_as_physical_on(pilot_scripts):
    _, _, run = pilot_scripts
    result = run("Start-Pilot.ps1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "readiness verified" in result.stdout
    assert "output state" in result.stdout


@pytest.mark.parametrize("operation", ["Install-Pilot.ps1", "Stop-Pilot.ps1"])
def test_owned_legacy_shortcut_is_migrated_or_disabled(pilot_scripts, operation):
    _, startup, run = pilot_scripts
    result = run("Install-Pilot.ps1")
    assert result.returncode == 0, result.stdout + result.stderr
    owned = next(startup.glob("*.lnk"))
    legacy = startup / "LabOS-Physical-Pilot.lnk"
    owned.rename(legacy)
    result = run(operation, disable=operation == "Stop-Pilot.ps1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not legacy.exists()
    assert len(list(startup.glob("*.lnk"))) == (1 if operation == "Install-Pilot.ps1" else 0)


def test_foreign_hashed_shortcut_cannot_be_overwritten_or_removed(pilot_scripts):
    _, startup, run = pilot_scripts
    assert run("Install-Pilot.ps1").returncode == 0
    owned = next(startup.glob("*.lnk"))
    owned.write_text(json.dumps({"TargetPath": "unrelated.exe", "Arguments": "different"}))
    before = owned.read_bytes()
    assert run("Install-Pilot.ps1").returncode != 0
    assert run("Stop-Pilot.ps1", disable=True).returncode == 0
    assert owned.read_bytes() == before


def test_pilot_scripts_parse_with_available_powershell(pilot_scripts):
    root, _, run = pilot_scripts
    parser = root / "Parse-Pilot.ps1"
    parser.write_text("""$ErrorActionPreference = 'Stop'
foreach ($name in @('Install-Pilot.ps1', 'Start-Pilot.ps1', 'Stop-Pilot.ps1', 'Pilot-Startup.ps1')) {
    $tokens = $null; $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $name), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
}
exit 0
""")
    result = run(parser.name)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("mode,expected", [("runtime_failure", 7), ("duplicate", 9)])
def test_start_preserves_failed_native_precheck_exit_code(pilot_scripts, mode, expected):
    _, startup, run = pilot_scripts
    result = run("Install-Pilot.ps1", mode=mode)
    assert result.returncode == expected, result.stdout + result.stderr
    assert not list(startup.glob("*.lnk"))


def test_readiness_timeout_leaves_child_running_for_cooperative_inspection(pilot_scripts):
    root, _, run = pilot_scripts
    result = run("Start-Pilot.ps1", mode="wrong_nonce")
    assert result.returncode == 1, result.stdout + result.stderr
    status = json.loads((root / "one profile.json.state/status.json").read_text())
    os.kill(status["pid"], 0)
    assert "Child was not terminated" in result.stdout
    assert "output state remains unknown" in result.stdout


@pytest.mark.parametrize("script", ["Start-Pilot.ps1", "Install-Pilot.ps1"])
def test_venv_redirector_is_refused_before_worker_or_shortcut_creation(pilot_scripts, script):
    root, startup, run = pilot_scripts
    venv = root / ".venv/Scripts"
    venv.mkdir(parents=True)
    (root / "python/python.exe").rename(venv / "python.exe")
    result = run(script)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "embedded" in result.stdout + result.stderr
    assert not list(root.glob("**/status.json"))
    assert not (root / "logs").exists()
    assert not list(startup.glob("*.lnk"))
