param([string]$Config = 'pilot-worker.yaml', [ValidateRange(1, 120)][int]$ReadinessTimeoutSeconds = 15)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
. (Join-Path $PSScriptRoot 'Pilot-Startup.ps1')
$Identity = Get-LabOSPilotIdentity $PSScriptRoot $Config
$Python = Get-LabOSPython $PSScriptRoot
$EmbeddedPython = Join-Path $PSScriptRoot 'python\python.exe'
if (-not [string]::Equals([IO.Path]::GetFullPath($Python), [IO.Path]::GetFullPath($EmbeddedPython), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Verified pilot startup requires the supplied embedded python\python.exe runtime. Windows virtual-environment redirectors cannot supply the required direct child PID. No worker was launched.'
}
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $Python -B (Join-Path $PSScriptRoot 'Check-Pilot-Runtime.py')
if ($LASTEXITCODE -ne 0) {
    $Code = $LASTEXITCODE
    Write-Host 'Physical runtime imports failed. Use the supplied portable dependency overlay.'
    exit $Code
}
try { $Metadata = Get-LabOSPilotLaunchMetadata $Python $Identity.Config }
catch {
    $Code = $LASTEXITCODE
    if ($Code -ne 0) {
        Write-Host "Pilot profile metadata could not be loaded (exit $Code)."
        exit $Code
    }
    throw
}
$DoctorOutput = & $Python -B -m labos.pilot_worker doctor --config $Identity.Config
if ($LASTEXITCODE -ne 0) {
    $Code = $LASTEXITCODE
    Write-Host 'Pilot Doctor failed; another worker may already be running. Inspect Doctor diagnostics and worker ownership.'
    exit $Code
}
$Doctor = $DoctorOutput | Out-String | ConvertFrom-Json
if ($Doctor.authority_ready -ne $true -or $Doctor.configured_approval_enabled -ne $true -or $Doctor.profile_ready -ne $true -or $Doctor.config_sha256 -cne $Metadata.config_sha256 -or ($Doctor.experiment_scope -and $Doctor.experiment_scope -cne $Metadata.experiment_scope)) {
    throw 'Pilot Doctor is not start-ready for this configuration: check local approval, profile, commissioning, scope and durable blocking.'
}
$LaunchId = [Guid]::NewGuid().ToString('N')
$LogDirectory = Join-Path (Join-Path $PSScriptRoot 'logs') ('physical-pilot-' + $Identity.Id)
$null = New-Item -ItemType Directory -Path $LogDirectory -Force
$Stdout = Join-Path $LogDirectory ($LaunchId + '.stdout.log')
$Stderr = Join-Path $LogDirectory ($LaunchId + '.stderr.log')
$Parameters = @{ FilePath=$Python; ArgumentList=('-B -u -m labos.pilot_worker run --config "' + $Identity.Config + '"'); WorkingDirectory=$PSScriptRoot; PassThru=$true; RedirectStandardOutput=$Stdout; RedirectStandardError=$Stderr }
if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) { $Parameters.WindowStyle = 'Hidden' }
$PreviousLaunchId = $env:LABOS_PILOT_LAUNCH_ID
$Started = [DateTimeOffset]::UtcNow
try {
    $env:LABOS_PILOT_LAUNCH_ID = $LaunchId
    # This handle is the actual Python child, never a PowerShell wrapper PID.
    $Child = Start-Process @Parameters
} finally { $env:LABOS_PILOT_LAUNCH_ID = $PreviousLaunchId }
$Deadline = [Diagnostics.Stopwatch]::StartNew()
$StatusPath = Join-Path $Metadata.state_dir 'status.json'
while ($Deadline.Elapsed.TotalSeconds -lt $ReadinessTimeoutSeconds) {
    $Child.Refresh()
    if ($Child.HasExited) {
        $Code = $Child.ExitCode
        Write-Host "Pilot child exited before readiness (exit $Code). Inspect $Stderr and $Stdout; duplicate-start ownership may have refused this launch."
        if ($Code -eq 0) { exit 1 }
        exit $Code
    }
    try {
        $RawStatus = Get-Content -Raw -LiteralPath $StatusPath
        $Status = $RawStatus | ConvertFrom-Json
        if (Test-LabOSPilotReadiness $Status $Child.Id $LaunchId $Metadata.config_sha256 $Started $RawStatus) {
            $Child.Refresh()
            if (-not $Child.HasExited) {
                Write-Host "Pilot child readiness verified (PID $($Child.Id)); snapshot only, instrument output state unknown. Logs: $Stdout and $Stderr"
                exit 0
            }
        }
    } catch { } # A missing/partial snapshot is retried only within the readiness bound.
    Start-Sleep -Milliseconds 100
}
Write-Host "Pilot readiness timed out after $ReadinessTimeoutSeconds seconds (PID $($Child.Id)). Child was not terminated. Inspect $StatusPath, $Stderr and $Stdout; output state remains unknown."
exit 1
