"""Exercise the installer with PowerShell without installing WSL or changing Windows settings."""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


PUBLIC = Path(__file__).resolve().parents[1] / "site" / "public"
INSTALLER = PUBLIC / "install.ps1"


@pytest.fixture
def powershell(tmp_path):
    # Windows PowerShell first: this is what ships with Windows, and has the older 5.1 parser.
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        pytest.skip("needs Windows PowerShell or pwsh")

    def run(code):
        script = tmp_path / "test.ps1"
        # Windows PowerShell needs a BOM to recognize non-ASCII source text as UTF-8.
        script.write_text('$ErrorActionPreference = "Stop"\n'
                          '[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false\n' + code,
                          encoding="utf-8-sig", newline="\n")
        env = os.environ.copy()
        if sys.platform != "win32":
            # Portable pwsh must not try to initialize its cache in a read-only home directory.
            for name in ("XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
                env[name] = str(tmp_path / name)
        return subprocess.run([exe, "-NoProfile", "-NonInteractive", "-File", str(script)],
                              capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)

    return run


def ps_string(text):
    return "'" + str(text).replace("'", "''") + "'"


def helpers(*names):
    """Load the real helper definitions through PowerShell's AST; never run the installer body."""
    return f"""
$ast = [System.Management.Automation.Language.Parser]::ParseFile({ps_string(INSTALLER)}, [ref]$null, [ref]$null)
$names = @({', '.join(ps_string(name) for name in names)})
$functions = $ast.FindAll({{ param($n)
    $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $names -contains $n.Name
}}, $true)
foreach ($f in $functions) {{ Invoke-Expression $f.Extent.Text }}
"""


@pytest.mark.parametrize("name", [p.name for p in sorted(PUBLIC.glob("*.ps1"))])
def test_powershell_scripts_parse(powershell, name):
    result = powershell(f"""
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile({ps_string(PUBLIC / name)}, [ref]$null, [ref]$parseErrors)
if ($parseErrors) {{ throw ($parseErrors | Out-String) }}
""")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("name", ["connect", "uninstall"])
def test_generated_powershell_scripts_parse(powershell, name):
    text = INSTALLER.read_text(encoding="utf-8")
    embedded = re.search(rf"\${name} = @'\n(.*?)\n'@", text, re.S).group(1)
    result = powershell(f"""
$parseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput({ps_string(embedded)}, [ref]$null, [ref]$parseErrors)
if ($parseErrors) {{ throw ($parseErrors | Out-String) }}
""")
    assert result.returncode == 0, result.stdout + result.stderr


def test_native_commands_accept_diagnostics_and_report_failure(powershell):
    diagnostic = base64.b64encode('[Console]::Error.WriteLine("compiler diagnostic"); exit 0'.encode("utf-16-le")).decode()
    failure = base64.b64encode('exit 23'.encode("utf-16-le")).decode()
    result = powershell(helpers("Run") + f"""
$native = (Get-Process -Id $PID).Path
Run {{ & $native -NoProfile -EncodedCommand {diagnostic} }} 'unexpected failure'
try {{
    Run {{ & $native -NoProfile -EncodedCommand {failure} }} 'expected failure' -Quiet
    throw 'accepted failed command'
}} catch {{
    if ($_.Exception.Message -ne 'expected failure (exit code 23)') {{ throw }}
}}
""")
    assert result.returncode == 0, result.stdout + result.stderr


def test_failed_wsl_listing_does_not_start_another_install(powershell, tmp_path):
    native = tmp_path / ("wsl.cmd" if sys.platform == "win32" else "wsl")
    native.write_text("@exit /b 7\n" if sys.platform == "win32" else "#!/bin/sh\nexit 7\n")
    native.chmod(0o755)
    result = powershell(helpers("Run", "Distros") + f"""
$Wsl = {ps_string(native)}
try {{
    Distros
    throw 'accepted failed distro listing'
}} catch {{
    if ($_.Exception.Message -notmatch 'listing WSL distributions failed.*exit code 7') {{ throw }}
}}
""")
    assert result.returncode == 0, result.stdout + result.stderr


def test_wsl_capture_preserves_native_error_and_exit_code(powershell):
    native_code = ('[Console]::Out.WriteLine("import" + [char]0 + " progress"); '
                   '[Console]::Error.WriteLine("Wsl/Service/RegisterDistro/CreateVm/HCS_E_HYPERV_NOT_INSTALLED"); '
                   'exit 23')
    encoded = base64.b64encode(native_code.encode("utf-16-le")).decode()
    result = powershell(helpers("Invoke-WslCapture") + f"""
$Wsl = (Get-Process -Id $PID).Path
$capture = Invoke-WslCapture @('-NoProfile', '-EncodedCommand', '{encoded}')
$capture | ConvertTo-Json -Compress
""")
    assert result.returncode == 0, result.stdout + result.stderr
    capture = json.loads(result.stdout)
    assert capture["ExitCode"] == 23
    assert "import progress" in capture["Output"]
    assert "HCS_E_HYPERV_NOT_INSTALLED" in capture["Output"]
    assert "\x00" not in capture["Output"]
    assert "-EncodedCommand" in capture["Command"]


@pytest.fixture
def distro_setup(powershell, tmp_path):
    """Run the real distro creation flow against fake downloads and WSL; never touch Windows settings."""
    def run(*, already_registered=False, import_exit=0, import_registers=True,
            fallback_exit=0, fallback_registers=True, download_fails=False, checksum_matches=True):
        code = helpers("Step", "New-DecompDistro") + f"""
$Distro = 'decomp-wtf'
$Wsl = 'wsl.exe'
$Base = {ps_string(tmp_path / "distro")}
$UA = 'decomp.wtf-test'
$script:registered = ${str(already_registered).lower()}
$script:downloadCalls = 0
$script:calls = New-Object 'System.Collections.Generic.List[object]'
function Distros {{ if ($script:registered) {{ 'decomp-wtf' }} }}
function Invoke-RestMethod {{
    [pscustomobject]@{{ ModernDistributions = [pscustomobject]@{{ Debian = @(
        [pscustomobject]@{{ Name = 'Debian'; Amd64Url = [pscustomobject]@{{
            Url = 'https://example.invalid/debian.wsl'; Sha256 = 'expected'
        }} }}
    ) }} }}
}}
function Invoke-WebRequest {{
    param([switch]$UseBasicParsing, [string]$UserAgent, [string]$Uri, [string]$OutFile)
    $script:downloadCalls++
    if (${str(download_fails).lower()}) {{ throw 'Debian image download failed: HTTP 403' }}
    [IO.File]::WriteAllText($OutFile, 'fake Debian image')
}}
function Get-FileHash {{ [pscustomobject]@{{ Hash = '{'expected' if checksum_matches else 'mismatch'}' }} }}
function Invoke-WslCapture([string[]]$Arguments) {{
    $script:calls.Add($Arguments)
    if ($Arguments -contains '--import') {{
        $script:registered = ${str(import_registers).lower()}
        return [pscustomobject]@{{ ExitCode = {import_exit}; Output = 'Wsl/Service/RegisterDistro/CreateVm/HCS_E_HYPERV_NOT_INSTALLED'; Command = 'wsl.exe --import decomp-wtf' }}
    }}
    if ($Arguments -notcontains '--install') {{ throw "unexpected WSL call: $Arguments" }}
    $script:registered = ${str(fallback_registers).lower()}
    return [pscustomobject]@{{ ExitCode = {fallback_exit}; Output = 'Wsl/E_INVALIDARG: unsupported installation option'; Command = 'wsl.exe --install Debian' }}
}}
try {{
    New-DecompDistro
    $failure = $null
}} catch {{ $failure = $_.Exception.Message }}
'TEST_RESULT=' + (@{{ Calls = @($script:calls.ToArray()); DownloadCalls = $script:downloadCalls; Error = $failure }} | ConvertTo-Json -Depth 10 -Compress)
"""
        result = powershell(code)
        assert result.returncode == 0, result.stdout + result.stderr
        outcome = next(line.removeprefix("TEST_RESULT=") for line in result.stdout.splitlines()
                       if line.startswith("TEST_RESULT="))
        outcome = json.loads(outcome)
        log = tmp_path / "distro" / "install.log"
        outcome["Log"] = log.read_text(encoding="utf-8") if log.exists() else ""
        return outcome, result.stdout + result.stderr

    return run


@pytest.mark.parametrize("import_exit", [0, 23])
def test_unregistered_import_uses_wsl2_fallback(distro_setup, import_exit):
    outcome, output = distro_setup(import_exit=import_exit, import_registers=False)
    assert outcome["Error"] is None, output
    assert len(outcome["Calls"]) == 2
    assert outcome["Calls"][0][0] == "--import"
    fallback = outcome["Calls"][1]
    assert fallback[:2] == ["--install", "Debian"]
    assert fallback[fallback.index("--version") + 1] == "2"
    assert "--unregister" not in str(outcome["Calls"])


def test_registered_import_is_not_recreated_after_an_unusual_exit(distro_setup):
    outcome, output = distro_setup(import_exit=23, import_registers=True)
    assert outcome["Error"] is None, output
    assert len(outcome["Calls"]) == 1
    assert outcome["Calls"][0][0] == "--import"


def test_existing_distribution_is_left_alone(distro_setup):
    outcome, output = distro_setup(already_registered=True)
    assert outcome["Error"] is None, output
    assert outcome["Calls"] == [] and outcome["DownloadCalls"] == 0


@pytest.mark.parametrize("fallback_exit", [0, 87])
def test_failed_distro_creation_keeps_both_wsl_errors(distro_setup, fallback_exit):
    outcome, output = distro_setup(import_exit=23, import_registers=False,
                                  fallback_exit=fallback_exit, fallback_registers=False)
    for details in (outcome["Error"], outcome["Log"]):
        assert "HCS_E_HYPERV_NOT_INSTALLED" in details, output
        assert "Wsl/E_INVALIDARG" in details, output
        assert "exit code 23" in details and f"exit code {fallback_exit}" in details
        assert "--import" in details and "--install" in details
    assert "--unregister" not in str(outcome["Calls"])


@pytest.mark.parametrize("download_fails,checksum_matches", [(True, True), (False, False)])
def test_unverified_debian_images_are_not_imported(distro_setup, download_fails, checksum_matches):
    outcome, output = distro_setup(download_fails=download_fails, checksum_matches=checksum_matches)
    assert outcome["Error"] is None, output
    assert len(outcome["Calls"]) == 1
    assert outcome["Calls"][0][0] == "--install"
    reason = "HTTP 403" if download_fails else "checksum mismatch"
    assert reason in outcome["Log"]


def test_shell_scripts_are_saved_as_utf8_without_crlf_or_bom(powershell, tmp_path):
    dest = tmp_path / "install.sh"
    text = '#!/bin/sh\r\necho "café"\r\n'
    result = powershell(helpers("Save-Lf") + f"Save-Lf {ps_string(text)} {ps_string(dest)}\n")
    assert result.returncode == 0, result.stdout + result.stderr
    assert dest.read_bytes() == text.replace("\r\n", "\n").encode("utf-8")


def test_checkout_paths_keep_spaces_and_unicode(powershell):
    result = powershell(helpers("To-Wsl") + r"""
function Resolve-Path([string]$Path) { [pscustomobject]@{ Path = $Path } }
To-Wsl 'D:\Game projects\José\decomp.wtf' | ConvertTo-Json -Compress
""")
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == "/mnt/d/Game projects/José/decomp.wtf"


@pytest.mark.parametrize("script", ["installer", "connect", "uninstall"])
@pytest.mark.parametrize("sysnative", [False, True])
def test_wsl_uses_native_system_directory(powershell, script, sysnative):
    text = INSTALLER.read_text(encoding="utf-8")
    if script != "installer":
        text = re.search(rf"\${script} = @'\n(.*?)\n'@", text, re.S).group(1)
    # Run only the resolver, including the actual conditional; never run either script's actions.
    resolver = re.search(r'\$[Ww]sl = Join-Path .*?\nif \(Test-Path .*?\n', text).group(0)
    result = powershell(rf"""
$env:SystemRoot = 'C:\Windows'
function Join-Path([string]$Path, [string]$ChildPath) {{ return "$Path\$ChildPath" }}
function Test-Path {{ return ${str(sysnative).lower()} }}
{resolver}
$Wsl | ConvertTo-Json -Compress
""")
    assert result.returncode == 0, result.stdout + result.stderr
    expected = "Sysnative" if sysnative else "System32"
    assert json.loads(result.stdout) == rf"C:\Windows\{expected}\wsl.exe"


def test_failed_unregister_preserves_launcher_and_settings(powershell, tmp_path):
    native = tmp_path / ("wsl.cmd" if sys.platform == "win32" else "wsl")
    native.write_text("@exit /b 7\n" if sys.platform == "win32" else "#!/bin/sh\nexit 7\n")
    native.chmod(0o755)
    embedded = re.search(r"\$uninstall = @'\n(.*?)\n'@", INSTALLER.read_text(encoding="utf-8"), re.S).group(1)
    # Guard every destructive command even if the regression reappears.
    result = powershell(rf"""
$env:SystemRoot = 'C:\Windows'
function Read-Host {{ return 'yes' }}
function Test-Path {{ return $true }}
function Join-Path {{ return {ps_string(native)} }}
function Remove-Item {{ throw 'uninstall removed files after WSL failed' }}
function Start-Process {{ throw 'uninstall started cleanup after WSL failed' }}
{embedded}
""")
    assert result.returncode == 7, result.stdout + result.stderr
    assert "Nothing else removed" in result.stdout + result.stderr


def test_early_setup_failure_does_not_clean_up_callers_temp_folder(powershell, tmp_path):
    sentinel = tmp_path / "caller's temporary folder"
    sentinel.mkdir()
    marker = sentinel / "keep.txt"
    marker.write_text("keep")
    result = powershell(f"""
$env:SystemRoot = {ps_string(tmp_path)}
$env:LOCALAPPDATA = {ps_string(tmp_path)}
$env:PROCESSOR_ARCHITECTURE = 'ARM64'
$env:PROCESSOR_ARCHITEW6432 = $null
$env:WSL_UTF8 = 'caller-value'
$tmp = {ps_string(sentinel)}
$script:removed = $false
function Remove-Item {{ $script:removed = $true; throw 'installer tried to remove the caller temp folder' }}
try {{
    & ([scriptblock]::Create([IO.File]::ReadAllText({ps_string(INSTALLER)})))
    throw 'accepted unsupported architecture'
}} catch {{
    if ($_.Exception.Message -notmatch 'needs a 64-bit Intel or AMD Windows') {{ throw }}
}}
if ($script:removed) {{ throw 'installer tried to clean up the caller temp folder' }}
if ($env:WSL_UTF8 -ne 'caller-value') {{ throw 'installer changed caller WSL_UTF8' }}
""")
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.read_text() == "keep"
