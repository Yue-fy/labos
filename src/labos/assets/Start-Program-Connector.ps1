param([string]$Config = 'program-connector.yaml')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$Python = Get-LabOSPython $PSScriptRoot
if (-not (Test-Path -LiteralPath $Config)) { throw 'Missing program-connector.yaml. Read PROGRAM_CONNECTOR_EN.md.' }
$ConfigPath = (Resolve-Path -LiteralPath $Config).Path
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
$LogPath = Join-Path $PSScriptRoot 'program-connector.log'
& $Python -B -u -m labos.program_connector run --config $ConfigPath 1>> $LogPath 2>&1
exit $LASTEXITCODE
