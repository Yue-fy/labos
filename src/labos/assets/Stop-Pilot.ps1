param([string]$Config = 'pilot-worker.yaml', [switch]$DisableStartup)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$Python = Get-LabOSPython $PSScriptRoot
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $Python -B -m labos.pilot_worker stop --config $Config
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($DisableStartup) {
    $Shortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'LabOS-Physical-Pilot.lnk'
    if (Test-Path -LiteralPath $Shortcut) { Remove-Item -LiteralPath $Shortcut }
}
Write-Host 'Cooperative stop requested. Inspect final protection readbacks; this is not a hardware emergency stop.'
