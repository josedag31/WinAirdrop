"""WinAirdrop: receive files from iPhone/iPad (iOS Shortcut) on Windows.

- Announces itself on the local network over mDNS as <name>.local, so the
  iPhone finds the PC by name even when its IP changes.
- POST /upload (multipart, one or more "file" fields, bearer token) saves the
  files, shows a notification and opens them on screen like AirDrop on a Mac.
- GET /setup (only from this PC) is the settings page: Shortcut instructions,
  save folder, behaviour, startup, firewall and network checks.
"""

import asyncio
import base64
import hmac
import io
import json
import os
import re
import secrets
import socket
import struct
import subprocess
import sys
import time
import unicodedata
import urllib.request
import webbrowser
import winreg
from html import escape
from pathlib import Path

import ifaddr
import qrcode
from PIL import Image
from aiohttp import web
from dotenv import load_dotenv, set_key
from zeroconf import IPVersion, ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

__version__ = "1.0.1"

FROZEN = getattr(sys, "frozen", False)  # PyInstaller .exe
if FROZEN:
    ROOT = Path(sys.executable).resolve().parent
    RESOURCES = Path(getattr(sys, "_MEIPASS", ROOT))
else:
    ROOT = RESOURCES = Path(__file__).resolve().parent
# The admin copy (firewall / network tasks) must not create or change any settings.
ELEVATED = "--elevated" in sys.argv or "--uninstall" in sys.argv


def config_dir() -> Path:
    """Where .env and the log live.

    A .env next to the program wins (portable use, running from source).
    Otherwise the installed .exe uses %APPDATA%\\WinAirdrop, which is always
    writable, unlike Program Files.
    """
    if (ROOT / ".env").exists() or not FROZEN:
        return ROOT
    base = Path(os.getenv("APPDATA") or Path.home() / "AppData" / "Roaming") / "WinAirdrop"
    base.mkdir(parents=True, exist_ok=True)
    return base


CONFIG_DIR = config_dir()
ENV_FILE = CONFIG_DIR / ".env"
LOG_FILE = CONFIG_DIR / "winairdrop.log"
if not ENV_FILE.exists() and not ELEVATED:
    ENV_FILE.write_text("", encoding="utf-8")

load_dotenv(ENV_FILE, encoding="utf-8")


def known_folder(guid: str, fallback: Path) -> Path:
    """A Windows known folder (honours redirection, e.g. Pictures in OneDrive)."""
    try:
        import ctypes
        from uuid import UUID

        raw = (ctypes.c_byte * 16)(*UUID(guid).bytes_le)
        path = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(raw, 0, None, ctypes.byref(path)) == 0:
            result = Path(path.value)
            ctypes.windll.ole32.CoTaskMemFree(path)
            return result
    except Exception:
        pass
    return fallback


def pictures_folder() -> Path:
    return known_folder("33E28130-4E1E-4676-835A-98395C3BC3BB", Path.home() / "Pictures")


def startup_folder() -> Path:
    return known_folder("B97D20BB-F46A-4C97-BA10-5E3608430854",
                        Path(os.getenv("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup")


def default_name() -> str:
    host = re.sub(r"[^a-z0-9]+", "-", socket.gethostname().lower()).strip("-")
    return f"winairdrop-{host or 'pc'}"[:63].rstrip("-")


def env_flag(key: str, default: bool) -> bool:
    value = (os.getenv(key) or "").strip().lower()
    return default if not value else value not in ("0", "no", "false", "off")


# --- Settings ----------------------------------------------------------------------

NAME_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
ON_RECEIVE_MODES = ("open", "reveal", "none")
LANGUAGES = ("en", "es")


def installer_language() -> str:
    """Language of the installer the user downloaded (English or Español MSI)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\josedag31\WinAirdrop") as key:
            return str(winreg.QueryValueEx(key, "Language")[0]).strip().lower()
    except OSError:
        return ""


def system_language() -> str:
    """Spanish if Windows is in Spanish, English otherwise."""
    try:
        import ctypes
        return "es" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x0A else "en"
    except Exception:
        return "en"


def load_strings() -> dict[str, dict]:
    return {lang: json.loads((RESOURCES / "locales" / f"{lang}.json").read_text(encoding="utf-8"))
            for lang in LANGUAGES}


STRINGS = load_strings()


def t(key: str, **values) -> str:
    """Translated app text (notifications, file names) in the current language."""
    text = STRINGS[LANGUAGE]["app"].get(key) or STRINGS["en"]["app"][key]
    return text.format(**values)


def resolve_folder(value: str) -> Path:
    folder = Path(os.path.expandvars(value.strip().strip('"')))
    return folder if folder.is_absolute() else ROOT / folder


def valid_port(value) -> int | None:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1024 <= port <= 65535 else None


NAME = os.getenv("WINAIRDROP_NAME") or default_name()
if not NAME_RE.fullmatch(NAME):
    NAME = default_name()
PORT = valid_port(os.getenv("WINAIRDROP_PORT") or 8770) or 8770
FOLDER = resolve_folder(os.getenv("WINAIRDROP_FOLDER") or str(pictures_folder() / "WinAirdrop"))
RENAME_BY_DATE = env_flag("WINAIRDROP_RENAME_BY_DATE", True)
NOTIFY = env_flag("WINAIRDROP_NOTIFICATIONS", True)
# What happens on screen when files arrive: "open" (like AirDrop on a Mac),
# "reveal" in File Explorer, or "none".
ON_RECEIVE = (os.getenv("WINAIRDROP_ON_RECEIVE") or "open").strip().lower()
if ON_RECEIVE not in ON_RECEIVE_MODES:
    ON_RECEIVE = "open"
# Settings page / .env first, then the installer the user picked, then Windows.
LANGUAGE = (os.getenv("WINAIRDROP_LANGUAGE") or "").strip().lower()
if LANGUAGE not in LANGUAGES:
    LANGUAGE = installer_language()
if LANGUAGE not in LANGUAGES:
    LANGUAGE = system_language()
TOKEN = os.getenv("WINAIRDROP_TOKEN")
FIRST_RUN = not TOKEN
if not TOKEN and not ELEVATED:
    # First run: generate a token and store it in .env (never in the code).
    TOKEN = secrets.token_urlsafe(24)
    set_key(str(ENV_FILE), "WINAIRDROP_TOKEN", TOKEN, quote_mode="never")

# Per-process secret for the settings page: blocks cross-site requests (CSRF).
CSRF = secrets.token_urlsafe(24)

if not ELEVATED:
    FOLDER.mkdir(parents=True, exist_ok=True)

FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Names iOS uses that say nothing: internal UUID (Photos app), IMG_1234, or
# FullSizeRender (edited photos, common from the iPad).
IOS_NAME = re.compile(r"[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}|IMG_E?\d{4,}|FullSizeRender", re.I)
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10))}
VIDEO = {".mov", ".mp4", ".m4v", ".3gp"}
# Only these are opened automatically. Anything else (.exe, .bat, .lnk, Office
# files with macros...) is shown in File Explorer instead, never run.
SAFE_TO_OPEN = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff",
    ".mov", ".mp4", ".m4v", ".3gp", ".avi", ".mkv", ".webm",
    ".mp3", ".m4a", ".aac", ".wav", ".flac",
    ".pdf", ".txt",
}
VIRTUAL_ADAPTERS = re.compile(
    r"vEthernet|Hyper-V|WSL|Docker|VirtualBox|VMware|Loopback|Bluetooth|TAP-|WireGuard|Tailscale|TunnelBear|ZeroTier",
    re.I)


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S]"), msg, flush=True)


# --- File names --------------------------------------------------------------------

def safe_name(original: str | None) -> str:
    name = (original or "").replace("\\", "/")
    # Invisible formatting characters (e.g. U+202E right-to-left override) can
    # disguise "photo<RLO>gpj.exe" as "photoexe.jpg". Drop them all.
    name = "".join(c for c in name if unicodedata.category(c) != "Cf")
    name = FORBIDDEN.sub("_", Path(name).name).strip(" .")
    if not name or Path(name).stem.upper() in RESERVED:
        name = time.strftime("file-%Y%m%d-%H%M%S") + (Path(name).suffix if name else "")
    return name[:200]


def free_path(name: str) -> Path:
    target = FOLDER / name
    stem, ext = target.stem, target.suffix
    n = 1
    while target.exists() or target.with_name(target.name + ".partial").exists():
        target = FOLDER / f"{stem} ({n}){ext}"
        n += 1
    return target


def photo_date(path: Path) -> time.struct_time | None:
    """EXIF DateTimeOriginal (the camera's local time)."""
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            value = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        return time.strptime(value.strip()[:19], "%Y:%m:%d %H:%M:%S") if value else None
    except Exception:
        return None


def video_date(path: Path) -> time.struct_time | None:
    """creation_time of the mvhd atom (UTC since 1904), converted to local time."""
    try:
        with open(path, "rb") as f:
            start, limit = 0, os.fstat(f.fileno()).st_size
            while start + 8 <= limit:
                f.seek(start)
                size, kind = struct.unpack(">I4s", f.read(8))
                header = 8
                if size == 1:
                    size, header = struct.unpack(">Q", f.read(8))[0], 16
                elif size == 0:
                    size = limit - start
                if size < header:
                    return None
                if kind == b"moov":  # descend into the container
                    start, limit = start + header, start + size
                    continue
                if kind == b"mvhd":
                    version = f.read(1)[0]
                    f.read(3)
                    t = struct.unpack(">Q" if version == 1 else ">I", f.read(8 if version == 1 else 4))[0]
                    return time.localtime(t - 2082844800) if t else None
                start += size
    except Exception:
        return None
    return None


def name_by_date(path: Path, ext: str) -> str:
    is_video = ext in VIDEO
    date = video_date(path) if is_video else photo_date(path)
    stamp = time.strftime("%Y-%m-%d %H.%M.%S", date or time.localtime())
    return f"{t('video' if is_video else 'photo')} {stamp}{ext}"


def mark_of_the_web(path: Path) -> None:
    """Tag the file as coming from another device, like a browser download.

    Windows then shows SmartScreen / Protected View for executables and Office
    files. Only possible on NTFS; silently skipped elsewhere.
    """
    try:
        with open(f"{path}:Zone.Identifier", "w", encoding="ascii") as f:
            f.write("[ZoneTransfer]\r\nZoneId=3\r\n")
    except OSError:
        pass


async def save(read, name: str) -> tuple[Path, int]:
    target = free_path(safe_name(name))
    partial = target.with_name(target.name + ".partial")
    total = 0
    try:
        with open(partial, "wb") as f:
            while chunk := await read(1 << 20):
                f.write(chunk)
                total += len(chunk)
        if RENAME_BY_DATE and IOS_NAME.fullmatch(target.stem):
            target = free_path(name_by_date(partial, target.suffix.lower()))
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    mark_of_the_web(target)
    return target, total


# --- Windows integration --------------------------------------------------------------
# Everything here talks to Windows directly (registry, COM, Win32). No PowerShell:
# antivirus programs block unknown apps that run scripts, and rightly so.

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
FW_GROUP = "WinAirdrop"
NET_CATEGORIES = {0: "Public", 1: "Private", 2: "DomainAuthenticated"}
TRAY = None  # the icon next to the clock, set in main()


def notify(title: str, text: str) -> None:
    """Windows notification from WinAirdrop's own tray icon."""
    if not NOTIFY or TRAY is None:
        return
    try:
        TRAY.notify(text, title)
    except Exception as e:
        log(f"Could not show notification: {e}")


def present(paths: list[Path]) -> None:
    """Show what arrived, like AirDrop on a Mac.

    One safe file (photo, video, audio, PDF, text) opens in its default app.
    Several files, or any other type, are shown selected in File Explorer:
    received files are never executed.
    """
    if ON_RECEIVE == "none" or not paths:
        return
    first = paths[0]
    try:
        if ON_RECEIVE == "open" and len(paths) == 1 and first.suffix.lower() in SAFE_TO_OPEN:
            os.startfile(first)
        else:
            subprocess.Popen(["explorer", "/select,", str(first)])
    except OSError as e:
        log(f"Could not show {first.name}: {e}")


def launch_command() -> list[str]:
    """Command that starts WinAirdrop silently (for startup and elevation)."""
    if FROZEN:
        return [sys.executable]
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return [str(pythonw if pythonw.exists() else exe), str(Path(__file__).resolve())]


def legacy_startup_link() -> Path:
    return startup_folder() / "WinAirdrop.lnk"


def startup_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, "WinAirdrop")
            return True
    except OSError:
        return legacy_startup_link().exists()


def set_startup(enabled: bool) -> bool:
    """Start with Windows via the standard per-user Run registry key."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, "WinAirdrop", 0, winreg.REG_SZ, subprocess.list2cmdline(launch_command()))
            else:
                try:
                    winreg.DeleteValue(key, "WinAirdrop")
                except FileNotFoundError:
                    pass
        if not enabled:
            legacy_startup_link().unlink(missing_ok=True)  # from older versions
    except OSError as e:
        log(f"Could not change startup: {e}")
    return startup_enabled() == enabled


def com_object(progid: str):
    import comtypes
    import comtypes.client
    comtypes.CoInitialize()  # needed once per thread; harmless if repeated
    return comtypes.client.CreateObject(progid, dynamic=True)


def firewall_ok() -> bool | None:
    """Are WinAirdrop's inbound rules (TCP port + mDNS, Private profile) there?"""
    try:
        found = set()
        for rule in com_object("HNetCfg.FwPolicy2").Rules:
            if rule.Grouping == FW_GROUP and rule.Enabled and rule.Direction == 1 \
                    and rule.Action == 1 and rule.Profiles & 2:
                found.add((rule.Protocol, str(rule.LocalPorts)))
        return (6, str(PORT)) in found and (17, "5353") in found
    except Exception as e:
        log(f"Could not read the firewall: {e}")
        return None


def connected_networks() -> list[dict]:
    try:
        nlm = com_object("{DCB00C01-570F-4A9B-8D69-199FDBA5723B}")  # Network List Manager
        return [{"name": str(net.GetName()), "category": NET_CATEGORIES.get(net.GetCategory(), "Public")}
                for net in nlm.GetNetworks(1)]  # 1 = connected networks
    except Exception as e:
        log(f"Could not read the networks: {e}")
        return []


def system_status() -> dict:
    return {"firewall": firewall_ok(), "networks": connected_networks()}


# Admin tasks run in a second copy of WinAirdrop started with admin rights
# (the Windows prompt shows "WinAirdrop", not a script host).

def add_firewall_rules(port: int) -> None:
    policy = com_object("HNetCfg.FwPolicy2")
    remove_firewall_rules(policy)
    for name, protocol, ports in ((f"WinAirdrop (TCP {port})", 6, str(port)), ("WinAirdrop (mDNS)", 17, "5353")):
        rule = com_object("HNetCfg.FWRule")
        rule.Name = name
        rule.Grouping = FW_GROUP
        rule.Description = "Lets your iPhone send files to WinAirdrop. Private networks only."
        rule.Protocol = protocol  # must be set before the ports
        rule.LocalPorts = ports
        rule.Direction = 1  # inbound
        rule.Action = 1  # allow
        rule.Profiles = 2  # Private only
        rule.Enabled = True
        policy.Rules.Add(rule)


def remove_firewall_rules(policy=None) -> None:
    policy = policy or com_object("HNetCfg.FwPolicy2")
    for name in [r.Name for r in policy.Rules if r.Grouping == FW_GROUP]:
        policy.Rules.Remove(name)


def make_network_private(name: str) -> bool:
    nlm = com_object("{DCB00C01-570F-4A9B-8D69-199FDBA5723B}")
    for net in nlm.GetNetworks(1):
        if str(net.GetName()) == name:
            net.SetCategory(1)  # Private
            return True
    return False


def elevated_main(argv: list[str]) -> int:
    """Entry point of the admin copy: WinAirdrop --elevated [--firewall PORT]
    [--remove-firewall] [--private NAME]."""
    import argparse
    parser = argparse.ArgumentParser(prog="WinAirdrop --elevated")
    parser.add_argument("--firewall", type=valid_port)
    parser.add_argument("--remove-firewall", action="store_true")
    parser.add_argument("--private")
    args = parser.parse_args(argv)
    try:
        if args.remove_firewall:
            remove_firewall_rules()
        if args.firewall:
            add_firewall_rules(args.firewall)
        if args.private and not make_network_private(args.private):
            return 2
        return 0
    except Exception as e:
        log(f"Admin task failed: {e}")
        return 1


def is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def uninstall_main() -> int:
    """Run by the uninstaller: remove WinAirdrop's firewall rules, asking for
    admin rights only if there is something to remove. Never fails the uninstall."""
    try:
        has_rules = any(r.Grouping == FW_GROUP for r in com_object("HNetCfg.FwPolicy2").Rules)
        if has_rules:
            remove_firewall_rules() if is_admin() else run_elevated(["--remove-firewall"])
        set_startup(False)
    except Exception as e:
        log(f"Uninstall cleanup: {e}")
    return 0


def run_elevated(args: list[str]) -> bool:
    """Run WinAirdrop with admin rights (UAC prompt) and wait for it."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    command = launch_command() + ["--elevated", *args]
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = command[0]
    info.lpParameters = subprocess.list2cmdline(command[1:])
    info.lpDirectory = str(ROOT)
    info.nShow = 0  # hidden
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        return False  # the user said "No" to the prompt
    kernel32 = ctypes.windll.kernel32
    kernel32.WaitForSingleObject(info.hProcess, 120_000)
    code = wintypes.DWORD()
    kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(info.hProcess)
    return code.value == 0


def fix_network(make_private: str | None = None) -> bool:
    """Firewall rules (Private profile only) and, optionally, mark ONE network
    (chosen by the user, by name) as Private. Never touches the other networks,
    e.g. a café Wi-Fi."""
    args = ["--firewall", str(PORT)]
    if make_private:
        args += ["--private", make_private]
    return run_elevated(args)


def pick_folder(current: Path) -> str | None:
    """Native Windows folder picker, shown on top of the browser."""
    import ctypes
    from ctypes import wintypes

    callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.UINT, wintypes.LPARAM, wintypes.LPARAM)

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [("hwndOwner", wintypes.HWND), ("pidlRoot", ctypes.c_void_p), ("pszDisplayName", wintypes.LPWSTR),
                    ("lpszTitle", wintypes.LPCWSTR), ("ulFlags", wintypes.UINT), ("lpfn", callback_type),
                    ("lParam", wintypes.LPARAM), ("iImage", ctypes.c_int)]

    user32, shell32, ole32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.ole32
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    start = ctypes.create_unicode_buffer(str(current))

    def on_event(hwnd, message, lparam, data):
        if message == 1:  # BFFM_INITIALIZED: preselect the current folder, bring to front
            user32.SendMessageW(hwnd, 0x0467, 1, ctypes.addressof(start))  # BFFM_SETSELECTIONW
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0003)  # HWND_TOPMOST, no move/size
            user32.SetForegroundWindow(hwnd)
        return 0

    callback = callback_type(on_event)  # keep a reference while the dialog is open
    ole32.CoInitializeEx(None, 0x2)  # the new-style dialog needs a single-threaded apartment
    display = ctypes.create_unicode_buffer(260)
    info = BROWSEINFOW(None, None, ctypes.cast(display, wintypes.LPWSTR), t("pick_folder"),
                       0x0001 | 0x0040, callback, 0, 0)  # BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
    pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
    if not pidl:
        return None
    path = ctypes.create_unicode_buffer(32768)
    ok = shell32.SHGetPathFromIDListW(pidl, path)
    ole32.CoTaskMemFree(ctypes.c_void_p(pidl))
    return path.value if ok else None


def start_tray(on_quit) -> object | None:
    """Icon next to the clock: shows WinAirdrop is running, opens the settings,
    the folder, or quits. Also the source of the notifications."""
    try:
        import pystray
        image = Image.open(RESOURCES / "assets" / "icon.png")
        menu = pystray.Menu(
            pystray.MenuItem(lambda item: t("tray_settings"), lambda: webbrowser.open(setup_url()), default=True),
            pystray.MenuItem(lambda item: t("tray_folder"), lambda: os.startfile(FOLDER)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: t("tray_quit"), lambda icon: (icon.stop(), on_quit())),
        )
        icon = pystray.Icon("WinAirdrop", image, "WinAirdrop", menu)
        icon.run_detached()
        return icon
    except Exception as e:
        log(f"No tray icon: {e}")
        return None


# --- Network --------------------------------------------------------------------------

def lan_ips() -> list[str]:
    """IPv4 addresses of the real networks (Ethernet, Wi-Fi, phone hotspot).

    All of them are announced, not just the default route: with cable and
    hotspot at the same time, the iPhone must get the IP of the network it is on.
    """
    ips = []
    for adapter in ifaddr.get_adapters():
        if VIRTUAL_ADAPTERS.search(adapter.nice_name or ""):
            continue
        for ip in adapter.ips:
            if isinstance(ip.ip, str) and not ip.ip.startswith(("127.", "169.254.")):
                ips.append(ip.ip)
    return sorted(set(ips))


# --- HTTP: upload (from the phone) ------------------------------------------------------

def authorized(request: web.Request) -> bool:
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return hmac.compare_digest(token.encode(), TOKEN.encode())


async def upload(request: web.Request) -> web.Response:
    if not authorized(request):
        log(f"Rejected (wrong token) from {request.remote}")
        return web.json_response({"ok": False, "error": "invalid token"}, status=401)

    saved: list[tuple[Path, int]] = []
    if request.content_type.startswith("multipart/"):
        reader = await request.multipart()
        while (part := await reader.next()) is not None:
            if part.filename is None and part.name != "file":
                continue  # text fields that are not files
            saved.append(await save(part.read_chunk, part.filename or ""))
    else:
        # Raw body: file name in the X-Filename header.
        saved.append(await save(request.content.read, request.headers.get("X-Filename", "")))

    if not saved:
        return web.json_response({"ok": False, "error": "no file received"}, status=400)

    for path, size in saved:
        log(f"Received {path.name} ({size / 1e6:.2f} MB) from {request.remote}")
    paths = [p for p, _ in saved]
    text = t("received_one", name=paths[0].name) if len(paths) == 1 else t("received_many", n=len(paths))
    notify("WinAirdrop", text)
    present(paths)
    return web.json_response({"ok": True, "files": [p.name for p in paths]})


async def ping(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "app": "WinAirdrop", "name": NAME, "version": __version__})


# --- HTTP: settings page (only from this PC) --------------------------------------------

def local_hosts() -> set[str]:
    return {f"localhost:{PORT}", f"127.0.0.1:{PORT}", f"[::1]:{PORT}"}


@web.middleware
async def local_only(request: web.Request, handler):
    """/setup and /api/* only for the browser on this PC.

    - The connection must come from loopback.
    - The Host header must be localhost: defeats DNS rebinding, where a web
      page re-points its own domain to 127.0.0.1 to read the token.
    - Changes (POST) need the per-process CSRF token and a local Origin, so a
      web page can't change settings behind your back.
    """
    path = request.path
    if path == "/setup" or path.startswith("/api/"):
        if request.remote not in ("127.0.0.1", "::1") or request.host not in local_hosts():
            raise web.HTTPForbidden(text="Only available from this PC at http://localhost.")
        if request.method != "GET":
            origin = request.headers.get("Origin")
            sent = request.headers.get("X-CSRF-Token", "")
            if (origin and origin not in {f"http://{h}" for h in local_hosts()}) \
                    or not hmac.compare_digest(sent.encode(), CSRF.encode()):
                raise web.HTTPForbidden(text="Invalid request.")
    response = await handler(request)
    if path == "/setup" or path.startswith("/api/"):
        response.headers.update({
            "Cache-Control": "no-store",
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            # connect-src allows other localhost ports: after a port change the
            # page polls the restarted server on its new port.
            "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; "
                                       "script-src 'unsafe-inline'; connect-src 'self' http://localhost:*; "
                                       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        })
    return response


def qr_png(text: str) -> str:
    buf = io.BytesIO()
    qrcode.make(text, box_size=6, border=2).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def current_settings() -> dict:
    return {
        "folder": str(FOLDER),
        "on_receive": ON_RECEIVE,
        "rename_by_date": RENAME_BY_DATE,
        "notifications": NOTIFY,
        "name": NAME,
        "port": PORT,
        "language": LANGUAGE,
        "startup": startup_enabled(),
        "first_run": FIRST_RUN,
    }


def json_for_script(data) -> str:
    """JSON safe inside <script type="application/json">: escape <, > and & so
    no value (a folder name, a translation) can close the tag."""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


async def setup(request: web.Request) -> web.Response:
    page = (RESOURCES / "setup.html").read_text(encoding="utf-8")
    values = {
        "URL": escape(f"http://{NAME}.local:{PORT}/upload"),
        "TOKEN": escape(TOKEN),
        "QR_TOKEN": qr_png(f"Bearer {TOKEN}"),
        "IPS": escape(", ".join(lan_ips()) or "no network"),
        "VERSION": __version__,
        "CSRF": CSRF,
        "SETTINGS": json_for_script(current_settings()),
        "STRINGS": json_for_script({**STRINGS["en"]["page"], **STRINGS[LANGUAGE]["page"]}),
        "LANG": LANGUAGE,
        "CONFIG": escape(str(ENV_FILE)),
    }
    for key, value in values.items():
        page = page.replace("{{" + key + "}}", value)
    return web.Response(text=page, content_type="text/html")


async def api_status(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(system_status))


async def json_body(request: web.Request) -> dict | None:
    """The request's JSON object, {} if there is no body, None if it's invalid."""
    if not request.can_read_body:
        return {}
    try:
        data = await request.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def write_setting(key: str, value: str) -> None:
    set_key(str(ENV_FILE), key, value, quote_mode="always", encoding="utf-8")


async def api_settings(request: web.Request) -> web.Response:
    """Validate, save to .env and apply. Name/port need a restart."""
    global FOLDER, ON_RECEIVE, RENAME_BY_DATE, NOTIFY, LANGUAGE
    data = await json_body(request)
    if data is None:
        return web.json_response({"ok": False, "errors": {"_": "generic"}}, status=400)
    # Errors are codes; the page shows them in the user's language (err_<code>).
    errors: dict[str, str] = {}

    folder = resolve_folder(str(data.get("folder", FOLDER)))
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".winairdrop-{secrets.token_hex(4)}"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        errors["folder"] = "folder"
    on_receive = str(data.get("on_receive", ON_RECEIVE))
    if on_receive not in ON_RECEIVE_MODES:
        errors["on_receive"] = "on_receive"
    language = str(data.get("language", LANGUAGE))
    if language not in LANGUAGES:
        errors["language"] = "language"
    name = str(data.get("name", NAME)).strip().lower()
    if not NAME_RE.fullmatch(name):
        errors["name"] = "name"
    port = valid_port(data.get("port", PORT))
    if port is None:
        errors["port"] = "port"
    if errors:
        return web.json_response({"ok": False, "errors": errors}, status=400)

    FOLDER, ON_RECEIVE, LANGUAGE = folder, on_receive, language
    write_setting("WINAIRDROP_LANGUAGE", LANGUAGE)
    RENAME_BY_DATE = bool(data.get("rename_by_date", RENAME_BY_DATE))
    NOTIFY = bool(data.get("notifications", NOTIFY))
    # Forward slashes: python-dotenv would turn "\\" into "\" (breaking UNC paths).
    write_setting("WINAIRDROP_FOLDER", FOLDER.as_posix())
    write_setting("WINAIRDROP_ON_RECEIVE", ON_RECEIVE)
    write_setting("WINAIRDROP_RENAME_BY_DATE", "1" if RENAME_BY_DATE else "0")
    write_setting("WINAIRDROP_NOTIFICATIONS", "1" if NOTIFY else "0")
    write_setting("WINAIRDROP_NAME", name)
    write_setting("WINAIRDROP_PORT", str(port))

    if "startup" in data and bool(data["startup"]) != startup_enabled():
        await asyncio.to_thread(set_startup, bool(data["startup"]))

    restart = name != NAME or port != PORT
    log(f"Settings saved{' (restart needed)' if restart else ''}. Files -> {FOLDER}")
    # Show the saved name/port (they take effect after the restart).
    settings = {**current_settings(), "name": name, "port": port}
    return web.json_response({"ok": True, "restart_required": restart, "settings": settings})


async def api_browse(request: web.Request) -> web.Response:
    return web.json_response({"path": await asyncio.to_thread(pick_folder, FOLDER)})


async def api_fix_network(request: web.Request) -> web.Response:
    data = await json_body(request)
    if data is None:
        return web.json_response({"ok": False, "error": "Invalid data."}, status=400)
    network = data.get("make_private")
    if network is not None:
        known = {n.get("name") for n in (await asyncio.to_thread(system_status))["networks"]}
        if not isinstance(network, str) or network not in known:
            return web.json_response({"ok": False, "error": "Unknown network."}, status=400)
    ok = await asyncio.to_thread(fix_network, network)
    return web.json_response({"ok": ok, **await asyncio.to_thread(system_status)})


async def api_open_folder(request: web.Request) -> web.Response:
    os.startfile(FOLDER)
    return web.json_response({"ok": True})


async def api_reset_token(request: web.Request) -> web.Response:
    global TOKEN
    TOKEN = secrets.token_urlsafe(24)
    set_key(str(ENV_FILE), "WINAIRDROP_TOKEN", TOKEN, quote_mode="never", encoding="utf-8")
    log("Token reset: update the iPhone Shortcut.")
    return web.json_response({"ok": True})


def relaunch() -> None:
    """Start a fresh copy (it waits for the port) and quit this one."""
    cmd = launch_command()
    # Drop the WINAIRDROP_* values this process loaded, so the new one reads .env.
    env = {k: v for k, v in os.environ.items() if not k.startswith("WINAIRDROP_")}
    env["WINAIRDROP_RELAUNCH"] = "1"
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(cmd, cwd=str(ROOT), env=env, creationflags=flags, close_fds=True)
    os._exit(0)


async def api_restart(request: web.Request) -> web.Response:
    asyncio.get_running_loop().call_later(0.5, relaunch)
    return web.json_response({"ok": True})


async def index(request: web.Request) -> web.Response:
    raise web.HTTPFound("/setup")


def create_app() -> web.Application:
    app = web.Application(middlewares=[local_only])
    app.add_routes([
        web.post("/upload", upload),
        web.get("/ping", ping),
        web.get("/", index),
        web.get("/setup", setup),
        web.get("/api/status", api_status),
        web.post("/api/settings", api_settings),
        web.post("/api/browse", api_browse),
        web.post("/api/fix-network", api_fix_network),
        web.post("/api/open-folder", api_open_folder),
        web.post("/api/reset-token", api_reset_token),
        web.post("/api/restart", api_restart),
    ])
    return app


# --- mDNS ---------------------------------------------------------------------------------

class Announcer:
    """mDNS records: <NAME>.local -> LAN IPs, plus an _http._tcp service."""

    def __init__(self) -> None:
        self.zc: AsyncZeroconf | None = None
        self.info: ServiceInfo | None = None
        self.ips: list[str] = []

    def _info(self, ips: list[str]) -> ServiceInfo:
        return ServiceInfo(
            "_http._tcp.local.",
            f"WinAirdrop ({NAME})._http._tcp.local.",
            addresses=[socket.inet_aton(ip) for ip in ips],
            port=PORT,
            properties={"path": "/upload", "version": __version__},
            server=f"{NAME}.local.",
        )

    async def watch(self) -> None:
        while True:
            ips = lan_ips()
            if ips != self.ips:
                # Zeroconf binds to the interfaces that exist when it is created:
                # after joining a new network (e.g. the iPhone hotspot) it must be
                # recreated so it also listens there.
                await self.close()
                if ips:
                    try:
                        self.zc = AsyncZeroconf(interfaces=ips, ip_version=IPVersion.V4Only)
                        self.info = self._info(ips)
                        await self.zc.async_register_service(self.info, allow_name_change=True)
                        log(f"Announced as {NAME}.local -> {', '.join(ips)} (port {PORT})")
                    except Exception as e:  # never let mDNS take the server down
                        log(f"mDNS error, retrying: {e}")
                        await self.close()
                        ips = []
                else:
                    log("No network; waiting...")
                self.ips = ips
            await asyncio.sleep(10)

    async def close(self) -> None:
        if self.zc:
            try:
                if self.info:
                    await self.zc.async_unregister_service(self.info)
                await self.zc.async_close()
            except Exception:
                pass
        self.zc, self.info = None, None


# --- Main -----------------------------------------------------------------------------

def message_box(title: str, text: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x30)  # warning icon
    except Exception:
        pass


def setup_url() -> str:
    return f"http://localhost:{PORT}/setup"


def running_instance() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/ping", timeout=3) as r:
            return json.load(r).get("app") == "WinAirdrop"
    except Exception:
        return False


async def start_server(runner: web.AppRunner) -> bool:
    # After a restart the old process may still hold the port for a moment.
    attempts = 40 if os.getenv("WINAIRDROP_RELAUNCH") else 1
    for attempt in range(attempts):
        try:
            await web.TCPSite(runner, "0.0.0.0", PORT).start()
            return True
        except OSError:
            if attempt + 1 < attempts:
                await asyncio.sleep(0.25)
    return False


async def main() -> int:
    runner = web.AppRunner(create_app(), access_log=None)
    await runner.setup()
    if not await start_server(runner):
        await runner.cleanup()
        if running_instance():
            # Already running: opening WinAirdrop again just shows the settings.
            webbrowser.open(setup_url())
            return 0
        log(f"Port {PORT} is used by another program. Change WINAIRDROP_PORT in {ENV_FILE}.")
        message_box(t("port_busy_title"), t("port_busy_text", port=PORT))
        return 1
    log(f"WinAirdrop {__version__} listening on port {PORT}. Files -> {FOLDER}")
    log(f"Settings: {setup_url()}")
    if FIRST_RUN or not os.getenv("WINAIRDROP_RELAUNCH") and "--settings" in sys.argv:
        webbrowser.open(setup_url())

    global TRAY
    loop = asyncio.get_running_loop()
    quit_requested = asyncio.Event()
    TRAY = start_tray(lambda: loop.call_soon_threadsafe(quit_requested.set))

    announcer = Announcer()
    watcher = asyncio.create_task(announcer.watch())
    try:
        await quit_requested.wait()
    finally:
        watcher.cancel()
        await announcer.close()
        await runner.cleanup()
    log("WinAirdrop closed from the tray icon.")
    return 0


if __name__ == "__main__":
    if sys.stdout is None:  # pythonw / windowed .exe: no console, log to file
        sys.stdout = sys.stderr = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    if "--uninstall" in sys.argv:
        sys.exit(uninstall_main())
    if ELEVATED:
        sys.exit(elevated_main(sys.argv[sys.argv.index("--elevated") + 1:]))
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        pass
