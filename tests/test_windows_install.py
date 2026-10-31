"""Execute the shipped scripts, including Windows PowerShell's legacy quoting.

On Linux the executable shim substitutes only the Windows Python binary; the
PowerShell scripts, Python checks and unpacked LabOS modules are the real ones.
The actual Windows runtime has a separate Windows smoke check.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
import zipfile

import pytest

from labos.delivery import write_package


@pytest.fixture
def windows_package(tmp_path):
    powershell = os.environ.get("LABOS_TEST_PWSH") or shutil.which("pwsh")
    if not powershell or os.name == "nt":
        pytest.skip("requires PowerShell Core on Linux; use Windows smoke check on Windows")
    package_dir = tmp_path / "LabOS cavity (test) 中文"
    package_dir.mkdir()
    archive = tmp_path / "agent.zip"
    with zipfile.ZipFile(archive, "w") as package:
        write_package(package, "agent")
    with zipfile.ZipFile(archive) as package:
        package.extractall(package_dir)
    python = package_dir / "python" / "python.exe"
    python.parent.mkdir()
    python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    python.chmod(0o755)
    runner = tmp_path / "run.ps1"
    runner.write_text(
        "$PSNativeCommandArgumentPassing = 'Legacy'\n& $env:LABOS_TEST_SCRIPT\nexit $LASTEXITCODE\n"
    )

    def run(script):
        env = {
            **os.environ,
            "LABOS_TEST_SCRIPT": str(package_dir / script),
            "PYTHONPATH": str(package_dir / "src"),
        }
        return subprocess.run(
            [powershell, "-NoProfile", "-File", str(runner)],
            env=env,
            capture_output=True,
            text=True,
            timeout=40,
        )

    return package_dir, run


def test_portable_install_runs_with_legacy_powershell_and_complex_path(windows_package):
    _, run = windows_package
    result = run("Install.ps1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "runtime OK" in result.stdout


def test_install_explains_missing_provisioning_and_preserves_diagnostics(windows_package):
    package_dir, run = windows_package
    result = run("Install.ps1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "config.yaml" in result.stdout
    assert "personalized" in result.stdout.lower()
    log = package_dir / "install.log"
    assert log.is_file()
    assert "runtime OK" in log.read_text(encoding="utf-8-sig")


def test_install_rejects_an_incomplete_agent_even_if_top_level_imports_work(windows_package):
    package_dir, run = windows_package
    (package_dir / "src/labos/agent.py").unlink()
    result = run("Install.ps1")
    assert result.returncode != 0
    assert "labos.agent" in result.stdout + result.stderr


def test_doctor_explains_missing_pc_configuration(windows_package):
    _, run = windows_package
    result = run("Doctor.ps1")
    assert result.returncode != 0
    assert "config.yaml" in result.stdout + result.stderr
    assert "personalized" in (result.stdout + result.stderr).lower()


@pytest.mark.parametrize(
    "script,config_name,module",
    [
        ("Start-Cooperation.ps1", "cooperation.yaml", "labos.cooperation_worker"),
        ("Start-Program-Connector.ps1", "program-connector.yaml", "labos.program_connector"),
        ("Start-Pilot.ps1", "pilot-worker.yaml", "labos.pilot_worker"),
    ],
)
def test_worker_start_passes_complex_config_path_as_one_argument(
    windows_package, script, config_name, module
):
    package_dir, run = windows_package
    (package_dir / config_name).write_text(
        "role: pc\nagent_id: pc-a\nconnection_config: config.yaml\n"
    )
    capture = package_dir / "capture.py"
    capture.write_text(
        "import json, pathlib, sys\npathlib.Path(__file__).with_name('args.json').write_text(json.dumps(sys.argv[1:]))\n"
    )
    python = package_dir / "python/python.exe"
    python.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(capture))} "$@"\n'
    )
    result = run(script)
    assert result.returncode == 0, result.stdout + result.stderr
    args = json.loads((package_dir / "args.json").read_text())
    assert args == ["-B", "-u", "-m", module, "run", "--config", str(package_dir / config_name)]


@pytest.mark.parametrize(
    "script,config_name,state",
    [
        ("Stop-Cooperation.ps1", "cooperation.yaml", "cooperation"),
        ("Stop-Program-Connector.ps1", "program-connector.yaml", "program-connector"),
        ("Stop-Pilot.ps1", "pilot-worker.yaml", "physical-pilot"),
    ],
)
def test_worker_stop_writes_request_without_opening_transport(
    windows_package, script, config_name, state
):
    package_dir, run = windows_package
    (package_dir / config_name).write_text(
        f"role: pc\nagent_id: pc-a\nconnection_config: nonexistent.yaml\nstate_dir: data/{state}\n"
    )
    result = run(script)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (package_dir / f"data/{state}/stop.request").read_text().strip() == "stop"


def test_physical_runtime_check_uses_a_file_and_legacy_quoting(windows_package):
    package_dir, run = windows_package
    # The real Windows NI-VISA backend is checked only on the commissioned PC.
    for name in ("pyvisa", "serial"):
        (package_dir / f"src/{name}.py").write_text("# local import fixture\n")
    wrapper = package_dir / "Check-Pilot-Test.ps1"
    wrapper.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'\n"
        "& (Join-Path $PSScriptRoot 'python/python.exe') -B (Join-Path $PSScriptRoot 'Check-Pilot-Runtime.py')\n"
        "exit $LASTEXITCODE\n"
    )
    result = run(wrapper.name)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no instruments opened" in result.stdout
    assert "-c " not in (package_dir / "Install-Pilot.ps1").read_text()
