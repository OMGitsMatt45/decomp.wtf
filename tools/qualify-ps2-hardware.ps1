param([string]$Output = (Join-Path $env:TEMP ("decomp-ps2-gpu-" + (Get-Date -Format "yyyyMMdd-HHmmss"))))
$ErrorActionPreference = "Stop"
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $uvCommand = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $uvProgram = if ($uvCommand) { $uvCommand.Source } else { $null }
    if (-not $uvProgram) {
        foreach ($folder in @(".local\bin", ".cargo\bin")) {
            $candidate = Join-Path $env:USERPROFILE "$folder\uv.exe"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { $uvProgram = $candidate; break }
        }
    }
    if (-not $uvProgram) {
        throw "PowerShell cannot find uv. Run: winget install --id astral-sh.uv --exact . Then close and reopen PowerShell and retry this script. Installer: https://docs.astral.sh/uv/getting-started/installation/"
    }
    if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) { throw "Install CMake: https://cmake.org/download/" }
    & $uvProgram run --locked --group dev --python 3.12 python -m tools.qualify_ps2_hardware $Output
    if ($LASTEXITCODE -ne 0) { throw "PS2 hardware validation failed. Inspect $Output\hardware-assessment.json and its logs." }
    Write-Host "Results: $Output\hardware-assessment.json"
} finally { Pop-Location }
