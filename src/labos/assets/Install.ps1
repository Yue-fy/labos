param([ValidateSet('agent','central')][string]$Role, [string]$Wheelhouse)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $Role) { $Role = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'ROLE') -Raw).Trim() }
if ($Role -notin @('agent','central')) { throw 'ROLE must be agent or central.' }
if (($Role -eq 'agent') -and (Test-Path -LiteralPath 'python\python.exe')) {
    & '.\python\python.exe' -c 'import labos, pydantic, httpx, yaml; print("Portable LabOS runtime OK")'
    if ($LASTEXITCODE -ne 0) { throw 'Portable runtime check failed.' }
    Write-Host 'Offline portable installation complete. Run Doctor.ps1 then Start-Agent.cmd.'
    exit 0
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) { & py -3 -c 'import sys; assert sys.version_info >= (3,11)'; if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ required.' }; & py -3 -m venv .venv }
    else { & python -c 'import sys; assert sys.version_info >= (3,11)'; if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11+ first.' }; & python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
$Requirements = "requirements-$Role.txt"
if ($Wheelhouse) { & '.\.venv\Scripts\python.exe' -m pip install --no-index --find-links $Wheelhouse -r $Requirements }
else { & '.\.venv\Scripts\python.exe' -m pip install -r $Requirements }
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& '.\.venv\Scripts\python.exe' -m labos --help
if ($LASTEXITCODE -ne 0) { throw 'LabOS check failed.' }
Write-Host 'Installation complete. Credentials come from central provisioning; no firewall or SSH configuration is required on this PC.'
