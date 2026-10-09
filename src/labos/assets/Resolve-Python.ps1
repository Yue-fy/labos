function Get-LabOSPython {
    param([string]$Root)
    foreach ($Relative in @('python\python.exe', '.venv\Scripts\python.exe')) {
        $Candidate = Join-Path $Root $Relative
        if (Test-Path $Candidate) { return $Candidate }
    }
    throw 'LabOS Python is missing. Run Install.ps1, or use the Windows x64 portable package.'
}
