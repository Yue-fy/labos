param([string]$Config = 'cooperation.yaml')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$Python = Get-LabOSPython $PSScriptRoot
if (-not (Test-Path -LiteralPath $Config)) { throw 'Missing cooperation.yaml. Read AUTOMATIC_COOPERATION_EN.md.' }
$ConfigPath = (Resolve-Path -LiteralPath $Config).Path
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$LogPath = Join-Path $PSScriptRoot 'cooperation-worker.log'
& $Python -B -u -m labos.cooperation_worker run --config $ConfigPath 1>> $LogPath 2>&1
exit $LASTEXITCODE
