param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [string]$LogDirectory
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Run this smoke check on Windows.' }
$Root = Join-Path ([IO.Path]::GetTempPath()) ('LabOS (smoke) ' + [char]0x4E2D + [char]0x6587 + ' ' + [guid]::NewGuid().ToString('N'))
$TranscriptStarted = $false
try {
    if ($LogDirectory) {
        $LogDirectory = [IO.Path]::GetFullPath($LogDirectory)
        New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
        Start-Transcript -Path (Join-Path $LogDirectory 'windows-smoke.log') -Force | Out-Null
        $TranscriptStarted = $true
    }
    if ($PSVersionTable.PSVersion.Major -ne 5 -or $PSVersionTable.PSVersion.Minor -ne 1) {
        throw 'Run this smoke check with Windows PowerShell 5.1 (powershell.exe).'
    }
    $Archive = (Resolve-Path -LiteralPath $Archive).Path
    Expand-Archive -LiteralPath $Archive -DestinationPath $Root
    Write-Host "Extracted delivery: $Root"
    if (Test-Path -LiteralPath (Join-Path $Root 'config.yaml')) { throw 'Use an unprovisioned generic ZIP for this check.' }
    $Scripts = @(Get-ChildItem -LiteralPath $Root -Filter '*.ps1' -Recurse -File)
    if ($Scripts.Count -eq 0) { throw 'The delivery contains no PowerShell scripts.' }
    foreach ($Script in $Scripts) {
        $Tokens = $null
        $ParseErrors = $null
        [Management.Automation.Language.Parser]::ParseFile($Script.FullName, [ref]$Tokens, [ref]$ParseErrors) | Out-Null
        if ($ParseErrors.Count -gt 0) { throw "PowerShell parse failed: $($Script.FullName): $ParseErrors" }
        Write-Host "Parsed: $($Script.FullName)"
    }
    Write-Host "Parsed $($Scripts.Count) shipped PowerShell files."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'Install.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Installer failed. See install.log in the extracted delivery.' }
    if (-not (Test-Path -LiteralPath (Join-Path $Root 'install.log'))) { throw 'Installer did not preserve its log.' }
    Push-Location -LiteralPath $Root
    try {
        & cmd.exe /d /c 'Install.cmd <NUL'
        if ($LASTEXITCODE -ne 0) { throw 'The batch installer failed with noninteractive stdin.' }
    } finally {
        Pop-Location
    }
    & (Join-Path $Root 'python\python.exe') --version
    if ($LASTEXITCODE -ne 0) { throw 'The actual embedded Python could not start.' }
    & (Join-Path $Root 'python\python.exe') -m labos --help
    if ($LASTEXITCODE -ne 0) { throw 'The actual packaged CLI could not start.' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'Doctor.ps1')
    if ($LASTEXITCODE -eq 0) { throw 'Doctor must reject a delivery without PC configuration.' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'Start-Agent.ps1')
    if ($LASTEXITCODE -eq 0) { throw 'Agent must reject a delivery without PC configuration.' }
    Write-Host 'PASS: Windows PowerShell parsing, installation, packaged CLI, and missing-config checks.'
    Write-Host 'No Agent was started. No server or instruments were accessed.'
} catch {
    Write-Host "SMOKE FAILED: $($_.Exception.Message)"
    throw
} finally {
    if ($LogDirectory -and (Test-Path -LiteralPath (Join-Path $Root 'install.log'))) {
        Copy-Item -LiteralPath (Join-Path $Root 'install.log') -Destination (Join-Path $LogDirectory 'install.log') -Force
    }
    if ($TranscriptStarted) { Stop-Transcript | Out-Null }
    if (Test-Path -LiteralPath $Root) { Write-Host "Extracted delivery and original logs retained in: $Root" }
    if ($TranscriptStarted) { Write-Host "Smoke logs retained in: $LogDirectory" }
}
exit 0
