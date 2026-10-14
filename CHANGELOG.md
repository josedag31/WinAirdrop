# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/josedag31/WinAirdrop/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/josedag31/WinAirdrop/releases/tag/v1.0.0
