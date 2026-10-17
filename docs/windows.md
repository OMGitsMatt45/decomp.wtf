# Running decomp.wtf on Windows

The app and its old compilers run together in a dedicated WSL 2 distribution named `decomp-wtf`. You use the
interface in your normal Windows browser. Keeping projects in WSL's Linux filesystem avoids Windows path and
file-ID problems in the old 32-bit compilers.

## Install this source

You need a 64-bit Intel or AMD PC with virtualization enabled, Windows 10 22H2 (build 19045) or newer,
and a current WSL installation. Windows 11 is recommended. Windows on ARM is not supported by these compilers.
The first install needs Internet access and may require a Windows restart.

1. Download the repository's source ZIP and extract it to a local drive, or clone the repository. Open the
   extracted folder containing `windows.cmd`; running inside the ZIP preview will not work.
2. Double-click **`windows.cmd`**. It runs the included installer using Windows PowerShell. You do not need to
   install Python, Git or Node.js on Windows. Approve Windows' prompt if WSL needs to be enabled.
3. If setup asks for a restart, restart Windows and double-click `windows.cmd` again. Setup reuses the existing
   distribution and projects.
4. When setup finishes, the app opens in your browser. Open the included **Demo Quest 64** to check the setup.

From an existing PowerShell window, the equivalent command is:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\site\public\install.ps1
```

This installs the files from this source folder. The public `irm https://decomp.wtf/install.ps1 | iex` command
installs the last upstream release, so it will not include local fixes that have not been released.

For a Git checkout, updates follow the checkout's branch in its GitHub `origin` repository; publish that branch
to your fork before using updates. A source ZIP has no
Git metadata. To install and track a published fork branch explicitly, run this in PowerShell, replacing the
repository and branch with yours:

```powershell
$env:DECOMP_REPO = "owner/decomp.wtf"
$env:DECOMP_BRANCH = "main"
powershell -NoProfile -ExecutionPolicy Bypass -File .\site\public\install.ps1
Remove-Item Env:DECOMP_REPO, Env:DECOMP_BRANCH
```

This downloads the branch from GitHub. Rerun `windows.cmd` with those variables cleared to install your local
source folder again.

## Open it again

Use **decomp.wtf** in the Start menu or its desktop shortcut. In a new PowerShell or Command Prompt window:

```powershell
decomp
```

The shortcuts start the app in a minimized terminal window; typing `decomp` runs it in your current terminal.
Closing that window stops it; `decomp stop` also stops it.
If the browser did not open, `decomp url` prints the address to paste into your browser.

Your projects are at:

```text
\\wsl.localhost\decomp-wtf\home\decomp\Decomp
```

Paste that into File Explorer's address bar. Keep projects there for compilation; the app can import a game
from a Windows drive using a path such as `C:\Games\My Game.iso`. Browser file selection and drag-and-drop also
work. A path beginning `\\wsl.localhost\Ubuntu\...` belongs to a different distribution; copy the game to a
Windows drive or this app's distribution before importing it.

## Connect agents

For an agent CLI already installed on Windows, run this from PowerShell:

```powershell
decomp connect
```

Then ask the agent to import your game using its Windows path. The connection uses `wsl.exe` to reach the app.

Helper agents started by the app run inside its Linux distribution. Install and sign those in there, even if
you already signed in to a Windows installation of the same agent:

```powershell
decomp shell
```

Use the sign-in command shown by **Agents & models** in that terminal.

Local model servers need separate networking consideration: under WSL's default NAT networking, `127.0.0.1`
inside WSL refers to Linux. A model listening only on Windows' localhost will not be reachable at the default
API preset address. On supported Windows 11 systems, WSL's mirrored networking supports connecting to Windows
services through localhost. See [Microsoft's WSL networking guide](https://learn.microsoft.com/windows/wsl/networking)
for mirrored networking and host addressing; test the model endpoint from `decomp shell` before starting agents.

## Troubleshooting

Run these in PowerShell to see the WSL installation and the app's distribution:

```powershell
wsl --version
wsl --status
wsl --list --verbose
```

`decomp-wtf` must show **VERSION 2**. If it shows 1, stop the app and run:

```powershell
wsl --set-version decomp-wtf 2
```

If `wsl --version` is unavailable, update WSL with `wsl --update`, or install the current WSL package from
Microsoft. If WSL is missing, run `wsl --install --no-distribution` from an administrator PowerShell, restart
Windows, then rerun `windows.cmd`. An error about virtualization or `0x80370102` usually needs virtualization
enabled in the PC's BIOS/UEFI and Windows' **Virtual Machine Platform** feature enabled.

If `decomp` is not recognized after setup, open a new terminal or use the Start menu shortcut. The command is
installed in `%LOCALAPPDATA%\decomp.wtf\bin`.

If the app does not start, run `decomp` in PowerShell so its error stays visible. Background startup output is
at `\\wsl.localhost\decomp-wtf\home\decomp\Decomp\.decomp\app.log`; application logs are under
`...\Decomp\.decomp\logs`. Include the error and the WSL version when reporting a failure.

To reinstall or repair the app, run `windows.cmd` again. `decomp uninstall` removes the dedicated distribution
and **every project inside it**, after asking for confirmation. Copy projects elsewhere before uninstalling.

## Validation status

The repository's Windows workflow checks Windows PowerShell 5.1 syntax, generated connection/uninstall scripts,
installer helpers, agent command handling and offline update behavior. Linux tests exercise WSL path translation
and the web API. A full first install still needs validation on a real Windows machine with WSL 2, including
the administrator prompt, restart, Debian import, shortcuts, browser opening and a demo compile.
