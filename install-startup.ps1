# Adds a shortcut to the Windows Startup folder so WinAirdrop starts when you sign in.
# To undo: .\install-startup.ps1 -Remove   (or delete "WinAirdrop.lnk" from shell:startup)
param([switch]$Remove)

$target = Join-Path ([Environment]::GetFolderPath("Startup")) "WinAirdrop.lnk"
if ($Remove) {
    Remove-Item $target -ErrorAction SilentlyContinue
    Write-Host "WinAirdrop removed from startup."
    exit
}

$s = (New-Object -ComObject WScript.Shell).CreateShortcut($target)
$exe = Join-Path $PSScriptRoot "WinAirdrop.exe"
if (Test-Path $exe) {
    $s.TargetPath = $exe
} else {
    $s.TargetPath = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
    $s.Arguments = "`"$(Join-Path $PSScriptRoot 'winairdrop.py')`""
}
$s.WorkingDirectory = $PSScriptRoot
$s.Description = "WinAirdrop - receive files from your iPhone"
$s.Save()
Write-Host "Created: $target"
