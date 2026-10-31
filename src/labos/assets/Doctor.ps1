param([string]$Config = 'config.yaml')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath $Config)) { throw 'Missing config.yaml. Obtain a personalized PC configuration from the central server first.' }
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$Python = Get-LabOSPython $PSScriptRoot
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $Python -m labos doctor --config $Config
exit $LASTEXITCODE
