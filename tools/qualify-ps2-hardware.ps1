param(
    [string]$Output = (Join-Path $env:TEMP ("dwg-" + [guid]::NewGuid().ToString("N").Substring(0,8))),
    [switch]$CheckTools
)
$ErrorActionPreference = "Stop"
$originalPath = $env:PATH
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
        throw "PowerShell cannot find uv. Install it with: winget install --id astral-sh.uv --exact`nThen close and reopen PowerShell and retry this script. Installer: https://docs.astral.sh/uv/getting-started/installation/"
    }
    $cmakeCommand = Get-Command cmake -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $cmakeProgram = if ($cmakeCommand) { $cmakeCommand.Source } else { $null }
    if (-not $cmakeProgram -and ${env:ProgramFiles(x86)}) {
        $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
        if (Test-Path -LiteralPath $vswhere -PathType Leaf) {
            $candidates = & $vswhere -products '*' -find 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
            foreach ($candidate in $candidates) {
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { $cmakeProgram = $candidate; break }
            }
        }
    }
    if (-not $cmakeProgram) {
        throw "CMake was not found on PATH or in Visual Studio. In Visual Studio Installer > Modify > Individual components, enable 'C++ CMake tools for Windows', or install https://cmake.org/download/ . A separate CMake download is unnecessary when the Visual Studio component is installed."
    }
    if ($CheckTools) {
        [pscustomobject]@{ uv = $uvProgram; cmake = $cmakeProgram; output = [IO.Path]::GetFullPath($Output) } | ConvertTo-Json -Compress
        return
    }
    $env:PATH = (Split-Path $cmakeProgram -Parent) + [IO.Path]::PathSeparator + $env:PATH
    Write-Host "CMake: $cmakeProgram"
    & $uvProgram run --locked --group dev --python 3.12 python -m tools.qualify_ps2_hardware $Output
    if ($LASTEXITCODE -ne 0) { throw "PS2 hardware validation failed. Inspect $Output\hardware-assessment.json and its logs." }
    Write-Host "Results: $Output\hardware-assessment.json"
} finally { $env:PATH = $originalPath; Pop-Location }
