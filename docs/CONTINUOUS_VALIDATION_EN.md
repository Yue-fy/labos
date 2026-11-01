# Continuous validation

The `Validation` GitHub Actions workflow runs on pushes, pull requests, and manual
dispatch. It uses read-only repository contents permission, does not retain checkout
credentials, and pins official actions to immutable commits. Each job has a
25-minute timeout; newer runs cancel older runs for the same branch or pull request.
It does not deploy, release, provision a PC, use provider credentials, or access
production services or instruments.

## Unit and lint matrix

Ubuntu and Windows each run Python 3.11 and 3.14 with the project's central and
development dependencies. Each cell runs:

```console
python -m ruff check src tests scripts
python -m pytest -ra --junitxml=validation-logs/pytest.xml
```

The console log and JUnit report retain skip reasons. Windows intentionally skips
the Linux PowerShell shim fixtures; Linux descriptor accounting is also skipped
on Windows. Linux PowerShell fixture tests require `pwsh` on the runner's PATH
(or `LABOS_TEST_PWSH`); their skip reason is visible if it is unavailable. Those
fixtures exercise portable script boundaries and do not establish native Windows
runtime compatibility.

## Native Windows delivery

A separate Windows job uses Windows PowerShell 5.1 (`powershell.exe`) to:

1. Run `scripts/build_windows_runtime.py`, downloading the actual official Python
   3.14.8 x64 embedded ZIP, checking its pinned SHA-256, and downloading fresh binary
   wheels from the shipped `requirements-agent.txt`.
2. Run `scripts/build_delivery.py` to create the current generic delivery ZIPs and
   `SHA256SUMS` in a fresh `dist/ci` directory. Check that the native-built Central
   ZIP contains LF shell scripts (including their shebangs) and that every packaged
   Python source file exactly matches its Git blob. The repository's
   `.gitattributes` forces LF for detected text on every host while preserving binary
   assets; Windows Git's `core.autocrlf` setting cannot rewrite packaged source.
3. Run `scripts/verify_windows_delivery.ps1` against the exact new
   `LabOS-Agent-Windows-x64-0.2.9rc1.zip`. The script extracts to a temporary path
   containing spaces, parentheses, and Chinese characters. It parses every shipped
   `.ps1` file recursively, including `Pilot-Startup.ps1`, using the running
   PowerShell parser. It then runs both the PowerShell installer and `Install.cmd`
   from that path. The batch installer receives stdin from `NUL` so its `pause`
   cannot block. It runs the embedded `python/python.exe`, checks CLI help, and
   verifies that Doctor and Agent startup reject the absent PC configuration. It
   does not start an Agent or central server.

To reproduce on a Windows machine from a source checkout with Python and the
project dependencies already installed, use Windows PowerShell 5.1:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python scripts/build_windows_runtime.py
python scripts/build_delivery.py --output dist/ci --windows-runtime dist/delivery/windows-x64-runtime.zip
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/verify_windows_delivery.ps1 -Archive dist/ci/LabOS-Agent-Windows-x64-0.2.9rc1.zip -LogDirectory validation-logs
```

The builders refuse to overwrite outputs. For another attempt, use a fresh checkout
or move the previous generated outputs aside first. Never replace the generic ZIP
with a personalized bundle or supply a real configuration for this check.

## Evidence and limits

The workflow retains dependency, lint, test, runtime-build, smoke, and installer
logs for seven days, including on failure when available. `source-bytes.log`
records the native Central ZIP's portable source checks. The native artifact also
contains the newly built generic release ZIPs, `dist/ci/SHA256SUMS`, and the exact
`dist/delivery/windows-x64-runtime.zip` used by the delivery builder. Its provenance
is copied from the runtime ZIP to `validation-logs/RUNTIME_PROVENANCE.json`, and
`validation-logs/runtime-SHA256SUMS` records that runtime ZIP's SHA-256. These files
allow reviewers to identify and inspect the tested build inputs. It never uploads
the extracted temporary directory, a personalized bundle, or a PC configuration.
`-LogDirectory` writes the smoke transcript and copies the installer log to the specified
directory; the extracted delivery and original logs remain in the reported temporary
path for local inspection.

The source candidate is `0.2.9rc1`. A local Linux test run or PowerShell Core parse
does not prove Windows PowerShell 5.1 or embedded Windows execution passed. Inspect
the Actions run for the reviewed commit and each matrix cell before recording
native success. A successful workflow establishes offline software and generic
delivery checks only; onsite commissioning and hardware validation remain separate
release gates.
