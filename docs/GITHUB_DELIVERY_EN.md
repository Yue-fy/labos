# Private GitHub delivery and PC updates

Repository: **https://github.com/Yue-fy/labos** (private).

GitHub distributes source, English operating instructions and versioned packages.
The existing authenticated HTTPS channel carries operational correspondence,
finite experiment tasks, readbacks and raw artifacts. A Git commit is not an
instrument command and does not grant new local hardware authority.

## One-time setup on a laboratory PC

Install Git for Windows and, for command-line release downloads, GitHub CLI.
Authenticate on that PC as Yue-fy or an account already granted repository access:

```powershell
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
gh repo clone Yue-fy/labos C:\LabOS\repository
Set-Location C:\LabOS\repository
gh repo view Yue-fy/labos --json nameWithOwner,isPrivate
```

Complete browser/device authentication locally. Never copy the server's GitHub
credential or LabOS operator credential to the PC. If an account lacks access,
the owner must grant access or sign in locally with an authorized account. The
repository and releases remain private; a release URL does not grant access.

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

The first physical overlay is version **0.2.5**. It includes the LabOS-owned
executor, pure Python VISA/serial dependencies, a disabled commissioning template,
the verified overlay updater and START_HERE_PHYSICAL_PILOT_EN.md.

```powershell
$ReleaseDir = 'C:\LabOS\updates\v0.2.5'
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
gh release download v0.2.5 --repo Yue-fy/labos `
  --pattern LabOS-Cryostat-Physical-Update-0.2.5.zip `
  --pattern SHA256SUMS --dir $ReleaseDir
if ($LASTEXITCODE -ne 0) { throw 'Release download failed; check GitHub access.' }
$Archive = Join-Path $ReleaseDir 'LabOS-Cryostat-Physical-Update-0.2.5.zip'
$ChecksumLines = @(Get-Content -LiteralPath (Join-Path $ReleaseDir 'SHA256SUMS') | Where-Object {
  $_ -match '^[a-fA-F0-9]{64}  LabOS-Cryostat-Physical-Update-0\.2\.5\.zip$'
})
if ($ChecksumLines.Count -ne 1) { throw 'Expected checksum entry is missing or ambiguous.' }
$Expected = ($ChecksumLines[0] -split '\s+')[0]
$Actual = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash
if ($Actual -ne $Expected) { throw 'Package checksum mismatch; do not install.' }
Expand-Archive -LiteralPath $Archive -DestinationPath (Join-Path $ReleaseDir 'extracted')
```

If that download/extraction directory already exists, inspect it and use a new
directory; do not use overwrite/force switches on an installation or old evidence.
An authenticated browser can download the same assets if GitHub CLI is unavailable.

Follow the extracted **START_HERE_PHYSICAL_PILOT_EN.md**. Cooperatively stop the
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

PC assistant: fetch the pinned version using its own GitHub access, preserve
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
