param([string]$Config = 'config.yaml')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$Python = Get-LabOSPython $PSScriptRoot
if (-not (Test-Path -LiteralPath $Config)) { throw 'Missing config.yaml. Obtain a personalized PC bundle from central provisioning.' }
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $Python -m labos agent --config $Config
exit $LASTEXITCODE
