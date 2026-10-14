# Starts WinAirdrop in the background (no window). Log: winairdrop.log
# Uses WinAirdrop.exe if it sits next to this script; otherwise the source code with .venv.
$exe = Join-Path $PSScriptRoot "WinAirdrop.exe"
if (Test-Path $exe) {
    Start-Process -FilePath $exe -WorkingDirectory $PSScriptRoot
    exit
}
$py = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $py)) { Write-Error "WinAirdrop.exe or .venv not found (see README)."; exit 1 }
Start-Process -FilePath $py -ArgumentList "`"$(Join-Path $PSScriptRoot 'winairdrop.py')`"" -WorkingDirectory $PSScriptRoot
