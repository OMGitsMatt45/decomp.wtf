param([string]$Output = (Join-Path $env:TEMP ("decomp-ps2-gpu-" + (Get-Date -Format "yyyyMMdd-HHmmss"))))
$ErrorActionPreference = "Stop"
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "Install uv: https://docs.astral.sh/uv/getting-started/installation/" }
    if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) { throw "Install CMake: https://cmake.org/download/" }
    uv run --locked --group dev --python 3.12 python -m tools.qualify_ps2_hardware $Output
    if ($LASTEXITCODE -ne 0) { throw "PS2 hardware validation failed. Inspect $Output\hardware-assessment.json and its logs." }
    Write-Host "Results: $Output\hardware-assessment.json"
} finally { Pop-Location }
