# GitHub delivery and PC updates

Repository: **https://github.com/Yue-fy/labos** (public, as authorized by the operator).

GitHub distributes source, English instructions and versioned packages. Existing
authenticated HTTPS correspondence carries operational reports and raw artifacts.
A Git commit or package installation does not grant hardware authority.

## Choose the intended release

**v0.2.8 is the older stable release.** Its package version is `0.2.8`; it does
not include the candidate's new physical authority and recovery behavior.
Its existing assets remain available and unchanged. Do not use its instructions
as authority to activate a new candidate physical worker.

The maintenance candidate is **0.2.9rc1**, tag **v0.2.9-rc.1**, on source branch
`maintenance/reliability-0.2.9rc1`. Read the
[candidate release notes](https://github.com/Yue-fy/labos/blob/v0.2.9-rc.1/docs/RELEASE_0.2.9rc1_EN.md) and
[integrated validation report](https://github.com/Yue-fy/labos/blob/v0.2.9-rc.1/docs/validation/2026-11-01-0.2.9rc1-integrated.md).
Final package/review/publication acceptance is recorded in the external
`QA_Report.json`; download links become available when the candidate is published.
Candidate publication is separate from stable promotion, main-branch merge,
live deployment and onsite commissioning.

## Read source without changing an installation

Git for Windows can read this public repository without signing in. Use a new
directory separate from the working portable runtime and vendor environment:

```powershell
git clone --branch maintenance/reliability-0.2.9rc1 --single-branch https://github.com/Yue-fy/labos.git C:\LabOS\candidate-repository
Set-Location C:\LabOS\candidate-repository
git status --short
git log -1 --oneline
```

The candidate branch can receive reviewed changes. Match the exact published
commit/tag and release manifest before staging software. For later source
updates, inspect `git status --short`, then use `git pull --ff-only`; preserve
local edits and report conflicts. Do not reset or delete local work. A source
pull does not update a separate portable runtime, install dependencies, restart
a worker or enable an instrument.

Pushing requires a locally configured GitHub account with write access. Never
copy a central GitHub or operator credential to a PC. A source clone has no live
`config.yaml`, portable runtime or PC credentials. Keep all such local files,
journals and raw data out of GitHub.

## Download and verify the candidate overlay

After the candidate is published, use a fresh directory. The small overlay
requires an existing provisioned runtime; a new Windows PC instead needs
`LabOS-Agent-Windows-x64-0.2.9rc1.zip` and its own provisioned configuration.
The generic Agent/Central packages are listed in the release notes.

```powershell
$ReleaseDir = 'C:\LabOS\updates\v0.2.9-rc.1-new-001'
if (Test-Path -LiteralPath $ReleaseDir) { throw 'Use a new update directory.' }
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null
$Archive = Join-Path $ReleaseDir 'LabOS-Cryostat-Physical-Update-0.2.9rc1.zip'
$ReleaseURL = 'https://github.com/Yue-fy/labos/releases/download/v0.2.9-rc.1'
Invoke-WebRequest -UseBasicParsing -Uri ($ReleaseURL + '/LabOS-Cryostat-Physical-Update-0.2.9rc1.zip') -OutFile $Archive
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

A browser can download the same public assets without signing in. Compare the
published checksum and QA evidence for the exact candidate. Checksums verify
integrity, not independent authorization or a signature. Never use overwrite
switches on an existing installation, package or evidence directory.

## Stage central and PC updates; commission later

The operator/trusted local assistant must coordinate central and selected PC
upgrades. An old 0.2.8 central cannot grant the candidate's new physical
authority. The new authority starts **uncommissioned**. Updated physical workers
fail closed against old/missing endpoints, profile mismatches and ambiguous
receipts. Do not start physical workers as part of package staging.

Read [PORTABLE_UPDATE_RECOVERY_EN.md](PORTABLE_UPDATE_RECOVERY_EN.md) before
applying the overlay. Stop and freeze all declared report, program and physical
workers, preserving live configuration, approval, journals, raw artifacts and
backups. Declare nested/external profiles as the guide requires. Use the actual
existing independently trusted interpreter with `-I`; neither apply nor recovery
starts a worker or imports installed/overlay LabOS code. The updater refuses
active declared locks and retains verified originals; unknown edits require
reconciliation. It cannot prevent an unrelated copied worker from being launched.

Later onsite, follow [ONSITE_COMMISSIONING_EN.md](ONSITE_COMMISSIONING_EN.md)
and [PHYSICAL_AUTHORITY_EN.md](PHYSICAL_AUTHORITY_EN.md): inventory and retire
legacy binaries/launchers/scheduled tasks, reconcile old outcomes, inspect
current wiring and calibration prerequisites, freeze the selected enabled
profile and referenced files, and run the applicable output-preserving preflight.
Operator commissioning retires all historical pilot task IDs and takes a new
cutoff. Only a separately authorized new finite task can then be considered.
Never replay an old failed or scope-less task. Installation never enables
measurement, changes local approval or queues a physical task.

## Responsibilities and limits

Central prepares reviewed source, candidate assets/checksums and evidence. The
PC assistant fetches the pinned version, preserves station state, follows the
coordinated maintenance/onsite procedures and sends factual results through the
existing authenticated channel. A report-only worker cannot silently install
software or acquire instrument authority.

Protect outputs and reconcile the physical executor before changing its code.
Keep UNKNOWN outcomes and backup/journal evidence; resetting source or
reinstalling software is not physical reconciliation. Preserve the working
vendor/lyr environment. GitHub is not an emergency-stop or real-time control
mechanism. Local protection and independent interlocks remain necessary.
