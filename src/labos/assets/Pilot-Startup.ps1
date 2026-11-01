# Shared portable startup identity and read-only launch observations (PowerShell 5.1).
function Get-LabOSPilotIdentity {
    param([string]$Root, [string]$Config)
    $RootPath = (Resolve-Path -LiteralPath $Root).Path
    $ConfigPath = $Config
    if (-not [IO.Path]::IsPathRooted($ConfigPath)) { $ConfigPath = Join-Path $RootPath $ConfigPath }
    $ConfigPath = [IO.Path]::GetFullPath($ConfigPath)
    if (Test-Path -LiteralPath $ConfigPath) { $ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path }
    $Canonical = $RootPath.TrimEnd('\', '/').ToLowerInvariant() + "`n" + $ConfigPath.ToLowerInvariant()
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try { $Id = ([BitConverter]::ToString($Hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($Canonical)))).Replace('-', '').ToLowerInvariant() }
    finally { $Hasher.Dispose() }
    $Target = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $RootPath 'Start-Pilot.ps1') + '" -Config "' + $ConfigPath + '"'
    return [pscustomobject]@{ Id=$Id; Root=$RootPath; Config=$ConfigPath; Target=$Target; Arguments=$Arguments }
}

function Test-LabOSPilotShortcut {
    param($Shortcut, $Identity)
    return [string]::Equals($Shortcut.TargetPath, $Identity.Target, [StringComparison]::OrdinalIgnoreCase) -and [string]::Equals($Shortcut.Arguments, $Identity.Arguments, [StringComparison]::OrdinalIgnoreCase)
}

function Remove-LabOSPilotStartup {
    param($Identity)
    $Startup = [Environment]::GetFolderPath('Startup')
    $Shell = New-Object -ComObject WScript.Shell
    foreach ($Name in @(('LabOS-Physical-Pilot-' + $Identity.Id + '.lnk'), 'LabOS-Physical-Pilot.lnk')) {
        $Path = Join-Path $Startup $Name
        if ((Test-Path -LiteralPath $Path) -and (Test-LabOSPilotShortcut ($Shell.CreateShortcut($Path)) $Identity)) {
            Remove-Item -LiteralPath $Path
        }
    }
}

function Get-LabOSPilotLaunchMetadata {
    param([string]$Python, [string]$ConfigPath)
    # Loading the schema/fingerprint does not construct a worker, driver or adapter.
    $Code = @'
import json, sys
from labos.pilot_worker import load_pilot_worker_config
from labos.pilot_authority import config_fingerprint
config = load_pilot_worker_config(sys.argv[1])
print(json.dumps(dict(state_dir=str(config.state_dir), config_sha256=config_fingerprint(config), experiment_scope=config.adapter_config.get('experiment_scope', 'optical_transport'))))
'@
    $Output = $Code | & $Python -B - $ConfigPath
    if ($LASTEXITCODE -ne 0) { throw 'Pilot profile metadata could not be loaded.' }
    return ($Output | Out-String | ConvertFrom-Json)
}

function Test-LabOSPilotReadiness {
    param($Status, [int]$ChildPid, [string]$LaunchId, [string]$ConfigHash, [DateTimeOffset]$Started, [string]$RawStatus)
    if ($RawStatus -cnotmatch '"updated_at_utc"\s*:\s*"[0-9T:.+-]+(?:Z|\+00:00)"') { return $false }
    $Updated = [DateTimeOffset]::MinValue
    if ($Status.updated_at_utc -is [DateTime]) {
        # PowerShell Core converts JSON timestamps; 5.1 retains the original string.
        $Updated = ([DateTimeOffset]$Status.updated_at_utc).ToUniversalTime()
    } elseif (-not [DateTimeOffset]::TryParse([string]$Status.updated_at_utc, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$Updated)) { return $false }
    return $Status.launch_id -ceq $LaunchId -and $Status.config_sha256 -ceq $ConfigHash -and `
        $Status.instance_id -cmatch '^[0-9a-f]{32}$' -and $Status.pid -eq $ChildPid -and `
        $Status.snapshot_only -eq $true -and $Status.phase -cin @('started', 'listening', 'network_unavailable', 'executing') -and `
        $Updated.Offset -eq [TimeSpan]::Zero -and $Updated -ge $Started -and $Updated -le [DateTimeOffset]::UtcNow
}
