# Contributing to WinAirdrop

Thanks for helping. Bug reports, ideas, docs fixes and code are all welcome.

## Reporting bugs

[Open a bug report](https://github.com/josedag31/WinAirdrop/issues/new/choose) and include:

- Windows version, and whether you use the `.exe` or the source code.
- iOS / iPadOS version.
- The network type: home Wi-Fi or Personal Hotspot.
- The relevant lines from `winairdrop.log`.

> **Never paste your token** (`WINAIRDROP_TOKEN`) or your `.env` file in an issue.

## Development setup

```powershell
git clone https://github.com/josedag31/WinAirdrop.git
cd WinAirdrop
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

Run the server with a console so you can see the log:

```powershell
.\.venv\Scripts\python.exe winairdrop.py
```

## Pull requests

1. Fork the repo and create a branch from `main`.
2. Keep each change focused: one feature or fix per PR.
3. Add or update tests in `tests/` for any behaviour change. The suite must pass (`pytest`).
4. Update `README.md` and `.env.example` if you add or change a setting.
5. Add a line to `CHANGELOG.md` under **Unreleased**.

### Guidelines

- WinAirdrop must keep working **offline and on the local network only**: no telemetry and no cloud services.
- Keep dependencies few, and pin them in `requirements.txt`.
- Never write paths from your own machine into the code. Use `ROOT`, `pictures_folder()` or settings instead.

## Releases (maintainers)

1. Update `__version__` in `winairdrop.py` and the `CHANGELOG.md`.
2. Tag and push it:
   ```powershell
   git tag v1.2.3
   git push origin v1.2.3
   ```
3. GitHub Actions runs the tests, builds `WinAirdrop.exe` and publishes the release.
