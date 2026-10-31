param([string]$Config = 'program-connector.yaml')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'Resolve-Python.ps1')
$Python = Get-LabOSPython $PSScriptRoot
$ConfigPath = (Resolve-Path -LiteralPath $Config).Path
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $Python -B -m labos.program_connector doctor --config $ConfigPath
if ($LASTEXITCODE -ne 0) { throw 'Program Connector Doctor failed. Check local configuration, approved paths and public HTTPS connectivity.' }
$Startup = [Environment]::GetFolderPath('Startup')
if (-not $Startup) { throw 'Current-user Startup folder is unavailable.' }
$ScriptPath = Join-Path $PSScriptRoot 'Start-Program-Connector.ps1'
$Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $ScriptPath + '" -Config "' + $ConfigPath + '"'
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut((Join-Path $Startup 'LabOS-Program-Connector.lnk'))
$Shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Shortcut.Arguments = $Arguments
$Shortcut.WorkingDirectory = $PSScriptRoot
$Shortcut.WindowStyle = 7
$Shortcut.Description = 'LabOS outbound approved program connector'
$Shortcut.Save()
Start-Process -FilePath $Shortcut.TargetPath -ArgumentList $Arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
Write-Host 'Program connector launch requested. Inspect data/program-connector/status.json and program-connector.log.'
Write-Host 'It starts again when this Windows user signs in. Keep this package directory in place.'
