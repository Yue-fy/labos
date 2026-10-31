param([Parameter(Mandatory=$true)][string]$Archive)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run this smoke check on Windows.' }
$Archive = (Resolve-Path -LiteralPath $Archive).Path
$Root = Join-Path ([IO.Path]::GetTempPath()) ('LabOS (smoke) ' + [char]0x4E2D + [char]0x6587 + ' ' + [guid]::NewGuid().ToString('N'))
Expand-Archive -LiteralPath $Archive -DestinationPath $Root
Write-Host "Extracted delivery: $Root"
if (Test-Path -LiteralPath (Join-Path $Root 'config.yaml')) { throw 'Use an unprovisioned generic ZIP for this check.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'Install.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Installer failed. See install.log in the extracted delivery.' }
if (-not (Test-Path -LiteralPath (Join-Path $Root 'install.log'))) { throw 'Installer did not preserve its log.' }
& (Join-Path $Root 'python\python.exe') -m labos --help
if ($LASTEXITCODE -ne 0) { throw 'The actual packaged CLI could not start.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'Doctor.ps1')
if ($LASTEXITCODE -eq 0) { throw 'Doctor must reject a delivery without PC configuration.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'Start-Agent.ps1')
if ($LASTEXITCODE -eq 0) { throw 'Agent must reject a delivery without PC configuration.' }
Write-Host 'PASS: Windows PowerShell installation, packaged CLI, and missing-config checks.'
Write-Host 'No Agent was started. No server or instruments were accessed.'
Write-Host "Logs retained in: $Root"
