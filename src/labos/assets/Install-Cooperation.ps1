param([string]$Config = 'cooperation.yaml')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$Python = Get-LabOSPython $PSScriptRoot
$ConfigPath = (Resolve-Path -LiteralPath $Config).Path
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $Python -B -m labos.cooperation_worker doctor --config $ConfigPath
if ($LASTEXITCODE -ne 0) { throw 'Worker Doctor failed. Check the CLI executable, CLI login, package configuration and HTTPS connection.' }
# Current-user Startup folder: no administrator rights or scheduled-task service required.
$Startup = [Environment]::GetFolderPath('Startup')
if (-not $Startup) { throw 'Current-user Startup folder is unavailable.' }
$ScriptPath = Join-Path $PSScriptRoot 'Start-Cooperation.ps1'
$Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $ScriptPath + '" -Config "' + $ConfigPath + '"'
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut((Join-Path $Startup 'LabOS-Cooperation.lnk'))
$Shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Shortcut.Arguments = $Arguments
$Shortcut.WorkingDirectory = $PSScriptRoot
$Shortcut.WindowStyle = 7
$Shortcut.Description = 'LabOS automatic report cooperation'
$Shortcut.Save()
Start-Process -FilePath $Shortcut.TargetPath -ArgumentList $Arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
Write-Host 'Cooperation worker launch requested. Inspect data/cooperation/status.json and cooperation-worker.log.'
Write-Host 'It will start again when this Windows user signs in. Keep this package directory in place.'
