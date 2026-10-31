param([ValidateSet('agent','central')][string]$Role, [string]$Wheelhouse)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$TranscriptStarted = $false
try {
    Start-Transcript -Path (Join-Path $PSScriptRoot 'install.log') -Force | Out-Null
    $TranscriptStarted = $true
    if (-not $Role) { $Role = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'ROLE') -Raw).Trim() }
    if ($Role -notin @('agent','central')) { throw 'ROLE must be agent or central.' }
    $Check = Join-Path $PSScriptRoot 'Check-Runtime.py'
    if (-not (Test-Path -LiteralPath $Check)) { throw 'Check-Runtime.py is missing. Extract the entire ZIP first.' }
    if (($Role -eq 'agent') -and (Test-Path -LiteralPath 'python\python.exe')) {
        $Python = Join-Path $PSScriptRoot 'python\python.exe'
        Write-Host 'Checking the bundled runtime; no downloads or instrument commands.'
    } else {
        if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
            $Launcher = Get-Command py -ErrorAction SilentlyContinue
            if ($Launcher) { & py -3 -c 'import sys; assert sys.version_info >= (3,11)'; if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ required.' }; & py -3 -m venv .venv }
            else { & python -c 'import sys; assert sys.version_info >= (3,11)'; if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11+ first.' }; & python -m venv .venv }
            if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
        }
        $Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
        $Requirements = "requirements-$Role.txt"
        if ($Wheelhouse) { & $Python -m pip install --no-index --find-links $Wheelhouse -r $Requirements }
        else { & $Python -m pip install -r $Requirements }
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    }
    & $Python $Check --role $Role
    if ($LASTEXITCODE -ne 0) { throw 'Runtime check failed. See install.log above the final error.' }
    if (Test-Path -LiteralPath 'config.yaml') {
        if (($Role -eq 'agent') -and (Test-Path -LiteralPath 'program-connector.yaml')) { Write-Host 'Runtime installation complete. Run Install-Program-Connector.ps1 for this program-only profile.' }
        elseif (($Role -eq 'agent') -and (Test-Path -LiteralPath 'cooperation.yaml')) { Write-Host 'Runtime installation complete. Run Install-Cooperation.ps1 for this agent-assisted profile.' }
        elseif ($Role -eq 'agent') { Write-Host 'Installation complete. Run Doctor.ps1 then Start-Agent.cmd.' }
        else { Write-Host 'Installation complete. Run Start-Central.ps1 with your central configuration.' }
    } else {
        Write-Host 'Installation complete. This template has no config.yaml.'
        if ($Role -eq 'agent') { Write-Host 'Obtain a personalized PC configuration from the central server before running Doctor or Agent.' }
        else { Write-Host 'Provision a central configuration before starting the central server.' }
    }
    exit 0
} catch {
    Write-Host "INSTALL FAILED: $($_.Exception.Message)"
    Write-Host 'Diagnostic details are in install.log in this folder.'
    exit 1
} finally {
    if ($TranscriptStarted) { Stop-Transcript | Out-Null }
}
