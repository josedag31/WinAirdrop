"""Offline tests: safe file names, capture dates and the upload API."""

import calendar
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

import pytest

# Isolated configuration before importing the module (it reads env on import).
_TMP = Path(tempfile.mkdtemp())
os.environ["WINAIRDROP_FOLDER"] = str(_TMP / "received")
os.environ["WINAIRDROP_TOKEN"] = "test-token"
os.environ["WINAIRDROP_NAME"] = "test"
os.environ["WINAIRDROP_NOTIFICATIONS"] = "0"
os.environ["WINAIRDROP_ON_RECEIVE"] = "none"
os.environ["WINAIRDROP_LANGUAGE"] = "en"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import winairdrop as w  # noqa: E402

from aiohttp import FormData  # noqa: E402
from dotenv import dotenv_values  # noqa: E402
from PIL import Image  # noqa: E402


@pytest.mark.parametrize("given, expected", [
    ("../../etc/passwd", "passwd"),
    ("..\\..\\evil:x?.txt", "evil_x_.txt"),
    ("  .hidden. ", "hidden"),
    ("Report.pdf", "Report.pdf"),
])
def test_safe_name(given, expected):
    assert w.safe_name(given) == expected


@pytest.mark.parametrize("given", ["CON.txt", "", "nul"])
def test_safe_name_reserved(given):
    assert w.safe_name(given).startswith("file-")


def test_ios_names():
    for name in ("6F993596-AE46-43AE-88D1-D5A1A8D1C305", "IMG_5107", "IMG_E5107", "FullSizeRender"):
        assert w.IOS_NAME.fullmatch(name)
    for name in ("Report", "IMG_logo", "beach-photo"):
        assert not w.IOS_NAME.fullmatch(name)


def test_photo_date_from_exif(tmp_path):
    path = tmp_path / "a.jpg"
    exif = Image.Exif()
    exif.get_ifd(0x8769)[36867] = "2026:09:19 21:13:20"
    Image.new("RGB", (4, 4)).save(path, exif=exif)
    assert w.name_by_date(path, ".jpg") == "Photo 2026-09-19 21.13.20.jpg"


def test_video_date_from_mvhd(tmp_path):
    utc = calendar.timegm((2026, 9, 19, 19, 13, 20, 0, 0, 0))
    mvhd = struct.pack(">I4sB3xII", 20, b"mvhd", 0, utc + 2082844800, 0)
    data = (struct.pack(">I4s4s", 12, b"ftyp", b"qt  ")
            + struct.pack(">I4s", 108, b"mdat") + b"\0" * 100
            + struct.pack(">I4s", 8 + len(mvhd), b"moov") + mvhd)
    path = tmp_path / "v.mov"
    path.write_bytes(data)
    assert w.video_date(path) == w.time.localtime(utc)
    assert w.name_by_date(path, ".mov").startswith("Video ")


def test_no_date_falls_back_to_arrival_time(tmp_path):
    path = tmp_path / "x.jpg"
    path.write_bytes(b"not an image")
    assert w.name_by_date(path, ".jpg").startswith("Photo ")


@pytest.fixture
def client(aiohttp_client):
    return aiohttp_client(w.create_app())


def _form(*files):
    form = FormData()
    for name, data in files:
        form.add_field("file", data, filename=name)
    return form


async def test_upload_requires_token(client):
    c = await client
    r = await c.post("/upload", data=_form(("x.txt", b"x")))
    assert r.status == 401


async def test_upload_multiple_never_overwrites(client):
    c = await client
    headers = {"Authorization": "Bearer test-token"}
    for _ in range(2):
        r = await c.post("/upload", data=_form(("note.txt", b"hi"), ("other.txt", b"bye")), headers=headers)
        assert r.status == 200
    names = {p.name for p in w.FOLDER.iterdir()}
    assert {"note.txt", "note (1).txt", "other.txt", "other (1).txt"} <= names
    assert not any(n.endswith(".partial") for n in names)


def test_present_respects_setting(monkeypatch):
    calls = []
    monkeypatch.setattr(w.os, "startfile", lambda p: calls.append(("open", p)), raising=False)
    monkeypatch.setattr(w.subprocess, "Popen", lambda args, **k: calls.append(("explorer", args)))
    one, two = Path("a.jpg"), Path("b.jpg")

    monkeypatch.setattr(w, "ON_RECEIVE", "none")
    w.present([one])
    assert calls == []

    monkeypatch.setattr(w, "ON_RECEIVE", "open")
    w.present([one])
    w.present([one, two])  # several files: reveal instead of opening each
    assert calls[0] == ("open", one)
    assert calls[1][0] == "explorer"

    monkeypatch.setattr(w, "ON_RECEIVE", "reveal")
    w.present([one])
    assert calls[2][0] == "explorer"


async def test_ping(client):
    c = await client
    r = await c.get("/ping")
    assert (await r.json())["version"] == w.__version__


# --- Security ------------------------------------------------------------------

def test_safe_name_strips_invisible_rtl_override():
    # "photo<RLO>gpj.exe" would display as "photoexe.jpg" in Explorer.
    assert w.safe_name("photo‮gpj.exe") == "photogpj.exe"
    assert w.safe_name("a​b.txt") == "ab.txt"


@pytest.mark.parametrize("name", ["setup.exe", "run.bat", "x.lnk", "doc.docm", "s.ps1", "app.msi", "noext"])
def test_received_programs_are_never_opened(monkeypatch, name):
    calls = []
    monkeypatch.setattr(w.os, "startfile", lambda p: calls.append(("open", p)), raising=False)
    monkeypatch.setattr(w.subprocess, "Popen", lambda args, **k: calls.append(("explorer", args)))
    monkeypatch.setattr(w, "ON_RECEIVE", "open")
    w.present([Path(name)])
    assert calls and calls[0][0] == "explorer"


async def test_received_files_get_mark_of_the_web(client):
    c = await client
    r = await c.post("/upload", data=_form(("motw.txt", b"x")), headers={"Authorization": "Bearer test-token"})
    path = w.FOLDER / (await r.json())["files"][0]
    with open(f"{path}:Zone.Identifier", encoding="ascii") as f:
        assert "ZoneId=3" in f.read()


@pytest.fixture
async def local(aiohttp_client, monkeypatch, tmp_path):
    """Client for the settings page, with an isolated .env."""
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr(w, "ENV_FILE", env)
    for attr in ("FOLDER", "ON_RECEIVE", "RENAME_BY_DATE", "NOTIFY", "TOKEN"):
        monkeypatch.setattr(w, attr, getattr(w, attr))  # restored after the test
    c = await aiohttp_client(w.create_app())
    monkeypatch.setattr(w, "PORT", c.server.port)
    c.env = env
    return c


def csrf_headers(c, **extra):
    return {"X-CSRF-Token": w.CSRF, "Origin": f"http://127.0.0.1:{c.server.port}", **extra}


async def test_setup_page_works_locally(local):
    r = await local.get("/setup")
    assert r.status == 200
    page = await r.text()
    assert w.CSRF in page and "{{" not in page
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store"


async def test_setup_blocks_dns_rebinding(local):
    # A malicious site re-pointing its own domain to 127.0.0.1 sends its own Host.
    r = await local.get("/setup", headers={"Host": f"evil.example:{local.server.port}"})
    assert r.status == 403


async def test_settings_need_csrf_token(local):
    r = await local.post("/api/settings", json={"on_receive": "none"})
    assert r.status == 403
    r = await local.post("/api/settings", json={"on_receive": "none"},
                         headers={"X-CSRF-Token": "wrong", "Origin": f"http://127.0.0.1:{local.server.port}"})
    assert r.status == 403


async def test_settings_reject_foreign_origin(local):
    r = await local.post("/api/settings", json={"on_receive": "none"},
                         headers={"X-CSRF-Token": w.CSRF, "Origin": "https://evil.example"})
    assert r.status == 403


async def test_settings_save_and_apply(local, tmp_path):
    target = tmp_path / "Mis fotos ñ"
    body = {"folder": str(target), "on_receive": "reveal", "rename_by_date": False,
            "notifications": False, "name": w.NAME, "port": w.PORT}
    r = await local.post("/api/settings", json=body, headers=csrf_headers(local))
    data = await r.json()
    assert r.status == 200 and data["restart_required"] is False
    assert w.FOLDER == target and target.is_dir()
    assert w.ON_RECEIVE == "reveal" and w.RENAME_BY_DATE is False
    saved = dotenv_values(local.env)
    assert Path(saved["WINAIRDROP_FOLDER"]) == target
    assert saved["WINAIRDROP_ON_RECEIVE"] == "reveal"


@pytest.mark.parametrize("field, value", [
    ("port", 80), ("port", "abc"), ("name", "-bad"), ("name", "has space"), ("on_receive", "run"),
    ("language", "fr"),
])
async def test_settings_validation(local, field, value):
    body = {"folder": str(w.FOLDER), "name": w.NAME, "port": w.PORT, "on_receive": "open", field: value}
    r = await local.post("/api/settings", json=body, headers=csrf_headers(local))
    assert r.status == 400
    assert field in (await r.json())["errors"]


@pytest.mark.parametrize("payload", ["[1, 2]", "not json", '"text"'])
async def test_settings_reject_non_object_json(local, payload):
    r = await local.post("/api/settings", data=payload,
                         headers=csrf_headers(local, **{"Content-Type": "application/json"}))
    assert r.status == 400


async def test_name_change_asks_for_restart(local):
    body = {"folder": str(w.FOLDER), "name": "another-name", "port": w.PORT}
    r = await local.post("/api/settings", json=body, headers=csrf_headers(local))
    assert (await r.json())["restart_required"] is True


async def test_trust_only_a_known_network(local, monkeypatch):
    monkeypatch.setattr(w, "system_status", lambda: {"firewall": True, "networks": [{"name": "Home", "category": "Public"}]})
    called = []
    monkeypatch.setattr(w, "fix_network", lambda name=None: called.append(name) or True)
    r = await local.post("/api/fix-network", json={"make_private": "Cafe Wi-Fi"}, headers=csrf_headers(local))
    assert r.status == 400 and called == []
    r = await local.post("/api/fix-network", json={"make_private": "Home"}, headers=csrf_headers(local))
    assert r.status == 200 and called == ["Home"]


# --- Languages -------------------------------------------------------------------

def test_locales_have_the_same_keys():
    en, es = w.STRINGS["en"], w.STRINGS["es"]
    for section in ("app", "page"):
        assert set(en[section]) == set(es[section]), f"missing translations in '{section}'"


def test_every_text_in_the_page_is_translated():
    import re
    page = (w.RESOURCES / "setup.html").read_text(encoding="utf-8")
    used = set(re.findall(r'data-i18n(?:-html|-ph)?="([a-z0-9_]+)"', page))
    used |= {k for k in re.findall(r'\bt\("([a-z0-9_]+)"', page) if not k.endswith("_")}  # skip t("err_" + code)
    used |= {f"err_{code}" for code in ("folder", "port", "name", "on_receive", "language", "generic")}
    for lang in w.LANGUAGES:
        missing = used - set(w.STRINGS[lang]["page"])
        assert not missing, f"{lang}: {sorted(missing)}"


def test_spanish_file_names(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "LANGUAGE", "es")
    path = tmp_path / "x.jpg"
    path.write_bytes(b"no exif")
    assert w.name_by_date(path, ".jpg").startswith("Foto ")
    assert w.name_by_date(path, ".mov").startswith("Vídeo ")
    assert w.t("received_many", n=3) == "3 archivos recibidos"


def test_installer_language_from_registry(monkeypatch):
    key = r"Software\WinAirdropTests\Lang"
    w.winreg.CreateKey(w.winreg.HKEY_CURRENT_USER, key)
    try:
        with w.winreg.OpenKey(w.winreg.HKEY_CURRENT_USER, key, 0, w.winreg.KEY_SET_VALUE) as k:
            w.winreg.SetValueEx(k, "Language", 0, w.winreg.REG_SZ, "es")
        real_open = w.winreg.OpenKey
        monkeypatch.setattr(w.winreg, "OpenKey", lambda root, sub, *a: real_open(root, key if "josedag31" in sub else sub, *a))
        assert w.installer_language() == "es"
    finally:
        w.winreg.DeleteKey(w.winreg.HKEY_CURRENT_USER, key)
        w.winreg.DeleteKey(w.winreg.HKEY_CURRENT_USER, r"Software\WinAirdropTests")


def test_uninstall_never_fails(monkeypatch):
    monkeypatch.setattr(w, "com_object", lambda progid: (_ for _ in ()).throw(OSError("no COM")))
    assert w.uninstall_main() == 0


async def test_language_change_is_saved(local, monkeypatch):
    monkeypatch.setattr(w, "LANGUAGE", "en")
    body = {"folder": str(w.FOLDER), "name": w.NAME, "port": w.PORT, "language": "es"}
    r = await local.post("/api/settings", json=body, headers=csrf_headers(local))
    assert r.status == 200 and w.LANGUAGE == "es"
    assert dotenv_values(local.env)["WINAIRDROP_LANGUAGE"] == "es"
    page = await (await local.get("/setup")).text()
    assert '<html lang="es">' in page and "Ajustes de WinAirdrop" in page


# --- Windows integration (no PowerShell) ----------------------------------------------

def test_no_powershell_anywhere():
    # Antivirus programs block unknown apps that run PowerShell.
    import re
    calls = re.compile(r"""["'=]\s*powershell(\.exe)?\b|EncodedCommand|-ExecutionPolicy""", re.I)
    for path in [w.ROOT / "winairdrop.py", w.ROOT / "installer" / "WinAirdrop.wxs"]:
        assert not calls.search(path.read_text(encoding="utf-8-sig")), path.name


def test_startup_uses_the_run_key(monkeypatch):
    key = r"Software\WinAirdropTests\Run"
    w.winreg.CreateKey(w.winreg.HKEY_CURRENT_USER, key)
    monkeypatch.setattr(w, "RUN_KEY", key)
    monkeypatch.setattr(w, "legacy_startup_link", lambda: Path("Z:/does/not/exist.lnk"))
    try:
        assert w.set_startup(True) and w.startup_enabled()
        with w.winreg.OpenKey(w.winreg.HKEY_CURRENT_USER, key) as k:
            value = w.winreg.QueryValueEx(k, "WinAirdrop")[0]
        assert "winairdrop.py" in value
        assert w.set_startup(False) and not w.startup_enabled()
    finally:
        w.winreg.DeleteKey(w.winreg.HKEY_CURRENT_USER, key)
        w.winreg.DeleteKey(w.winreg.HKEY_CURRENT_USER, r"Software\WinAirdropTests")


def test_system_status_reads_windows_directly():
    status = w.system_status()  # read-only COM calls, no admin needed
    assert status["firewall"] in (True, False)
    assert all(n["category"] in ("Public", "Private", "DomainAuthenticated") for n in status["networks"])


def test_elevated_tasks(monkeypatch):
    calls = []
    monkeypatch.setattr(w, "add_firewall_rules", lambda port: calls.append(("fw", port)))
    monkeypatch.setattr(w, "remove_firewall_rules", lambda: calls.append(("rm",)))
    monkeypatch.setattr(w, "make_network_private", lambda name: calls.append(("net", name)) or name == "Home")
    assert w.elevated_main(["--firewall", "8770", "--private", "Home"]) == 0
    assert calls == [("fw", 8770), ("net", "Home")]
    assert w.elevated_main(["--private", "Nope"]) == 2
    assert w.elevated_main(["--remove-firewall"]) == 0 and calls[-1] == ("rm",)


def test_fix_network_runs_winairdrop_elevated(monkeypatch):
    seen = []
    monkeypatch.setattr(w, "run_elevated", lambda args: seen.append(args) or True)
    assert w.fix_network("Home")
    assert seen == [["--firewall", str(w.PORT), "--private", "Home"]]


# --- Pairing the iPhone Shortcut ---------------------------------------------------------

def test_pairing_qr_carries_only_url_and_auth():
    data = json.loads(w.pairing_data())
    assert data == {"url": f"http://{w.NAME}.local:{w.PORT}/upload", "auth": f"Bearer {w.TOKEN}"}


def test_shortcut_link_falls_back_to_any_language(monkeypatch):
    monkeypatch.setattr(w, "SHORTCUT_LINKS", {"es": "", "en": ""})
    assert w.shortcut_link() == ""
    monkeypatch.setattr(w, "SHORTCUT_LINKS", {"es": "", "en": "https://www.icloud.com/shortcuts/abc"})
    monkeypatch.setattr(w, "LANGUAGE", "es")
    assert w.shortcut_link() == "https://www.icloud.com/shortcuts/abc"


async def test_setup_page_has_pairing_and_url_qr(local):
    page = await (await local.get("/setup")).text()
    assert page.count("data:image/png;base64,iVBOR") >= 3  # pair, URL and token QR codes
    assert '"shortcut_link"' in page


def test_port_in_use_vs_blocked():
    busy = OSError(10048, "Only one usage of each socket address")
    busy.winerror = 10048
    assert w.port_in_use(busy)
    assert w.port_in_use(OSError(98, "Address already in use"))
    denied = OSError(10013, "An attempt was made to access a socket in a way forbidden")
    denied.winerror = 10013
    assert not w.port_in_use(denied)  # antivirus sandbox / firewall: a different message


async def test_reset_token(local):
    old = w.TOKEN
    r = await local.post("/api/reset-token", headers=csrf_headers(local))
    assert r.status == 200 and w.TOKEN != old
    assert dotenv_values(local.env)["WINAIRDROP_TOKEN"] == w.TOKEN
