# decomp.wtf native Windows installer (Windows PowerShell 5.1 or newer).
# From a checkout or extracted source ZIP: double-click windows.cmd.
# PowerShell: irm https://raw.githubusercontent.com/OMGitsMatt45/decomp.wtf/main/site/public/install.ps1 | iex
# Installs for your Windows user with uv and its managed Python 3.12. Projects live in ~/Decomp.
# A checkout installs its own source; otherwise this fork's published release is used.
# DECOMP_SOURCE=<folder|branch:name>, DECOMP_BRANCH=<name>, DECOMP_REPO=<owner/repository> override the source.
# Uninstall: uv tool uninstall decompnet (your projects remain).
param([switch]$NoStart, [switch]$NoConnect, [string]$Source = "")

& {
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$DefaultRepo = "OMGitsMatt45/decomp.wtf"
$ReleaseVersion = "0.19.0"
$UA = "decomp.wtf-native-installer (PowerShell)"

function Step($Text) { Write-Host "> " -ForegroundColor Green -NoNewline; Write-Host $Text }

# Native stderr may contain ordinary diagnostics in Windows PowerShell. Check the process exit code.
function Run([scriptblock]$Command, [string]$Failure = "", [switch]$Quiet) {
    $ErrorActionPreference = "Continue"
    if ($Quiet) { & $Command *> $null } else { & $Command }
    if ($Failure -and $LASTEXITCODE -ne 0) { throw "$Failure (exit code $LASTEXITCODE)" }
}

function Find-Application([string]$Name) {
    $found = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.Source }
}

function Valid-Repo([string]$Repo) {
    return $Repo -match '^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+$' -and $Repo -notmatch '/\.{1,2}$'
}

function Resolve-DecompSource([string]$Requested = "", [string]$Checkout = "") {
    $repo = $DefaultRepo
    $selected = if ($Requested) { $Requested } elseif ($env:DECOMP_SOURCE) { $env:DECOMP_SOURCE } elseif ($env:DECOMP_BRANCH) { "branch:$($env:DECOMP_BRANCH)" } elseif ($Checkout) { $Checkout } else { "release" }
    $channel = "branch"
    $branch = ""
    $commit = ""
    $src = ""
    $spec = ""
    $git = Find-Application "git"
    if ($selected -eq "release") {
        $channel = "release"
    } elseif ($selected.StartsWith("branch:")) {
        $branch = $selected.Substring(7)
        if (-not $branch) { throw "DECOMP_SOURCE=branch:<name> needs a branch name" }
    } else {
        $src = (Resolve-Path -LiteralPath $selected).Path
        if (-not (Test-Path -LiteralPath (Join-Path $src "pyproject.toml")) -or -not (Test-Path -LiteralPath (Join-Path $src "src\decompnet"))) {
            throw "$src isn't decomp.wtf's source"
        }
        $branch = [string]$env:DECOMP_BRANCH
        if ($git -and (Test-Path -LiteralPath (Join-Path $src ".git"))) {
            if (-not $branch) { $branch = ((Run { & $git -c "safe.directory=*" -C $src rev-parse --abbrev-ref HEAD 2>$null }) | Out-String).Trim() }
            if ($branch -eq "HEAD") { $branch = "" }
            $commit = ((Run { & $git -c "safe.directory=*" -C $src rev-parse HEAD 2>$null }) | Out-String).Trim()
        }
        if (-not $branch) { $channel = "release" }
    }
    if ($env:DECOMP_REPO) {
        if (-not (Valid-Repo $env:DECOMP_REPO)) { throw "DECOMP_REPO must be a GitHub repository in owner/name form" }
        $repo = $env:DECOMP_REPO
    } elseif ($src -and $git -and (Test-Path -LiteralPath (Join-Path $src ".git"))) {
        $origin = ((Run { & $git -c "safe.directory=*" -C $src config --get remote.origin.url 2>$null }) | Out-String).Trim()
        if ($origin -match '^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^?#]+)$') {
            $candidate = $Matches[1] -replace '\.git$', ''
            if (Valid-Repo $candidate) { $repo = $candidate }
        }
    }
    if (-not $src -and $channel -eq "release") {
        $spec = "decompnet @ https://github.com/$repo/releases/download/v$ReleaseVersion/decompnet-$ReleaseVersion-py3-none-any.whl"
    } elseif (-not $src) {
        try {
            $head = Invoke-RestMethod -UseBasicParsing -UserAgent $UA -Headers @{ Accept = "application/vnd.github+json" } -Uri "https://api.github.com/repos/$repo/commits/$branch"
            if ($head.sha -match '^[0-9a-f]{40}$') { $commit = $head.sha }
        } catch { }  # a rate-limited API still permits downloading the branch archive
        $archive = if ($commit) { "$commit.tar.gz" } else { "refs/heads/$branch.tar.gz" }
        $spec = "decompnet @ https://github.com/$repo/archive/$archive"
    }
    return [pscustomobject]@{ Source = $selected; SourceDir = $src; Spec = $spec; Channel = $channel; Branch = $branch; Commit = $commit; Repo = $repo }
}

function Find-Uv {
    $found = Find-Application "uv"
    if ($found) { return $found }
    foreach ($folder in @(".local\bin", ".cargo\bin")) {
        $candidate = Join-Path $env:USERPROFILE "$folder\uv.exe"
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
}

function Install-Uv {
    Step "installing uv (Python's tool manager) for your Windows user"
    $oldDir = $env:UV_INSTALL_DIR
    $oldModify = $env:UV_NO_MODIFY_PATH
    try {
        $env:UV_INSTALL_DIR = Join-Path $env:USERPROFILE ".local\bin"
        $env:UV_NO_MODIFY_PATH = "1"
        try {
            $script = Invoke-RestMethod -UseBasicParsing -UserAgent $UA -Uri "https://astral.sh/uv/install.ps1"
        } catch {
            $primaryError = $_.Exception.Message
            Step "Astral's download couldn't be reached; trying its official GitHub installer"
            try {
                $script = Invoke-RestMethod -UseBasicParsing -UserAgent $UA -Uri "https://github.com/astral-sh/uv/releases/latest/download/uv-installer.ps1"
            } catch {
                throw "Couldn't download uv's installer. astral.sh: $primaryError; GitHub: $($_.Exception.Message). Install uv from https://docs.astral.sh/uv/, then run windows.cmd again."
            }
        }
        & ([scriptblock]::Create($script)) | Out-Host
    } finally {
        $env:UV_INSTALL_DIR = $oldDir
        $env:UV_NO_MODIFY_PATH = $oldModify
    }
    $found = Find-Uv
    if (-not $found) { throw "uv wasn't installed. Install it from https://docs.astral.sh/uv/, then run windows.cmd again." }
    return $found
}

function Add-DecompPath([string]$Bin) {
    # Preserve expandable entries such as %USERPROFILE%; put the native command before older launchers.
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("Environment")
    try {
        $raw = [string]$key.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $paths = @($raw -split ";" | Where-Object { $_ -and $_.TrimEnd('\') -ne $Bin.TrimEnd('\') })
        $key.SetValue("Path", ((@($Bin) + $paths) -join ";"), [Microsoft.Win32.RegistryValueKind]::ExpandString)
    } finally { $key.Close() }
    $env:Path = (@($Bin) + @($env:Path -split ";" | Where-Object { $_ -and $_.TrimEnd('\') -ne $Bin.TrimEnd('\') })) -join ";"
    # .NET broadcasts WM_SETTINGCHANGE, so Explorer and new terminals see the updated PATH.
    $previous = [Environment]::GetEnvironmentVariable("DECOMP_WTF_REFRESH", "User")
    try { [Environment]::SetEnvironmentVariable("DECOMP_WTF_REFRESH", [guid]::NewGuid().ToString(), "User") }
    finally { [Environment]::SetEnvironmentVariable("DECOMP_WTF_REFRESH", $previous, "User") }
}

function Find-Decomp([string]$Bin) {
    $exe = Join-Path $Bin "decomp.exe"
    if (-not (Test-Path -LiteralPath $exe)) { throw "uv installed the package, but $exe is missing" }
    return $exe
}

function Stop-Decomp([string]$Bin) {
    $exe = Join-Path $Bin "decomp.exe"
    if (-not (Test-Path -LiteralPath $exe)) { return }
    $homeDir = if ($env:DECOMP_HOME) { $env:DECOMP_HOME } else { Join-Path $env:USERPROFILE "Decomp" }
    $state = Join-Path $homeDir ".decomp\server.json"
    $appPid = $null
    if (Test-Path -LiteralPath $state) {
        try { $appPid = (Get-Content -LiteralPath $state -Raw | ConvertFrom-Json).pid } catch { }
    }
    Run { & $exe stop } -Quiet
    if ($appPid -and $appPid -ne $PID) {
        Wait-Process -Id $appPid -Timeout 20 -ErrorAction SilentlyContinue
        if (Get-Process -Id $appPid -ErrorAction SilentlyContinue) { throw "Close the running decomp.wtf app, then run windows.cmd again so its files can be replaced." }
    }
}

function Install-Decomp([string]$Requested = "", [string]$Checkout = "", [switch]$NoStart, [switch]$NoConnect) {
    if ($env:PROCESSOR_ARCHITECTURE -ne "AMD64" -and $env:PROCESSOR_ARCHITEW6432 -ne "AMD64") {
        throw "decomp.wtf's native Windows tools currently need a 64-bit Intel or AMD PC"
    }
    $tmp = $null
    $oldBridge = $env:DECOMP_WSL
    $env:DECOMP_WSL = $null
    try {
        Write-Host "decomp.wtf native Windows setup" -ForegroundColor White
        $sourceInfo = Resolve-DecompSource -Requested $Requested -Checkout $Checkout
        $uv = Find-Uv
        if (-not $uv) { $uv = Install-Uv }
        Run { & $uv --version } "uv couldn't start"
        $bin = ((Run { & $uv tool dir --bin } "uv couldn't find its command folder") | Out-String).Trim()
        if (-not $bin) { throw "uv returned an empty command folder" }
        Stop-Decomp $bin
        $spec = $sourceInfo.Spec
        if ($sourceInfo.SourceDir) {
            $tmp = Join-Path ([IO.Path]::GetTempPath()) ("decomp-native-" + [guid]::NewGuid().ToString("N"))
            New-Item -ItemType Directory -Path $tmp | Out-Null
            foreach ($name in @("pyproject.toml", "README.md", "LICENSE", "src")) {
                Copy-Item -LiteralPath (Join-Path $sourceInfo.SourceDir $name) -Destination $tmp -Recurse -Force
            }
            $spec = $tmp
        }
        Step "installing decomp.wtf with its own Python 3.12"
        Run { & $uv tool install --force --managed-python --python "3.12" $spec } "installing decomp.wtf failed"
        Add-DecompPath $bin
        $decomp = Find-Decomp $bin
        $metadata = @("install-info", "--channel", $sourceInfo.Channel, "--repo", $sourceInfo.Repo)
        # Windows PowerShell drops empty native arguments; argparse already defaults these fields to empty.
        if ($sourceInfo.Branch) { $metadata += @("--branch", $sourceInfo.Branch) }
        if ($sourceInfo.Commit) { $metadata += @("--commit", $sourceInfo.Commit) }
        Run { & $decomp @metadata } "saving the installation source failed" -Quiet
        Step "setting up the available native Windows tools"
        Run { & $decomp setup } "setting up decomp.wtf failed"
        Run { & $decomp shortcut } "adding decomp.wtf to your apps failed"
        if (-not $NoConnect -and [Environment]::UserInteractive) {
            $agents = Run { & $decomp connect --list }
            if ($LASTEXITCODE -eq 0 -and ($agents -match "not connected")) {
                try { $answer = Read-Host "Give your installed AI agents decomp.wtf's tools? [Y/n]" } catch { $answer = "n" }
                if (-not $answer -or $answer -match '^[Yy]') { Run { & $decomp connect } "connecting your agents failed" }
            }
        }
        Write-Host ""
        Write-Host "Done. Open decomp.wtf from the Start menu or desktop, or type decomp." -ForegroundColor White
        $projectHome = if ($env:DECOMP_HOME) { $env:DECOMP_HOME } else { Join-Path $env:USERPROFILE "Decomp" }
        Write-Host "  Your projects: $projectHome"
        Write-Host "  Connect your AI agents any time: decomp connect"
        if (-not $NoStart) { Start-Process -FilePath $decomp -WindowStyle Minimized }
    } finally {
        $env:DECOMP_WSL = $oldBridge
        if ($tmp -and (Test-Path -LiteralPath $tmp)) { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

$checkout = ""
if ($PSScriptRoot) {
    $root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
    $py = Join-Path $root "pyproject.toml"
    if ((Test-Path -LiteralPath $py) -and (Select-String -LiteralPath $py -Pattern '^name = "decompnet"' -Quiet)) { $checkout = $root }
}
Install-Decomp -Requested $Source -Checkout $checkout -NoStart:$NoStart -NoConnect:$NoConnect
}
