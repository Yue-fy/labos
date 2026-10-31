param([string]$Config = 'pilot-worker.yaml')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$Python = Get-LabOSPython $PSScriptRoot
$ConfigPath = (Resolve-Path -LiteralPath $Config).Path
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $Python -B (Join-Path $PSScriptRoot 'Check-Pilot-Runtime.py')
if ($LASTEXITCODE -ne 0) { throw 'Physical runtime imports failed. Use the supplied portable dependency overlay.' }
& $Python -B -m labos.pilot_worker doctor --config $ConfigPath
if ($LASTEXITCODE -ne 0) { throw 'Pilot Doctor failed. Check local commissioning and HTTPS.' }
$Startup = [Environment]::GetFolderPath('Startup')
$ScriptPath = Join-Path $PSScriptRoot 'Start-Pilot.ps1'
$Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $ScriptPath + '" -Config "' + $ConfigPath + '"'
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut((Join-Path $Startup 'LabOS-Physical-Pilot.lnk'))
$Shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Shortcut.Arguments = $Arguments
$Shortcut.WorkingDirectory = $PSScriptRoot
$Shortcut.WindowStyle = 7
$Shortcut.Description = 'LabOS locally commissioned finite physical pilot'
$Shortcut.Save()
Start-Process -FilePath $Shortcut.TargetPath -ArgumentList $Arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
Write-Host 'Physical worker launch requested. Review physical-pilot.log and its separate status/ledger directory.'
