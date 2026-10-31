param([string]$Config = 'cooperation.yaml', [switch]$DisableStartup)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$Python = Get-LabOSPython $PSScriptRoot
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $Python -B -m labos.cooperation_worker stop --config $Config
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
if ($DisableStartup) {
    $Shortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'LabOS-Cooperation.lnk'
    if (Test-Path -LiteralPath $Shortcut) { Remove-Item -LiteralPath $Shortcut }
    Write-Host 'Current-user automatic startup disabled.'
}
