# GitHub delivery and PC updates

Repository: **https://github.com/Yue-fy/labos** (public, as authorized by the operator).

GitHub distributes source, English operating instructions and versioned packages.
The existing authenticated HTTPS channel carries operational correspondence,
finite experiment tasks, readbacks and raw artifacts. A Git commit is not an
instrument command and does not grant new local hardware authority.

## One-time setup on a laboratory PC

Install Git for Windows. Reading this public repository and downloading release
packages requires no GitHub sign-in:

```powershell
git clone https://github.com/Yue-fy/labos.git C:\LabOS\repository
Set-Location C:\LabOS\repository
git log -1 --oneline
```

Pushing changes requires a GitHub account with write access; configure that
account locally when needed. Never copy the server's GitHub or LabOS operator
credential to the PC. Public code/package access does not grant access to the
authenticated runtime API. Live settings, journals and raw data remain local.

Keep the clone separate from the existing provisioned LabOS runtime. A clone has
source and examples, not live config.yaml, portable Python or PC credentials.
It does not replace the working vendor/lyr environment.

## Get future changes

```powershell
Set-Location C:\LabOS\repository
git status --short
git pull --ff-only
git log -1 --oneline
```

If local edits or divergent history block the pull, preserve them and report the
conflict; do not reset or delete local work. Read the release notes and use the
matching versioned package for deployment. Source pull alone does not update a
separate portable runtime, install dependencies or restart a worker.

## Download the cryostat physical update

The current physical overlay is version **0.2.7**, adding a dedicated dark a-axis voltage profile with no chopper/PM/XY/AUX
access. The earlier two-SR830 optical profile remains available for separately
commissioned use. It includes the LabOS-owned
executor, pure Python VISA/serial dependencies, a disabled commissioning template,
the verified overlay updater and START_HERE_PHYSICAL_PILOT_EN.md.

```powershell
$ReleaseDir = 'C:\LabOS\updates\v0.2.7'
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
$Archive = Join-Path $ReleaseDir 'LabOS-Cryostat-Physical-Update-0.2.7.zip'
$ReleaseURL = 'https://github.com/Yue-fy/labos/releases/download/v0.2.7'
Invoke-WebRequest -UseBasicParsing -Uri ($ReleaseURL + '/LabOS-Cryostat-Physical-Update-0.2.7.zip') -OutFile $Archive
Invoke-WebRequest -UseBasicParsing -Uri ($ReleaseURL + '/SHA256SUMS') -OutFile (Join-Path $ReleaseDir 'SHA256SUMS')
$ChecksumLines = @(Get-Content -LiteralPath (Join-Path $ReleaseDir 'SHA256SUMS') | Where-Object {
  $_ -match ('^[a-fA-F0-9]{64}  ' + [regex]::Escape([IO.Path]::GetFileName($Archive)) + '$')
})
if ($ChecksumLines.Count -ne 1) { throw 'Expected checksum entry is missing or ambiguous.' }
$Expected = ($ChecksumLines[0] -split '\s+')[0]
$Actual = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash
if ($Actual -ne $Expected) { throw 'Package checksum mismatch; do not install.' }
Expand-Archive -LiteralPath $Archive -DestinationPath (Join-Path $ReleaseDir 'extracted')
```

If that download/extraction directory already exists, inspect it and use a new
directory; do not use overwrite/force switches on an installation or old evidence.
A browser can download the same assets without signing in. GitHub CLI remains an
optional alternative for users who already have it configured.

For the current short test, follow **DARK_A_SHORT_TEST_EN.md** in the extracted
overlay or repository. **START_HERE_PHYSICAL_PILOT_EN.md** also links to it. Cooperatively stop the
old worker, apply the verified overlay to the actual existing LabOS installation,
preserve all local configuration/state, and restart report cooperation. The
updater refuses active worker locks and saves replaced files in a local backup.
The small overlay requires the existing portable runtime; a new PC instead needs
the full Windows x64 package and its own provisioned configuration.

Do not overwrite live settings with repository examples. Fill actual local
resource bindings, run the output-preserving preflight and send its JSON through
HTTPS. Enable the separate physical worker only after a PASSED preflight within
the operator's established scope. Central queues the finite pilot after reviewing
the returned evidence. Installing or pulling a version never starts a measurement.

## Responsibilities

Central assistant: implement and verify changes, push source, publish versioned
assets with checksums, notify the PC over existing correspondence, and inspect
returned commissioning/measurement evidence.

PC assistant: fetch the pinned public version, preserve
configuration and production files, perform the documented local update/preflight,
and send factual results. The existing report-only worker cannot silently install
software or acquire instrument capabilities. A trusted local assistant/operator
performs that commissioning step; GitHub publication does not make it automatic.

Do not hot-update a running acquisition. Protect outputs and finish/reconcile the
physical worker before changing its code. Keep UNKNOWN outcomes, journals and
backup evidence; a Git reset or reinstallation is not physical reconciliation.

GitHub is not a real-time control or emergency-stop mechanism. Shutdown deadlines,
power/current guards and independent laser/minimum-excitation protection remain
local to the physical executor regardless of repository/network availability.
