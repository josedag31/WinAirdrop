# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.3] - 2026-10-15

### Fixed
- When an antivirus (e.g. Avast CyberCapture) runs WinAirdrop in its sandbox on first launch and blocks its network port, WinAirdrop now says so and explains what to do, instead of wrongly saying that another program uses the port. The real error is written to the log.
- Opening WinAirdrop while another copy is still starting now waits a few seconds for it instead of showing an error.

## [1.0.2] - 2026-10-15

### Added
- Ready-made iOS Shortcut, shared from iCloud. The settings page now shows two QR codes: **Install the Shortcut** and **Pair it with this PC**. Setting up an iPhone takes two camera scans and no typing.
- The Shortcut keeps its pairing in `Shortcuts/WinAirdrop.txt`; if the PC's token changes, it tells the user and asks to scan the pairing code again.

## [1.0.1] - 2026-10-14

### Changed
- The installer is now a one-click Windows Installer (MSI) package, one per language (English / Español), instead of an Inno Setup wizard. It's run by Windows' own `msiexec` and nothing is unpacked to the temp folder, which antivirus programs (e.g. Avast CyberCapture) blocked.
- The firewall is allowed from the settings page (one Windows prompt) instead of during the installation.
- No PowerShell anywhere: firewall, networks, folder picker and startup use Windows APIs directly; the program is a normal folder instead of a self-extracting `.exe`. Antivirus programs blocked PowerShell launched by WinAirdrop.

### Added
- The settings page can pair the iPhone with two QR codes: one to install a shared Shortcut (once it's published) and one with this PC's address and token, which the Shortcut scans the first time. The address now has its own QR too.
- Every installer is checked on GitHub Actions before it's published (extracted and checked for all the program's files).

### Fixed
- Shortcut steps: "Show in Share Sheet" now comes after the first action, because the info button stays grey until the shortcut has one.

## [1.0.0] - 2026-10-14

First public release.

### Added
- Receive any file from iPhone/iPad through an iOS Shortcut in the Share Sheet.
- Received files open on screen like AirDrop on a Mac (photos, videos, audio, PDF, text); several files are shown in File Explorer.
- Tray icon next to the clock (open settings, open folder, quit) and Windows notifications.
- Settings page: save folder (with a folder picker), on-receive behaviour, smart names, notifications, start with Windows, network name and port, with firewall and network checks and one-click fixes.
- Installer (per-user, no admin rights except the optional firewall step) and portable `.zip`.
- Automatic discovery over mDNS (`<name>.local`) on every real network adapter, re-announced when the network changes (home Wi-Fi ↔ Personal Hotspot).
- Photos and videos renamed by capture date (EXIF `DateTimeOriginal`, MOV/MP4 `mvhd`).
- Opening WinAirdrop again while it's running shows the settings page.
- English and Spanish: chosen in the installer (or the Windows language), and changeable in the settings. Covers the settings page, the Shortcut steps with the exact iOS names, notifications and file names.

### Security
- Bearer-token authentication with a locally generated 192-bit token, with a reset option.
- Received programs and unknown file types are never opened automatically.
- Unicode formatting characters (right-to-left override, zero-width…) are stripped from file names.
- Received files carry the Mark of the Web (Zone.Identifier).
- Settings page restricted to loopback, with Host-header validation (DNS-rebinding protection), anti-CSRF tokens and security headers.
- Firewall rules limited to the Private network profile; networks are trusted one by one, never in bulk.

[Unreleased]: https://github.com/josedag31/WinAirdrop/compare/v1.0.3...HEAD
[1.0.3]: https://github.com/josedag31/WinAirdrop/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/josedag31/WinAirdrop/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/josedag31/WinAirdrop/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/josedag31/WinAirdrop/releases/tag/v1.0.0
