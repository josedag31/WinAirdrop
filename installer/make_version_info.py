"""Writes the Windows version resource for WinAirdrop.exe (Properties → Details).

Usage: python installer/make_version_info.py 1.0.0 build/version_info.txt
"""

import sys
from pathlib import Path

version = sys.argv[1]
numbers = [int(n) for n in version.split("-")[0].split(".")][:4]
numbers += [0] * (4 - len(numbers))
fixed = tuple(numbers)

Path(sys.argv[2]).parent.mkdir(parents=True, exist_ok=True)
Path(sys.argv[2]).write_text(f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={fixed}, prodvers={fixed}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'josedag31'),
      StringStruct('FileDescription', 'WinAirdrop - receive files from your iPhone'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'WinAirdrop'),
      StringStruct('LegalCopyright', 'Copyright (C) 2026 josedag31. MIT License.'),
      StringStruct('OriginalFilename', 'WinAirdrop.exe'),
      StringStruct('ProductName', 'WinAirdrop'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")
print("version info:", version, fixed)
