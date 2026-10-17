@echo off
setlocal
rem Install this checkout (or extracted source ZIP) with Windows' built-in PowerShell.
rem Use 64-bit PowerShell even when launched from a 32-bit program.
set "DECOMP_POWERSHELL=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "DECOMP_POWERSHELL=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
"%DECOMP_POWERSHELL%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0site\public\install.ps1"
set "DECOMP_SETUP_EXIT=%ERRORLEVEL%"
echo.
if not "%DECOMP_SETUP_EXIT%"=="0" echo Setup did not finish. See the error above, then run windows.cmd again.
rem Keep reboot instructions and errors visible when opened from File Explorer.
pause
exit /b %DECOMP_SETUP_EXIT%
