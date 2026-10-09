param([string]$TaskName = 'LabOS-Agent', [switch]$AtStartup)
$ErrorActionPreference = 'Stop'
$AgentScript = Join-Path $PSScriptRoot 'Start-Agent.ps1'
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'config.yaml'))) { throw 'Provision config.yaml first.' }
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$AgentScript`"" -WorkingDirectory $PSScriptRoot
if ($AtStartup) {
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'AtStartup requires an elevated PowerShell. Default AtLogOn uses your current user.' }
    $Trigger = New-ScheduledTaskTrigger -AtStartup
    $Principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
} else {
    $Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Identity
    $Principal = New-ScheduledTaskPrincipal -UserId $Identity -LogonType Interactive -RunLevel Limited
}
$Settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw 'Task already exists. Choose another name or remove the existing LabOS task explicitly.' }
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings | Out-Null
Write-Host "Registered $TaskName. Logs: data\logs\service.log. To remove: Unregister-ScheduledTask -TaskName '$TaskName'"
