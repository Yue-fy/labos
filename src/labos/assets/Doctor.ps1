param([string]$Config = 'config.yaml')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$Python = Get-LabOSPython $PSScriptRoot
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $Python -m labos doctor --config $Config
exit $LASTEXITCODE
