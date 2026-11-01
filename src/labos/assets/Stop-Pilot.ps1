param([string]$Config = 'pilot-worker.yaml', [switch]$DisableStartup)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'Pilot-Startup.ps1')
$Result = 0
try {
    . (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
    $Python = Get-LabOSPython $PSScriptRoot
    $env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
    & $Python -B -m labos.pilot_worker stop --config $Config
    $Result = $LASTEXITCODE
    if ($Result -eq 0) { Write-Host 'Cooperative stop requested. Inspect final protection readbacks; this is not a hardware emergency stop.' }
} catch {
    $Result = 1
    Write-Warning ('Cooperative stop failed: ' + $_.Exception.Message)
} finally {
    if ($DisableStartup) {
        try { Remove-LabOSPilotStartup (Get-LabOSPilotIdentity $PSScriptRoot $Config) }
        catch {
            Write-Warning ('Startup removal failed: ' + $_.Exception.Message)
            if ($Result -eq 0) { $Result = 1 }
        }
    }
}
exit $Result
