# Security Policy

## Supported versions

Only the [latest release](https://github.com/josedag31/WinAirdrop/releases/latest) receives security fixes.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private reporting instead: go to the **Security** tab of this repository → **Report a vulnerability**. Include:

- what an attacker can do and under which conditions (same network? token needed? a web page the user visits?),
- steps to reproduce,
- the affected version.

You will get an answer as soon as possible. Once a fix is released, the report can be made public with credit to you, if you want it.

## Threat model

WinAirdrop is designed for **trusted local networks** (your home Wi-Fi, your own phone hotspot).

| Attacker | Protection |
|---|---|
| A device on the same network **without the token** | Every upload needs the bearer token (192 bits, constant-time comparison). `/ping` reveals only the app name, network name and version. |
| Someone **with the token** | Can save files to the configured folder. Received programs and unknown file types are never opened or run. Files carry the Mark of the Web, and file names are sanitized (no paths, reserved names or Unicode formatting characters). |
| A **web page** open in the user's browser | The settings page and `/api/*` only accept loopback connections whose `Host` header is `localhost`/`127.0.0.1` (DNS-rebinding protection). Every change needs a per-process anti-CSRF token and a local `Origin`. Responses are `no-store`, can't be framed, and send a restrictive CSP. |
| A device on a **public network** | The firewall rules only cover the Private profile, and networks are marked Private one at a time, by the user, through a UAC prompt. |

### Known limitations

- Traffic is **unencrypted HTTP**. Anyone who can capture traffic on the same network can read the transferred files and the token. Don't use WinAirdrop on networks you don't trust.
- There's no upload size limit. Someone with the token can fill the disk.
- Releases are not code-signed. Verify downloads with `SHA256SUMS.txt`.

## If your token leaks

Settings page → **Reset token** (or delete the `WINAIRDROP_TOKEN` line from `.env` and restart), then paste the new token into your iOS Shortcut.
