param([string]$Config = 'pilot-worker.yaml', [ValidateRange(1, 120)][int]$ReadinessTimeoutSeconds = 15)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'Pilot-Startup.ps1')
$Identity = Get-LabOSPilotIdentity $PSScriptRoot $Config
$Startup = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $Startup ('LabOS-Physical-Pilot-' + $Identity.Id + '.lnk')
$Shell = New-Object -ComObject WScript.Shell
if ((Test-Path -LiteralPath $ShortcutPath) -and -not (Test-LabOSPilotShortcut ($Shell.CreateShortcut($ShortcutPath)) $Identity)) {
    throw 'Startup entry has different ownership; refusing to overwrite it.'
}
& (Join-Path $PSScriptRoot 'Start-Pilot.ps1') -Config $Identity.Config -ReadinessTimeoutSeconds $ReadinessTimeoutSeconds
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Identity.Target
$Shortcut.Arguments = $Identity.Arguments
$Shortcut.WorkingDirectory = $Identity.Root
$Shortcut.WindowStyle = 7
$Shortcut.Description = 'LabOS locally commissioned finite physical pilot'
$Shortcut.Save()
$Legacy = Join-Path $Startup 'LabOS-Physical-Pilot.lnk'
if ((Test-Path -LiteralPath $Legacy) -and (Test-LabOSPilotShortcut ($Shell.CreateShortcut($Legacy)) $Identity)) { Remove-Item -LiteralPath $Legacy }
Write-Host 'Profile startup entry installed after child readiness verification. Inspect logs and independent protection readbacks.'
