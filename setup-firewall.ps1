<#
.SYNOPSIS
  Opens what WinAirdrop needs in Windows Firewall, on Private networks only.

.DESCRIPTION
  Creates two inbound rules, limited to the "Private" profile:
    - TCP <Port> (8770 by default): where files arrive.
    - UDP 5353 (mDNS): lets the iPhone find the PC by its .local name.
  Public networks (cafés, campus Wi-Fi) stay closed.
  Asks for administrator rights (UAC) if needed.

.EXAMPLE
  .\setup-firewall.ps1
  .\setup-firewall.ps1 -Port 9000
  .\setup-firewall.ps1 -Remove
#>
param(
    [int]$Port = 8770,
    [switch]$Remove
)

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"", "-Port", $Port)
    if ($Remove) { $arguments += "-Remove" }
    Start-Process powershell -Verb RunAs -ArgumentList $arguments -Wait
    exit
}

$group = "WinAirdrop"
Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue | Remove-NetFirewallRule

if ($Remove) {
    Write-Host "WinAirdrop firewall rules removed."
} else {
    New-NetFirewallRule -Group $group -DisplayName "WinAirdrop (TCP $Port)" -Direction Inbound `
        -Protocol TCP -LocalPort $Port -Action Allow -Profile Private | Out-Null
    New-NetFirewallRule -Group $group -DisplayName "WinAirdrop (mDNS)" -Direction Inbound `
        -Protocol UDP -LocalPort 5353 -Action Allow -Profile Private | Out-Null
    Write-Host "Done: TCP $Port and UDP 5353 are open on Private networks only." -ForegroundColor Green
    Write-Host "Remember to set your home Wi-Fi and your iPhone hotspot to 'Private' in Windows settings."
}
Read-Host "Press Enter to close"
