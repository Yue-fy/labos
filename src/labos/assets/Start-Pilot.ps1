param([string]$Config = 'pilot-worker.yaml')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$Python = Get-LabOSPython $PSScriptRoot
$ConfigPath = (Resolve-Path -LiteralPath $Config).Path
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $Python -B -u -m labos.pilot_worker run --config $ConfigPath 1>> (Join-Path $PSScriptRoot 'physical-pilot.log') 2>&1
exit $LASTEXITCODE
